"""In-memory data store + logical clock. Fresh (empty) on every process boot."""
import uuid
from datetime import datetime, timezone


INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.registrants = {}
        self.jurisdictions = {}
        self.product_classes = {}
        self.tax_rates = {}
        self.rate_notices = {}
        self.registrations = {}
        self.bonds = {}
        self.certificates = {}
        self.movements = {}
        self.events = {}
        self.returns = {}
        self.deposits = {}
        self.claims = {}
        self.audit_cases = {}
        self.clock = INITIAL_CLOCK
        self.seq = 0                      # global insertion sequence (stable ordering)
        self.reg_number_seq = {}          # jurisdiction_id -> counter for registration_number

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()


def new_id():
    return str(uuid.uuid4())
