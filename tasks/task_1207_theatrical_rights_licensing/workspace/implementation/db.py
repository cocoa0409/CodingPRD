"""In-memory data store. All state lives here; reset on process restart."""
import uuid
from datetime import datetime, timezone, timedelta

# Entity stores: dict keyed by id, values are dicts (plain records)
titles = {}
restrictions = {}
organizations = {}
applications = {}
agreements = {}
performances = {}
rentals = {}
alteration_requests = {}
recording_grants = {}
payments = {}
fines = {}
availability_snapshots = {}

# Insertion-order counters for created_at ties (tie-break = insertion order)
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _CLOCK_DEFAULT}


def clock_now():
    return _clock["now"]


def set_clock(ts):
    _clock["now"] = ts


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    if dt is None:
        return None
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_ts(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime at seconds granularity.

    Returns None if malformed.
    """
    if not isinstance(s, str):
        return None
    txt = s.strip()
    # Normalize trailing Z
    try:
        if txt.endswith("Z"):
            txt2 = txt[:-1] + "+00:00"
        else:
            txt2 = txt
        dt = datetime.fromisoformat(txt2)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # seconds granularity
    return dt.replace(microsecond=0)
