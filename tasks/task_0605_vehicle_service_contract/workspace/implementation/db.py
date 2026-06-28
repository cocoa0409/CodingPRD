"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
import random
import string
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Each entity collection keyed by id.
        self.coverage_plans = {}
        self.reinsurance_pools = {}
        self.contracts = {}
        self.ancillary_products = {}
        self.repair_facilities = {}
        self.claims = {}
        self.claim_lines = {}
        self.repair_authorizations = {}
        self.cancellations = {}
        self.ledger_entries = {}
        self.audit_events = {}
        # Logical clock. Startup default per PRD §2.4.
        self.clock_utc = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # monotonic sequence to break created_at ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock as ISO 8601 UTC with three fractional digits."""
    return fmt_iso(db.clock_utc)


def fmt_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    rand = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rand
