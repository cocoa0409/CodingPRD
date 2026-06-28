"""In-memory data store for the Ortho Dental Office API.

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.

Records are plain dicts keyed by their UUID id. A monotonically increasing
sequence number is stamped on every record (`_seq`) and used as the deterministic
sort key for list endpoints (PRD §2.3 default sort is created_at ASC; the seq is
a stable tiebreaker for records minted within the same millisecond, and ordering
by created_at then seq is equivalent to creation order). The same sequence also
gives claims their chronological created-order tiebreak (PRD §3.6).
"""

import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.family_accounts = {}
        self.patients = {}
        self.providers = {}
        self.chairs = {}
        self.growth_records = {}
        self.insurance_policies = {}
        self.treatment_plans = {}
        self.treatment_phases = {}
        self.contracts = {}
        self.installments = {}
        self.payments = {}
        self.insurance_claims = {}
        self.appointments = {}
        self.retainers = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Resource created_at/updated_at wall-clock timestamp: ISO 8601 UTC with
    three fractional digits. Distinct from the logical business clock."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
