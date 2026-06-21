"""In-memory data store. Everything is wiped on process start — no persistence.

Storage is plain Python dicts keyed by entity id. Nothing is seeded at import
or startup; tests build all state via the API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_ts():
    # ISO 8601 UTC, three fractional digits (PRD §2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    """Per-entity dicts plus a per-policy internal premium ledger.

    A single re-entrant lock serializes all mutations so multi-step cascades
    (bind, payment, lapse) are atomic with respect to one another.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.properties = {}
        self.risk_assessments = {}
        self.inspectors = {}
        self.inspections = {}
        self.applications = {}
        self.endorsements = {}
        self.quotes = {}
        self.policies = {}
        self.payments = {}
        self.underwriters = {}
        # policy_id -> list of {"type": "DEBIT"|"CREDIT", "amount": Decimal, "reason": str}
        self.ledgers = {}
        # monotonically increasing insertion sequence to allow stable created_at ordering
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
