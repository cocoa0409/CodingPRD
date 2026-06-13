"""In-memory data store. All state is wiped on every process boot.

NO seeding, NO preloaded entities — tests build every entity via the API.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Each is a dict keyed by entity id -> record dict.
        self.insurers = {}
        self.insureds = {}
        self.certificate_holders = {}
        self.policies = {}
        self.endorsements = {}
        self.certificates = {}
        self.claims = {}
        self.claim_transactions = {}
        self.audits = {}
        self.exposure_records = {}
        self.loss_runs = {}
        # Monotonic counter to guarantee strictly increasing created_at ordering
        # even when two records are created within the same millisecond.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now_real():
    # Real wall-clock timestamp for created_at / updated_at, ISO 8601 UTC, 3 frac digits.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
