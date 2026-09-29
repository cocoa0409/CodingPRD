"""In-memory data store, logical clock and audit-column helpers.

Storage is process-local Python dicts keyed by entity id.  Nothing is ever
persisted and nothing is ever seeded: the store is empty on every boot.
"""

import datetime
import random
import re
import string
import threading
import uuid

# ---------------------------------------------------------------------------
# Collections.  Every collection maps id -> dict.
# ---------------------------------------------------------------------------
lessees = {}
leases = {}
mortgages = {}
revaluations = {}
appraisals = {}
arbitrations = {}
statements = {}
alterations = {}
transfers = {}
notices = {}
loss_events = {}
assessments = {}
certificates = {}

COLLECTIONS = {
    "lessee": lessees,
    "lease": leases,
    "mortgage": mortgages,
    "revaluation": revaluations,
    "appraisal": appraisals,
    "arbitration": arbitrations,
    "statement": statements,
    "alteration": alterations,
    "transfer": transfers,
    "notice": notices,
    "loss_event": loss_events,
    "assessment": assessments,
    "certificate": certificates,
}

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock.  The server never consults wall-clock time for business
# comparisons; PRD 2.5 fixes the boot default at 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_clock = {"now": DEFAULT_CLOCK}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def now():
    """Current logical instant (timezone-aware, UTC)."""
    return _clock["now"]


def set_now(value):
    _clock["now"] = value
    return _clock["now"]


# ---------------------------------------------------------------------------
# Formatting helpers.
# ---------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(text):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    m = _DT_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        base = datetime.datetime(
            year, month, day, hour, minute, second, micro,
            tzinfo=datetime.timezone.utc,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = datetime.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * delta
    return base


def add_days(dt, days):
    """Whole-day arithmetic: adding 24-hour days (PRD 2.5)."""
    return dt + datetime.timedelta(days=days)


def add_years(dt, years):
    """Calendar-year addition with a 29-Feb -> 28-Feb fallback."""
    year = dt.year + int(years)
    month, day = dt.month, dt.day
    try:
        return dt.replace(year=year)
    except ValueError:
        return dt.replace(year=year, month=month, day=28)


def whole_days_between(start, end):
    """Number of whole 24-hour days from start to end (may be negative)."""
    return (end - start).days


# ---------------------------------------------------------------------------
# Identifiers.
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ---------------------------------------------------------------------------
# Audit columns (PRD 2.4).
# ---------------------------------------------------------------------------
def stamp(record, versioned=True):
    """Attach the system-managed audit columns to a brand new record."""
    moment = now()
    record["id"] = new_id()
    record["created_at"] = moment
    if versioned:
        record["updated_at"] = moment
        record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version for a mutated record."""
    if record is None:
        return None
    record["updated_at"] = now()
    record["version"] = record.get("version", 1) + 1
    return record


def sort_rows(rows, key=None):
    """Default ordering: created_at ascending, insertion sequence as tiebreak."""
    if key is None:
        return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    return sorted(rows, key=key)


def by_lease(collection, lease_id):
    return sort_rows([r for r in collection.values() if r.get("lease_id") == lease_id])


def reset():
    """Clear every collection and restore the logical clock (test convenience)."""
    for coll in COLLECTIONS.values():
        coll.clear()
    _clock["now"] = DEFAULT_CLOCK
    _seq["n"] = 0
