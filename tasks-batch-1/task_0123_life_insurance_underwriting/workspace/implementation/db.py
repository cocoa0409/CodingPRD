"""In-memory data store.

All state lives in process-local dicts keyed by UUID string. Nothing is
persisted to disk and nothing is seeded at startup — every entity is created
by tests through the declared API surface. A fresh `Store` is constructed on
every boot, so the per-test-server restart wipes all state.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC instant with three fractional digits.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.products = {}
        self.applicants = {}
        self.underwriters = {}
        self.applications = {}
        self.paramed_exams = {}
        self.mib_checks = {}
        self.risk_assessments = {}
        self.policies = {}
        self.beneficiaries = {}
        self.premium_payments = {}
        self.policy_loans = {}
        self.cash_value_entries = {}
        # Monotonic counter providing a stable creation order even when two rows
        # share the same millisecond timestamp.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()
