"""In-memory data store and logical clock.

The store starts empty on every boot. Nothing is seeded here or anywhere else;
every entity is created through the declared API surface.
"""
import itertools
import re
import uuid
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Stores: one dict per entity kind, keyed by id. Insertion order preserved.
# ---------------------------------------------------------------------------
STORES = {
    "districts": {},
    "contracts": {},
    "routes": {},
    "drivers": {},
    "training_events": {},
    "credentials": {},
    "buses": {},
    "inspections": {},
    "work_orders": {},
    "service_days": {},
    "assignments": {},
    "charter_trips": {},
    "fuel_entries": {},
    "invoices": {},
    "incidents": {},
    "ridership_reports": {},
}

_seq_counter = itertools.count(1)

# Logical clock: exactly 2026-05-01T00:00:00Z at startup; never wall-clock.
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def utcnow():
    """Real wall clock — used only for metadata timestamps (created_at etc.)."""
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def fmt_clock(dt):
    """Logical-clock timestamp serialization (seconds precision when integral)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:06d}Z".format(dt.microsecond)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_now():
    return CLOCK["now"]


def clock_date():
    return CLOCK["now"].date()


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD date string; returns date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def valid_month(value):
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        return False
    try:
        mm = int(value[5:7])
    except ValueError:
        return False
    return 1 <= mm <= 12


def stamp_new(rec):
    """Apply common system fields to a freshly created primary resource."""
    ts = fmt_ts(utcnow())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()


def stamp_append_only(rec):
    """Append-only resources carry only id + created_at."""
    rec["created_at"] = fmt_ts(utcnow())
    rec["_seq"] = next_seq()


def touch(rec):
    """Refresh updated_at and bump version on a mutated primary resource."""
    rec["updated_at"] = fmt_ts(utcnow())
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal bookkeeping keys for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def week_bounds(d):
    """ISO week (Mon-Sun) containing date d; returns (monday, sunday)."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


# --- entity lookup helpers -------------------------------------------------

def find(store, rec_id):
    return STORES[store].get(rec_id)


def all_of(store):
    return STORES[store].values()


def assignments_of_day(service_day_id):
    return [a for a in all_of("assignments") if a["service_day_id"] == service_day_id]


def day_of_assignment(a):
    return find("service_days", a["service_day_id"])


def contract_of_day(day):
    return find("contracts", day["contract_id"])


def route_of_assignment(a):
    return find("routes", a["route_id"])


def contract_district_id(contract):
    return contract["district_id"] if contract else None
