"""In-memory data store plus logical clock.

The store starts completely empty on every boot; tests build all state via the
declared API surface. The logical clock starts at exactly 2026-05-01T00:00:00Z
and is only advanced through POST /_clock/set_current_utc.
"""
import itertools
import uuid
from datetime import datetime, timezone

START_CLOCK_RAW = "2026-05-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now():
    return fmt_ts(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware datetime (UTC default)."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Store:
    def __init__(self):
        self.customers = {}
        self.formulas = {}
        self.reviews = {}
        self.components = {}
        self.lots = {}
        self.orders = {}
        self.batches = {}
        self.ipc_checks = {}
        self.allocations = {}
        self.shortfalls = {}
        self.lines = {}
        self.runs = {}
        self.chambers = {}
        self.studies = {}
        self.readings = {}
        self._seq = itertools.count(1)
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = START_CLOCK_RAW

    def next_seq(self):
        return next(self._seq)


db = Store()
