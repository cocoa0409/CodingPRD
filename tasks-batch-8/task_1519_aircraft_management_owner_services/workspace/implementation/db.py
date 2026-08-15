"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
import itertools
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.owners = {}
        self.aircraft = {}
        self.agreements = {}
        self.budgets = {}
        self.expenses = {}
        self.statements = {}
        self.crew = {}
        self.trips = {}
        self.assignments = {}
        self.programs = {}
        self.events = {}
        self.filings = {}
        self.contracts = {}
        # monotonically increasing creation sequence used as created_at tiebreaker
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()
