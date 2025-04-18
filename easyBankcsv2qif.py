#!/usr/bin/python
'''
TODO: fill me


based and inspired by http://code.google.com/p/xlscsv-to-qif/

Author: github@2cef.eu
Date: 08.04.2025
'''

from __future__ import print_function
import sys
import csv
import re
import argparse
import datetime as dt

# global var for enabling debugging
doDebug = False



def createArgParser():
    parser = argparse.ArgumentParser(description='Convert an easybank or BAWAG CSV export file to QIF format')
    parser.add_argument('type', choices=['CCard', 'Bank'],
                        help='specify the csv type, default is Bank')
    parser.add_argument('file', help='input file in CSV format. If file is - sdtin is used')
    parser.add_argument('-o', '--output',
                        help="output file, to write the resulting QIF. If not given stdout is used")
    parser.add_argument('-d', '--debug', action="store_true",
                        help='print debugging information to stderr, this option includes -s')
    parser.add_argument('-s', '--summary', action="store_true",
                        help='print a summary to stderr')
    parser.add_argument('-t', '--encto',
                        help='change the encoding to specified one \
                              a list of valid encodings can be found here: \
                              http://docs.python.org/2/library/codecs.html#standard-encodings')
    parser.add_argument('-f', '--encfrom',
                        help='specify encoding for the input file')
    parser.add_argument('--dateformat',
                        help=r'specify the date format for the input file, default is "%%Y-%%m-%%d"')


    return parser



