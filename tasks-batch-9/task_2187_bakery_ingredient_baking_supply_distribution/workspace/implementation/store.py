"""In-memory data store, logical clock and numeric/temporal helpers.

Storage is process-local only: every re-invocation of start.sh wipes all state.
No entity is ever seeded here.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

EPOCH_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "customers",
    "products",
    "quotes",
    "contracts",
    "contract_lines",
    "zones",
    "lots",
    "silos",
    "orders",
    "order_lines",
    "subs",
    "routes",
    "stops",
    "engagements",
)

db = {name: {} for name in COLLECTIONS}
_clock = {"now": EPOCH_DEFAULT}
_seq = {"n": 0}


def reset():
    for name in COLLECTIONS:
        db[name] = {}
    _clock["now"] = EPOCH_DEFAULT
    _seq["n"] = 0


# ---------------------------------------------------------------- clock ----
def now():
    """Current logical clock instant (never real wall-clock time)."""
    return _clock["now"]


def set_now(instant):
    _clock["now"] = instant


def clock_date():
    """Logical clock truncated to the UTC day."""
    return day_of(_clock["now"])


def day_of(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def days_between(a, b):
    """Whole UTC days from a to b, fractional remainder discarded."""
    return (day_of(b) - day_of(a)).days


# ------------------------------------------------------------ identity ----
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def peek_seq():
    """The sequence number the next insertion would take (no side effect)."""
    return _seq["n"] + 1


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_sec(dt):
    """Render a business date or window instant to whole-second ISO 8601 UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ------------------------------------------------------------- records ----
def base_record(with_version=True):
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def bump(rec):
    """Increment the resource's version and refresh updated_at."""
    if "version" in rec:
        rec["version"] = int(rec["version"]) + 1
        rec["updated_at"] = now()
    return rec


def insert(collection, rec):
    db[collection][rec["id"]] = rec
    return rec


def get(collection, rid):
    if rid is None:
        return None
    return db[collection].get(rid)


def all_of(collection):
    return list(db[collection].values())


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ------------------------------------------------------------ numerics ----
LB = Decimal("0.01")
PCT = Decimal("0.01")


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not numeric")
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def lb(value):
    """Pounds carried at two decimal places."""
    return round_half_up(value, 2)


def cents(value):
    return int(round_half_up(value, 0))


def out_lb(value):
    if value is None:
        return None
    return float(lb(value))


def out_num(value, places=2):
    if value is None:
        return None
    return float(round_half_up(value, places))


def out_qty(value, places=2):
    """Serialise a pounds/hours quantity: int when integral, else float."""
    if value is None:
        return None
    q = round_half_up(value, places)
    if q == q.to_integral_value():
        return int(q)
    return float(q)
