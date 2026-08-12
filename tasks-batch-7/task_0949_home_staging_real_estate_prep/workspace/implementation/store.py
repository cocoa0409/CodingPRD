"""In-memory data store, id minting, logical clock and money/time helpers.

Nothing is persisted anywhere: no sqlite, no file, no pickle.  The store starts
completely EMPTY on every process boot and nothing is seeded.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from consts import DEFAULT_CLOCK_UTC

COLLECTIONS = [
    "brokerages", "clients", "properties", "listings", "tiers", "vendors", "items",
    "consultations", "scope_items", "projects", "pulls", "pull_lines", "orders",
    "installs", "visits", "leases", "extensions", "pickups", "assessments",
    "shoots", "invoices", "deposits",
]

STORE = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)

# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
_CLOCK = {"now": None}


def _parse_z(text):
    t = text.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now():
    """The logical clock.  Never falls back to host wall-clock time."""
    if _CLOCK["now"] is None:
        _CLOCK["now"] = _parse_z(DEFAULT_CLOCK_UTC)
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt
    return dt


def reset_clock():
    _CLOCK["now"] = _parse_z(DEFAULT_CLOCK_UTC)


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse a caller-supplied ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _parse_z(value)
    except Exception:
        return None


def iso(dt):
    """Canonical rendering: ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def add_days(dt, days):
    """Adding whole days preserves the time-of-day component."""
    if dt is None:
        return None
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def floor_days(delta):
    return int(delta.total_seconds() // 86400)


# --------------------------------------------------------------------------
# money helpers
# --------------------------------------------------------------------------
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value):
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def rate4(value):
    return D(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def num(value):
    """Render a Decimal into JSON as a float."""
    if value is None:
        return None
    return float(D(value))


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def new_row(collection, fields, common=True):
    ts = now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "_seq": next(_seq),
    }
    if common:
        row["updated_at"] = ts
        row["version"] = 1
    row.update(fields)
    STORE[collection][row["id"]] = row
    return row


def touch(row):
    """Bump version + updated_at.  Called at the point of mutation, always
    BEFORE the response body is serialised."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now()
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return STORE[collection].get(row_id)


def all_rows(collection):
    return list(STORE[collection].values())


def sort_default(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def sort_created(rows):
    """Creation-timestamp ordering with the monotonic sequence as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def where(collection, **filters):
    out = []
    for row in STORE[collection].values():
        ok = True
        for key, value in filters.items():
            if value is None:
                continue
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out
