"""In-memory data store, logical clock, id/timestamp helpers.

Everything lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot; no entity is ever seeded. All state is built by tests via
the API surface.
"""
import uuid
from datetime import datetime, timezone

# --- Logical clock ---------------------------------------------------------
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"


class _Clock:
    def __init__(self):
        self.current = _parse_instant(CLOCK_DEFAULT)

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


def _parse_instant(s):
    """Parse an ISO-8601 instant (accepts trailing Z and date-only) -> aware UTC datetime."""
    if isinstance(s, datetime):
        dt = s
    else:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(txt)
        except ValueError:
            # date only
            dt = datetime.fromisoformat(txt + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


clock = _Clock()

# --- Collections -----------------------------------------------------------
members = {}
products = {}
rental_units = {}
reservations = {}
trips = {}
guides = {}
trip_bookings = {}
trade_ins = {}
repair_orders = {}
passes = {}
special_orders = {}
purchases = {}
declarations = {}
loyalty_ledger = {}

_ALL = [
    members, products, rental_units, reservations, trips, guides, trip_bookings,
    trade_ins, repair_orders, passes, special_orders, purchases, declarations,
    loyalty_ledger,
]

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO-8601 UTC with three fractional digits and trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(clock.now())


def stamp_new(entity, common=True):
    entity["id"] = new_id()
    entity["_seq"] = next_seq()
    entity["_created_dt"] = clock.now()
    if common:
        ts = now_ts()
        entity["created_at"] = ts
        entity["updated_at"] = ts
        entity["version"] = 1
    else:
        entity["created_at"] = now_ts()
    return entity


def touch(entity):
    """Bump version + refresh updated_at on a stored-field mutation."""
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 1) + 1
    return entity
