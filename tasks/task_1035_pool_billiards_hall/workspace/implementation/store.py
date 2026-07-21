"""In-memory data store. Every process boot starts empty; nothing is seeded."""
from common import DEFAULT_CLOCK


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.plans = {}
        self.members = {}
        self.tables = {}
        self.reservations = {}
        self.sessions = {}
        self.fnb_orders = {}
        self.tournaments = {}
        self.entries = {}
        self.products = {}
        self.repairs = {}
        self.events = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
