"""In-memory data store and helpers. Store starts empty on every boot."""
import uuid
from datetime import datetime, timezone

# Logical clock. Startup default per PRD §3.10.
_DEFAULT_CLOCK = "2026-03-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def fmt_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO8601 timestamp into an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.products = {}
        self.allocations = {}
        self.inventory_items = {}
        self.trade_ins = {}
        self.trade_in_lines = {}
        self.orders = {}
        self.order_lines = {}
        self.pre_orders = {}
        self.consignments = {}
        self.display_slots = {}
        self.grading_disputes = {}
        self.special_orders = {}
        self._clock = parse_iso(_DEFAULT_CLOCK)

    @property
    def now(self):
        """Current logical clock instant (aware datetime, UTC)."""
        return self._clock

    def set_clock(self, iso):
        self._clock = parse_iso(iso)


db = Store()


def now_iso():
    """Server timestamp: ISO8601 UTC with three fractional digits.

    Uses the logical clock so created_at/updated_at are deterministic in tests.
    """
    return fmt_iso(db.now)
