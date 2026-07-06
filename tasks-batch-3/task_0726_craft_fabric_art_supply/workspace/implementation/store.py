import uuid
import itertools
from datetime import datetime, timezone


class Clock:
    """Logical clock. Default 2026-03-01T00:00:00Z until explicitly set."""

    DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self):
        self.now = self.DEFAULT

    def set(self, dt):
        self.now = dt


class Store:
    def __init__(self):
        self.clock = Clock()
        self.customers = {}
        self.loyalty_accounts = {}
        self.products = {}
        self.inventory_lots = {}
        self.coupons = {}
        self.orders = {}
        self.order_lines = {}
        self.rooms = {}
        self.workshops = {}
        self.sessions = {}
        self.registrations = {}
        self.framing_orders = {}
        self.project_bundles = {}
        self.special_orders = {}
        self._counter = itertools.count(1)

    def next_seq(self):
        """Monotonic sequence for created_at tiebreak ordering."""
        return next(self._counter)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return fmt_ts(store.clock.now)


def fmt_ts(dt):
    # ISO 8601 UTC with three fractional digits
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(s):
    if not isinstance(s, str):
        raise ValueError("bad timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
