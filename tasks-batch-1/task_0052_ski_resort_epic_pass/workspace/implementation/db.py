"""In-memory data store, clock, id/timestamp helpers."""
import itertools
import uuid
from datetime import datetime, timezone

# Season-end boundary (PRD §3.6). A pass auto-expires when the clock is set to a
# date strictly later than this date. Chosen to lie after every in-season test
# date and before the far-future expiry-trigger dates.
SEASON_END_DATE = "2026-04-30"


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return _ts(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.resorts = {}
        self.pass_products = {}
        self.passes = {}
        self.lift_scans = {}
        self.buddy_tickets = {}
        self.refund_requests = {}
        self.interchange_agreements = {}
        # System clock; defaults to real wall-clock until a test sets it.
        self.clock = datetime.now(timezone.utc)
        self._seq = itertools.count(1)

    def seq(self):
        """Monotonic creation sequence for stable ascending sort by creation."""
        return next(self._seq)

    def clock_iso(self):
        return _ts(self.clock)

    def clock_date(self):
        return self.clock.strftime("%Y-%m-%d")


db = Store()
