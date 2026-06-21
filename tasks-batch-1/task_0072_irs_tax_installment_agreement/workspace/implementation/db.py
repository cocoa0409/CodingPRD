import uuid
from datetime import datetime, timezone


class Clock:
    """Server logical clock. Defaults to real UTC, can be overridden for tests."""

    def __init__(self):
        self._override = None

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._override = dt


class Store:
    def __init__(self):
        self.tax_accounts = {}
        self.tax_periods = {}
        self.csed_suspensions = {}
        self.installment_agreements = {}
        self.payments = {}
        self.offers = {}
        self.liens = {}
        self.cnc_determinations = {}
        self.account_events = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


def now_iso(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Module-level singletons (fresh on every process boot — in-memory only)
store = Store()
clock = Clock()
