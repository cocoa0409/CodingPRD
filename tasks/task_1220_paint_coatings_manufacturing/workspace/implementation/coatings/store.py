"""In-memory data store. Fresh process per test -> fresh store. Never seeded."""
import secrets
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.tint_bases = {}
        self.colorants = {}
        self.formulas = {}
        self.formula_lines = {}
        self.voc_rules = {}
        self.mills = {}
        self.batches = {}
        self.batch_adjustments = {}
        self.color_matches = {}
        self.containers = {}
        self.orders = {}
        self.credit_claims = {}
        self.disposal_requests = {}
        self.seq = 0
        self.batch_code_seq = 0
        # Logical clock default: exactly 2026-05-01T00:00:00Z; never wall-clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + secrets.token_hex(10)


def next_seq():
    store.seq += 1
    return store.seq


def next_batch_code():
    store.batch_code_seq += 1
    return "B-%06d" % store.batch_code_seq


def now():
    return store.clock
