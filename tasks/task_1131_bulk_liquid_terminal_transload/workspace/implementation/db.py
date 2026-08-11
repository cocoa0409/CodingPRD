"""In-memory data store. Plain dicts keyed by id. A fresh process starts
completely empty: no seeding, no preloading, no external persistence."""
import uuid


def new_id():
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        self.customers = {}
        self.tanks = {}
        self.resources = {}
        self.leases = {}
        self.amendments = {}
        self.allocations = {}
        self.permits = {}
        self.movements = {}
        self.gauge_tickets = {}
        self.samples = {}
        self.custody_transfers = {}
        self.statements = {}
        self.movement_sequence = 0


# Module-level singleton. Rebooting the process resets everything.
STORE = DB()
