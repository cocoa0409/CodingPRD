"""In-memory data store. Starts completely empty on every boot — no seeding."""


class Store:
    def __init__(self):
        # entity name -> { id: record-dict }
        self.employers = {}
        self.employees = {}
        self.programs = {}
        self.enrollments = {}
        self.hras = {}
        self.screenings = {}
        self.challenges = {}
        self.participations = {}
        self.events = {}
        self.ledger = {}
        self.awards = {}
        self.referrals = {}
        self.invoices = {}
        self.reports = {}
        # request-order sequence: settles "computed after the latest close"
        # ties when the logical clock reads the same instant for both
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()
