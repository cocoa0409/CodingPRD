"""In-memory data store.

Plain Python dicts keyed by entity id. The store starts EMPTY on every boot;
no entities are seeded, preloaded, or hardcoded. Every record any test needs is
created through the declared API surface.
"""
import itertools
import uuid

from clock import clock


class DB:
    def __init__(self):
        self.issuers = {}
        self.offerings = {}
        self.investors = {}
        self.accreditation_requests = {}
        self.investments = {}
        self.escrow_accounts = {}            # keyed by escrow id
        self.escrow_by_offering = {}         # offering_id -> escrow id
        self.cap_table_entries = {}
        self.investor_updates = {}
        self.investor_wallets = {}           # investor_id -> credited cents (refund destination)
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return clock.now_iso()


db = DB()
