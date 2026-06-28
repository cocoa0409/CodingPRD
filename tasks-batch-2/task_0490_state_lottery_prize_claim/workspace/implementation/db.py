"""In-memory data store. Every dict starts empty on each boot — no seeding."""
import itertools


class DB:
    def __init__(self):
        self.games = {}
        self.retailers = {}
        self.terminals = {}
        self.players = {}
        self.tickets = {}
        self.prize_claims = {}
        self.drawings = {}
        self.entries = {}
        self.settlements = {}
        self.escheat_records = {}
        # Monotonic sequence used as a stable secondary sort key so that
        # created_at ties resolve in insertion order deterministically.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()
