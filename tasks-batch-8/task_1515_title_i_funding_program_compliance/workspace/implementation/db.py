"""In-memory data store. The store starts EMPTY on every boot — no seeding.

Also owns: monotonic server timestamps (created_at/updated_at) and the logical
clock used by every date-sensitive rule (session dates, visit windows, the
finding-escalation sweep). The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import time
import uuid
from datetime import datetime, timezone

# --- entity stores: dict keyed by id ---------------------------------------
grants = {}
schools = {}
private_schools = {}
snapshots = {}
allocations = {}
set_asides = {}
sns_docs = {}
consultations = {}
expenditures = {}
amendments = {}
visits = {}
findings = {}

# --- monotonic timestamps ---------------------------------------------------
_last_ms = 0


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits, strictly
    increasing across the process so created_at ordering is stable."""
    global _last_ms
    ms = time.time_ns() // 1_000_000
    if ms <= _last_ms:
        ms = _last_ms + 1
    _last_ms = ms
    sec, milli = divmod(ms, 1000)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % milli


def touch(resource):
    """Record a modification: refresh updated_at and bump version."""
    resource["updated_at"] = now_ts()
    resource["version"] = resource.get("version", 1) + 1


def init_common(resource):
    ts = now_ts()
    resource["id"] = new_id()
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1
    return resource


# --- logical clock ----------------------------------------------------------
_DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
_clock = {
    "instant": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": _DEFAULT_CLOCK_RAW,
}


def clock_instant():
    return _clock["instant"]


def clock_date():
    return _clock["instant"].date()


def clock_raw():
    return _clock["raw"]


def set_clock(instant, raw):
    _clock["instant"] = instant
    _clock["raw"] = raw
