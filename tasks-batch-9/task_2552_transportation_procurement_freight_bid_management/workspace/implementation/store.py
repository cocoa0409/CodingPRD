"""In-memory store and the logical procurement clock (PRD §2.5, §2.6).

The store is a set of plain dicts keyed by id.  It starts completely empty on every
boot: nothing is seeded, preloaded or hardcoded.  Every row is created by a declared
endpoint.
"""
import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError, bad_request

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# --- collections -------------------------------------------------------------
carriers = {}
reviews = {}
scorecards = {}
events = {}
lanes = {}
rounds = {}
invitations = {}
lane_bids = {}
runs = {}
allocations = {}
contracts = {}
rate_records = {}
tender_events = {}
mini_bids = {}

_clock = {"now": CLOCK_DEFAULT}
_seq = itertools.count(1)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


# --- clock -------------------------------------------------------------------
def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt.astimezone(UTC)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt(now())


def parse_dt(value):
    """Parse an ISO 8601 instant.  Naive values are read as UTC."""
    if not isinstance(value, str):
        raise bad_request("Expected an ISO 8601 timestamp string.")
    m = _ISO_RE.match(value.strip())
    if not m:
        raise bad_request("Malformed ISO 8601 timestamp: %s" % value)
    year, month, day, hh, mm, ss, frac, tz = m.groups()
    micro = int((frac or "0").ljust(6, "0")) if frac else 0
    try:
        dt = datetime(int(year), int(month), int(day), int(hh or 0), int(mm or 0),
                      int(ss or 0), micro, tzinfo=UTC)
    except ValueError:
        raise bad_request("Malformed ISO 8601 timestamp: %s" % value)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        dt = dt - sign * timedelta(hours=int(body[:2]), minutes=int(body[2:]))
    return dt


def dt_of(value):
    """Parse a stored timestamp value (already validated on the way in)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return parse_dt(value)


def days(n):
    return timedelta(days=n)


# --- rows --------------------------------------------------------------------
_touched = {"ids": set()}


def begin_request():
    _touched["ids"] = set()


def new_row(**fields):
    """Mint a row carrying the four common system fields of PRD §2.6."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = next(_seq)
    _touched["ids"].add(row["id"])
    return row


def new_event_row(**fields):
    """A TenderEvent carries only id and created_at (PRD §2.6) — no updated_at, no
    version, and nothing ever mutates it."""
    row = {"id": str(uuid.uuid4()), "created_at": now_iso()}
    row.update(fields)
    row["_seq"] = next(_seq)
    return row


def touch(row):
    """Record a real mutation: refresh updated_at and increment version.  Rollups
    recomputed by a cascade count as mutations (PRD §2.12).  A row already mutated in
    this request is not bumped twice."""
    if row is None:
        return
    if row["id"] in _touched["ids"]:
        row["updated_at"] = now_iso()
        return
    _touched["ids"].add(row["id"])
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def order_key(row):
    """created_at ascending, with the insertion sequence as a stable tie-break."""
    return (row["created_at"], row["_seq"])


def sorted_rows(items):
    return sorted(items, key=order_key)


def require(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row
