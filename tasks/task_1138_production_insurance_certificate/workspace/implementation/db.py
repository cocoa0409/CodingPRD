"""In-memory data store and logical clock.

Everything lives in module-level dicts; each start.sh invocation boots a
fresh process, so state starts empty every time. Nothing is seeded.
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.productions = {}
        self.policies = {}
        self.cast_members = {}
        self.cast_endorsements = {}
        self.certificates = {}
        self.claims = {}
        self.claim_events = {}
        self.clearance_items = {}
        self.completion_bonds = {}          # id -> bond
        self.bond_by_production = {}        # production_id -> bond id
        self.travel_extensions = {}
        self.payroll_audits = {}
        self.renewal_offers = {}
        # monotonic creation sequence for stable created_at tie-breaking
        self.seq = 0
        # per-production certificate issuance sequence
        self.cert_seq = {}
        # logical clock: boots at exactly 2026-05-01T00:00:00Z; never falls
        # back to wall-clock before the first set_current_utc call.
        self.current_utc = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def next_cert_seq(self, production_id):
        n = self.cert_seq.get(production_id, 0) + 1
        self.cert_seq[production_id] = n
        return n


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]
