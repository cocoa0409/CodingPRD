"""In-memory data store and the logical clock (PRD section 2.4).

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: every row is created by an API call.
"""

import re
import uuid
from datetime import datetime, date, timedelta

# ---------------------------------------------------------------- collections

COLLECTIONS = (
    "parties",
    "laboratories",
    "sites",
    "assessment_phases",
    "contaminant_findings",
    "cleanup_goals",
    "liability_protections",
    "continuing_obligations",
    "vcp_enrollments",
    "remedial_action_plans",
    "cost_cap_policies",
    "site_controls",
    "funding_awards",
    "nfa_letters",
    "monitoring_events",
)

_store = {name: {} for name in COLLECTIONS}
_seq = {"n": 0}

# The logical clock starts at exactly 2026-08-01T00:00:00Z on every boot and
# never falls back to wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0)
_clock = {"now": CLOCK_EPOCH}


def store(name):
    return _store[name]


def reset():
    for name in COLLECTIONS:
        _store[name] = {}
    _seq["n"] = 0
    _clock["now"] = CLOCK_EPOCH


# -------------------------------------------------------------------- clock


def now():
    """Current logical time as a naive UTC datetime."""
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def today():
    """Current logical date."""
    return _clock["now"].date()


def iso_ts(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_ts():
    return iso_ts(now())


def today_str():
    return today().isoformat()


# ------------------------------------------------------------- id / parsing


def new_id():
    return str(uuid.uuid4())


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a strict ISO 8601 calendar date, or return None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    """Parse an ISO 8601 datetime (Z, offset, or naive) into naive UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=None)
        if offset:
            dt = dt - offset
    return dt


def days_between(later, earlier):
    """later - earlier in whole days (both date objects)."""
    return (later - earlier).days


def add_days(d, n):
    return d + timedelta(days=n)


# ------------------------------------------------------------- row lifecycle


def insert(collection, row):
    _seq["n"] += 1
    row["_seq"] = _seq["n"]
    ts = now_ts()
    row.setdefault("id", new_id())
    row["created_at"] = ts
    if collection != "contaminant_findings":
        row["updated_at"] = ts
        row["version"] = 1
    _store[collection][row["id"]] = row
    return row


def touch(row):
    """Mark a row mutated: refresh updated_at and bump version by 1."""
    row["updated_at"] = now_ts()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return _store[collection].get(row_id)


def all_rows(collection):
    return list(_store[collection].values())


def ordered(rows):
    """Default ordering: created_at ascending, insertion sequence as tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
