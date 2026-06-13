"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.plans = {}
        self.travelers = {}
        self.policies = {}
        self.insured_travelers = {}
        self.named_storms = {}
        self.claims = {}
        self.claim_expenses = {}
        self.claim_documents = {}
        self.payouts = {}
        self.refunds = {}
        # Monotonic insertion counter to give a stable creation order independent
        # of timestamp collisions (timestamps only have ms resolution).
        self._seq = 0
        # Logical server clock (test-driven). None until the test sets it; when
        # None we fall back to real UTC now.
        self.current_clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
