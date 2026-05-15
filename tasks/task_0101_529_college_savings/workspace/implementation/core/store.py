"""In-memory data store and ID/sequence helpers."""

import uuid
import threading
from datetime import datetime, timezone


_LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.donors = {}                       # id -> dict
        self.beneficiaries = {}
        self.accounts = {}
        self.contributions = {}
        self.withdrawals = {}
        self.recurring_plans = {}
        self.beneficiary_change_requests = {}
        self.education_expenses = {}           # id -> dict
        self.tax_reports = {}
        self.state_rules = {}                  # state_code -> dict (keyed by code AND id)
        self.state_rules_by_id = {}            # id -> dict
        self._created_seq = 0                  # monotonic ordering tie-breaker

    def next_seq(self) -> int:
        self._created_seq += 1
        return self._created_seq


STORE = Store()


def lock():
    return _LOCK


def gen_id() -> str:
    return str(uuid.uuid4())


def gen_request_id() -> str:
    # Per PRD §2.2: starts with req_ followed by alphanumeric
    return "req_" + uuid.uuid4().hex[:20]


def iso_now_from_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
