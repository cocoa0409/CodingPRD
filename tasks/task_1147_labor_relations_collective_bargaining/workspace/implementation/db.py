"""In-memory data store. Starts empty on every boot; no seeding ever."""

import itertools
import threading


class Store:
    def __init__(self):
        self.unions = {}
        self.agreements = {}
        self.clauses = {}
        self.sessions = {}
        self.proposals = {}
        self.scenarios = {}
        self.votes = {}
        self.letters = {}
        self.practices = {}
        self.requests = {}
        self.tasks = {}
        # monotonic insertion counter, used as stable tiebreak for created_at sort
        self.seq = itertools.count(1)
        self.lock = threading.RLock()


db = Store()