class Transaction(object):
    """ Transaction object, represents one transaction exratcted from the CSV
        file
    """
    def __init__(self, csvtype: str):
        object.__init__(self)
        self.account = ""
        self.csvtype = csvtype
        self.description = ""
        self.date = ""
        self.valutadate = ""
        self.amount = "0"
        self.currency = "EUR"
        self.id = ""
        self.type = None
        self.payee = None
        self.memo = None
        # debug types
        self.htype = ""
        self.desc1 = ""
        self.desc2 = ""
        self.types = set()


    def setTransaction(self, account, description, date, valutadate, amount, currency):
        self.account = account
        self.description = description
        self.date = dt.datetime.strptime(date, '%d.%m.%Y').strftime('%Y-%m-%d')
        self.valutadate = valutadate
        self.amount = amount.replace('.', '').replace(',', '.')
        self.currency = currency
        self.parseDescription()


    def parseDescription(self):
        """ parses the description field to get more detailed information
        """
        if self.csvtype == "CCard":
            d_list = self.description.split("|")
            self.payee = d_list[0].strip()
            if len(d_list) > 1:
                self.desc1 = d_list[1].strip()
            self.memo = self.description
        if self.csvtype == "Bank":
            r = re.match(r"^(.*)\W*([A-Z]{2})/([0-9]+)\W*(.*)?$", self.description)
            if r is not None:
                self.desc1 = r.group(1).strip()
                self.type = r.group(2)
                self.id = r.group(3)
                self.desc2 = r.group(4).strip()
                # Cash withdraw
                if (self.type == "BG" and \
                    (self.desc1 == "Auszahlung Karte" or self.desc1 == "Auszahlung Maestro")):
                    self.htype = "withdraw"
                    self.memo = "{} {}".format(self.desc1, self.desc2)
                    self.payee = "Myself"

                # transfer
                elif (self.type == "BG" or self.type == "FE") \
                   and len(self.desc2) > 0 and len(self.desc1) > 0:
                    self.htype = "transfer"
                    self.desc2 = self.desc2.split("|")[:-1]
                    self.desc2 = "|".join(self.desc2)
                    m = re.match(r"^(([A-Z0-9]+\W)?[A-Z]*[0-9]+)\W(\w+\W+\w+)\W*(.*)$", self.desc2)
                    if m is not None:
                        self.payee = m.group(3) + ' ' + m.group(4)
                        self.desc2 = m.group(1)
                        self.memo = self.desc1 + " " + m.group(4)
                    else:
                        m = re.match(r"^([A-Z]{2}[0-9]{18})\s+(.*)$", self.desc2)
                        if m is not None:
                            self.payee = m.group(2) + ' ' + m.group(3)
                            self.desc2 = m.group(2)
                            self.memo = m.group(2)

                # BG can meen "Bankgebuehren" (bankfee), therefore the desc2 XOR desc1 is empty
                elif (self.type in ["BG", "RI"] and len(self.desc2) == 0):
                    self.memo = self.desc1
                    self.payee = "Bank"
                    self.htype = "bankfee"

                elif (self.type in ["BG", "RI"] and len(self.desc1) == 0):
                    self.memo = self.desc2
                    self.payee = "Bank"
                    self.htype = "bankfee"

                # not really a transfer, but use the information we have
                elif self.type == "MC" and len(self.desc1) == 0:
                    self.memo = self.desc2

                elif self.type == "MC" and len(self.desc2) == 0:
                    self.memo = self.desc1

                # Maestro card (cash card) things
                elif self.type == "MC" \
                    and len(self.desc1) > 0 and len(self.desc2) > 0:
                    # withdraw with cash card
                    m1 = re.match(r"^((Auszahlung)\W+\w+)\W*(.*)$", self.desc1)

                    # payment with cash card
                    m2 = re.match(r"^((Bezahlung)\W+\w+)\W*(.*)$", self.desc1)

                    if m1 is not None:
                        self.htype = "withdraw"
                        self.memo = m1.group(1)
                        if len(m1.group(3)) > 0:
                            self.memo += " (" + m1.group(3) + ")"
                        self.memo += " " + self.desc2
                        self.payee = "Myself"

                    elif m2 is not None:
                        self.htype = "payment"
                        self.memo = m2.group(1)
                        if len(m2.group(3)) > 0:
                            self.memo += " (" + m2.group(3) + ")"
                        self.memo += " " + self.desc2


                    else:
                        # credit card bill and other infos
                        if re.match(r"^Abrechnung.*", self.desc2):
                            self.htype = "credit card bill"
                        else:
                            self.htype = "unknown"
                        self.memo = "{} {}".format(self.desc1, self.desc2)
                        self.payee = "Bank"


                # mixture of transfer, cash card payments
                elif self.type == "VD":
                    # if we have a value for desc1 but not for desc2
                    # it may be a cash card payment
                    if len(self.desc1) > 0 and len(self.desc2) == 0:
                        self.htype = "payment"
                        self.memo = self.desc1

                    # if we have values for both desc fields it may be a transfer
                    elif len(self.desc1) > 0 and len(self.desc2) > 0:
                        self.htype = "transfer"
                        self.memo = self.desc1
                        m = re.match(r"^(([A-Z0-9]+\W)?[A-Z]*[0-9]+)?\W*(\w+)\W*(.*)$", self.desc2)
                        if m is not None:
                            self.payee = m.group(3) + ' ' + m.group(4)
                            #if m.group(1) is not None:
                            #    self.payee += " (" + m.group(1) + ")"

                # OG also seems to be a payment transaction
                elif self.type == "OG":
                    self.htype = "payment"
                    if len(self.desc1) > 0 and len(self.desc2) > 0:
                        self.memo = self.desc1
                        m = re.match(r"^(([A-Z0-9]+\W)?[A-Z]*[0-9]+)?\W*(\w+\W+\w+)\W*(.*)$", self.desc2)
                        if m is not None:
                            self.payee = m.group(3) + ' ' + m.group(4)
                            #if m.group(1) is not None:
                            #    self.payee += " (" + m.group(1) + ")"
                            self.memo += " " + m.group(4)
                    else:
                        # here we have desc1 and desc2
                        self.memo = "{} {}".format(self.desc1, self.desc2)


                # seems to be an cash card payment, however, I don't have enough
                # infos about it
                #elif self.type == "OG":
                else:
                    # use what we have
                    self.memo = self.desc1 + " " + self.desc2

            # if we got an unkown description field, use it as memo
            else:
                self.memo = self.description

            if self.htype == "":
                self.htype = 'unknown'

            # finally, some clean up
            self.memo = self.cleanStr(self.description)
            self.payee = self.cleanStr(self.payee)


    def cleanStr(self, string):
        if string is not None:
            # remove too much whitespace
            # begin and end and more than two in the middle
            pat = re.compile(r'\s\s+')
            string = pat.sub(" ", string.strip())

        return string


    def printDebug(self, raw=None):
        if raw is not None:
            print('CSV line: "{}"'.format(raw), file=sys.stderr)
        print('account: {},'.format(self.account),
              'date: {},'.format(self.date),
              'amount: {} {}'.format(self.amount, self.currency),
              file=sys.stderr)

        print('desc: {}'.format(self.description),
              'type,h: {},{}'.format(self.type, self.htype),
              #'   id: {}'.format(self.id),
              '    2: {}'.format(self.desc2),
              '    1: {}'.format(self.desc1),
              'payee: {}'.format(self.payee),
              ' memo: {}'.format(self.memo),
              '-------------------------------------------',
              file=sys.stderr, sep='\n')


    def getQIFstr(self):
        ret = 'D{}\n'.format(self.date) + \
              'T{}\n'.format(self.amount) + \
              'M{}\n'.format(self.memo)

        if self.payee is not None:
            ret += 'P{}\n'.format(self.payee)
        info = None
        if self.htype is not None:
            info = self.htype
        elif self.type is not None:
            info = self.type
        if info is not None:
            ret += 'N{}\n'.format(info)
        ret += '^\n'
        return ret



