"""In-memory data store. Every byte of state lives here and is wiped on each
fresh process boot — no seeding, no persistence, no disk."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.customers = {}
        self.segments = {}
        self.segment_memberships = {}
        self.promotions = {}
        self.coupons = {}
        self.blackout_windows = {}
        self.exclusion_rules = {}
        self.carts = {}
        self.cart_lines = {}
        self.cart_applications = {}
        self.coupon_redemptions = {}
        # monotonic sequence to order rows that share a created_at millisecond
        self._seq = 0
        # logical clock (PRD §2.8) — defaults to real wall clock at boot
        self.clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def now_iso_ms(dt=None):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
