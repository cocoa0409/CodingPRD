"""In-memory data store. Empty at every boot — no seeding."""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def now_iso(self):
        return self._current.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"

    def date_str(self):
        return self._current.strftime("%Y-%m-%d")

    def set(self, iso_str):
        # Parse ISO8601, allow trailing Z
        s = iso_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._current = dt
        return self.now_iso()


clock = LogicalClock()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return clock.now_iso()


def current_date_str():
    return clock.date_str()


# ---------------------------------------------------------------------------
# Stores — all empty at startup
# ---------------------------------------------------------------------------
securities = {}          # id -> Security dict
beneficial_owners = {}   # id -> BeneficialOwner dict
borrowers = {}           # id -> Borrower dict
lendable_positions = {}  # id -> LendablePosition dict
borrow_requests = {}     # id -> BorrowRequest dict
loans = {}               # id -> Loan dict
pledges = {}             # id -> CollateralPledge dict
margin_calls = {}        # id -> MarginCall dict
recalls = {}             # id -> Recall dict
reinvestments = {}       # id -> ReinvestmentTranche dict
ledger_entries = {}      # id -> RevenueLedgerEntry dict
limit_overrides = {}     # id -> LimitOverride dict
regulatory_reports = {}  # id -> RegulatoryReport dict
period_closes = {}       # period string (YYYY-MM) -> PeriodClose dict
