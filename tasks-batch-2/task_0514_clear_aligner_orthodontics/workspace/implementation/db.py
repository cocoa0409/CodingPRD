"""In-memory data store.

All state lives in Python dicts keyed by id. The store starts EMPTY on every
boot — no entity is seeded, preloaded, or hardcoded. start.sh re-invocation
wipes every byte of state and guarantees a fresh boot.
"""
import uuid


class DB:
    def __init__(self):
        self.patients = {}
        self.clinicians = {}
        self.cases = {}
        self.intake_records = {}
        self.plans = {}
        self.aligner_steps = {}
        self.shipments = {}
        self.checkins = {}
        self.refinements = {}
        self.financing_plans = {}
        self.installments = {}
        self.retainers = {}
        self.refunds = {}
        # monotonic sequence used only to order creations deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())
