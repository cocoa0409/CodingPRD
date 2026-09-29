"""In-memory data store, logical clock, and shared numeric helpers.

Storage is process-local Python dicts only. The store starts completely empty on
every boot: no seeding, no preloaded rows, no persistence.
"""

import datetime
import itertools
import random
import string
import threading
import uuid
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from errors import ApiError

LOCK = threading.RLock()

COLLECTIONS = (
    "clients",
    "cycles",
    "facilities",
    "recognitions",
    "representatives",
    "accreditations",
    "screenings",
    "matters",
    "assignments",
    "evidence",
    "declarations",
    "sessions",
    "events",
    "decisions",
    "reports",
)

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

db = {name: {} for name in COLLECTIONS}
_seq = itertools.count(1)
_state = {"clock": DEFAULT_CLOCK}


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

def parse_dt(text):
    """Parse an ISO 8601 UTC timestamp. Returns a naive UTC datetime."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        value = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value


def parse_date(text):
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if len(raw) != 10:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return None


def iso(value):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def clock_iso():
    return _state["clock"]


def clock_dt():
    return parse_dt(_state["clock"])


def clock_date():
    return clock_dt().date()


def set_clock(text):
    _state["clock"] = text


def reset():
    for name in COLLECTIONS:
        db[name] = {}
    _state["clock"] = DEFAULT_CLOCK


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

def new_row(fields=None):
    stamp = clock_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next(_seq),
    }
    if fields:
        row.update(fields)
    return row


def touch(row):
    row["version"] = int(row["version"]) + 1
    row["updated_at"] = clock_iso()
    return row


def insert(collection, row):
    db[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db[collection].get(row_id)


def rows(collection):
    return sorted(db[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def order_key(row):
    return (row["created_at"], row["_seq"])


# --------------------------------------------------------------------------
# request metadata
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def request_timestamp():
    return iso(datetime.datetime.utcnow())


# --------------------------------------------------------------------------
# decimal helpers
# --------------------------------------------------------------------------

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "Expected a number.")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise ApiError("ERR_VALIDATION", "Expected a number.")
    raise ApiError("ERR_VALIDATION", "Expected a number.")


def rhu(value, places=2):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _int_param(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)


def pagination(args):
    limit = _int_param(args, "limit", LIMIT_DEFAULT)
    offset = _int_param(args, "offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must not be negative.")
    return limit, offset


def paginate(items, args):
    limit, offset = pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
