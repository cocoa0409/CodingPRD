"""In-memory data store. Starts empty on every boot — no seeding ever."""
import threading


class Store:
    def __init__(self):
        self.programs = {}
        self.markets = {}
        self.municipalities = {}
        self.sites = {}
        self.drawings = {}
        self.permits = {}
        self.contractors = {}
        self.packages = {}
        self.bids = {}
        self.mobilizations = {}
        self.change_orders = {}
        self.punch_items = {}
        self.turnovers = {}
        self.commitments = {}
        self._seq = 0
        self.lock = threading.RLock()

    def next_seq(self):
        with self.lock:
            self._seq += 1
            return self._seq


store = Store()
