"""In-memory store, logical clock, id/timestamp helpers, and entity mutation.

Storage is process-local dicts keyed by id. Nothing is seeded at startup and
nothing is persisted to disk. The logical clock defaults to
2026-08-01T00:00:00Z and only moves via POST /api/_clock/set_current_utc.
"""
import re
import uuid
from datetime import datetime, date, timezone, timedelta

from flask import g

# ---------------------------------------------------------------------------
# data store
# ---------------------------------------------------------------------------

db = {
    "borrowers": {},
    "facilities": {},
    "participants": {},
    "draws": {},
    "settlements": {},
    "payments": {},
    "runs": {},
    "lines": {},
    "modifications": {},
    "consent_votes": {},
    "default_cases": {},
    "default_votes": {},
    "statements": {},
    "packages": {},
    "transfers": {},
    "buybacks": {},
}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"

_clock = {"raw": CLOCK_DEFAULT_RAW, "dt": None}


def _parse_dt(value):
    """Parse an ISO-8601 datetime (Z or numeric offset, date-only allowed)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    s = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    t = s
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_clock(raw):
    dt = _parse_dt(raw)
    _clock["raw"] = raw
    _clock["dt"] = dt
    return dt


def clock_dt():
    if _clock["dt"] is None:
        _clock["dt"] = _parse_dt(_clock["raw"])
    return _clock["dt"]


def clock_raw():
    return _clock["raw"]


def now_ts():
    """Logical clock as ISO-8601 UTC with exactly three fractional digits."""
    dt = clock_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today():
    return clock_dt().date()


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return date.fromisoformat(value.strip())


def date_of_ts(ts):
    """Calendar date (UTC) of an ISO-8601 timestamp string."""
    return _parse_dt(ts).date()


# ---------------------------------------------------------------------------
# entity mutation bookkeeping
# ---------------------------------------------------------------------------

def new_entity():
    """Common system-managed fields for every resource."""
    ts = now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(ent):
    """One mutation of a resource: version +1 and updated_at refresh.

    Guarded per request so that a multi-field cascade over the same entity
    within one API call counts as a single mutation.
    """
    seen = g.setdefault("_touched", set()) if hasattr(g, "_touched") else None
    if seen is None:
        g._touched = seen = set()
    key = id(ent)
    if key in seen:
        return
    seen.add(key)
    ent["version"] += 1
    ent["updated_at"] = now_ts()


def public(ent):
    """Serialization: strip internal underscore-prefixed fields."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
