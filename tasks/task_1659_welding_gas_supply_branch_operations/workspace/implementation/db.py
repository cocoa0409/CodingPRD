"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

The store starts empty on every boot — nothing is seeded at startup; every
entity is constructed by clients through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone, date

# Logical clock default: exactly 2026-08-01T00:00:00Z at server startup.
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]

# Pinned domain constants (scaffold §1.5 / calculations constants).
DELIVERY_FEE_CENTS = 2500
FREE_DELIVERY_THRESHOLD_CENTS = 20000
HAZMAT_FEE_CENTS = 1500
DEMURRAGE_MONTHLY_CENTS = 1200
DEFAULT_CYLINDER_GRACE_DAYS = 5
MACHINE_TURNAROUND_BUFFER_DAYS = 1
CERT_VALIDITY_DAYS = 1095
PERIOD_DAYS = {"DAILY": 1, "WEEKLY": 7, "MONTHLY": 30, "DEMURRAGE": 30}
GAS_GRADES = ["OXYGEN", "ACETYLENE", "ARGON", "AR_CO2_7525", "NITROGEN"]
ROLES = ["CounterRep", "BranchManager", "RouteDriver", "Trainer", "ServiceTech"]


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.customers = {}
        self.price_books = {}
        self.products = {}
        self.cylinder_assets = {}
        self.machines = {}
        self.rental_agreements = {}
        self.delivery_routes = {}
        self.orders = {}
        self.invoices = {}
        self.training_classes = {}
        self.enrollments = {}
        self.repair_tickets = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def _fmt_wall(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    """Strictly increasing wall-clock ISO 8601 UTC timestamp, 3 fractional digits."""
    now = datetime.now(timezone.utc)
    last = _wall_last[0]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _wall_last[0] = now
    return _fmt_wall(now)


def iso_logical(dt):
    """Format a logical-clock datetime as ISO 8601 UTC."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_now():
    return LOGICAL_CLOCK


def clock_date():
    return LOGICAL_CLOCK.date()


def set_clock(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity."""
    entity["created_at"] = wall_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on bad input. Naive inputs are treated as UTC.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date string. Raises ValueError otherwise."""
    if not isinstance(value, str):
        raise ValueError("not a date string")
    dt = datetime.strptime(value, "%Y-%m-%d")
    return dt.date()


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)