class EasyCSV2QIFconverter:
    """ create for each row of the given CSV a Transaction object
        a outputs this Transaction object to the given output file stream
    """
    def __init__(self, instream, outstream, csvtype, dateformat='%Y-%m-%d'):
        self._instream = instream
        self._outstream = outstream
        self._csvtype = csvtype
        self._transSummary = {}
        self._dateformat = dateformat

    def convert(self):
        print(f'!Type:{self._csvtype}', file=self._outstream)

        delimiter = ';'
        rows = csv.reader(self._instream, delimiter=delimiter)
        for l in rows:
            if len(l) < 6:
                print ('ignoring invalid line:', l, file=sys.stderr)
                continue

            t = Transaction(self._csvtype)
            t.setTransaction(l[0],  # account
                             l[1],  # description
                             l[2],  # date
                             l[3],  # valutadate
                             l[4],  # amount
                             l[5])  # currency

            self._outstream.write(t.getQIFstr())

            # some debugging
            if doDebug:
                t.printDebug(';'.join(l))

            # count abount of different transaction types
            if t.htype in self._transSummary:
                self._transSummary[t.htype] += 1
            else:
                self._transSummary[t.htype] = 1


    def getSummary(self):
        ret = ""
        count = 0
        for k, v in self._transSummary.items():
            ret += '  {}:\t{}\n'.format(k, v)
            count += v
        ret += 'total transcation converted: {}\n'.format(count)
        return ret

    def printSummary(self):
        print(self.getSummary(), file=sys.stderr)



if __name__ == "__main__":
    parser = createArgParser()
    args = parser.parse_args()
    if args.debug:
        doDebug = True

    outstream = None
    instream = None

    if args.file != "-":
        try:
            instream = open(args.file, mode='r', encoding=args.encfrom)
        except IOError as detail:
            print('could not open input file:', detail, file=sys.stderr)
            sys.exit(1)

    else:
        instream = sys.stdin


    if args.output:
        try:
            outstream = open(args.output, mode='w', encoding=args.encto)
        except IOError as detail:
            print('could not open output file:', detail, file=sys.stderr)
            sys.exit(1)

    else:
        outstream = sys.stdout

    converter = EasyCSV2QIFconverter(instream, outstream, args.type, args.dateformat)

    converter.convert()
    if args.debug or args.summary:
        converter.printSummary()

    if args.file != "-":
        instream.close()
    if args.output:
        outstream.close()


