"""In-memory data store, logical clock, id/timestamp/decimal helpers. No disk persistence.

The store starts empty on every boot; nothing is seeded at startup. The logical
clock starts at exactly 2026-08-01T00:00:00Z and only moves via the
POST /_clock/set_current_utc test-driving endpoint.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# The district logical clock (module-level; rebound only by routes/clock.py).
LOGICAL_CLOCK = _CLOCK_START

_seq_counter = itertools.count(1)
_wall_last = [None]

CENT = Decimal("0.01")


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.water_accounts = {}
        self.seasons = {}
        self.allocations = {}
        self.turnout_orders = {}
        self.rider_work_orders = {}
        self.invoices = {}
        self.canal_reaches = {}
        self.maintenance_windows = {}
        self.transfer_requests = {}
        self.drought_declarations = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def D(value):
    """Exact Decimal from a JSON number or existing Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value):
    """Round half-up to 2 decimal places (the district's pinned rounding)."""
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


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


def iso_out(dt):
    """Format a datetime as ISO 8601 UTC (second precision, Z suffix)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(raw, field):
    """Parse an ISO 8601 datetime input; interval comparisons are to the second."""
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field %s must be an ISO 8601 datetime string" % field)
    s = raw.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field %s is not a valid ISO 8601 instant" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


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
