"""In-memory data store, logical clock, and time helpers."""
import threading
from datetime import datetime, timezone, timedelta, date

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock. Startup default is 2026-05-01T00:00:00Z and never falls back
# to wall-clock time until an operator advances it.
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def parse_dt(value):
    """Parse an ISO 8601 datetime string (accepts trailing Z or offset)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return date.fromisoformat(value.strip())


def render_ts(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def now_ts():
    """Server-stamped timestamp drawn from the logical clock."""
    return render_ts(clock_now())


# ---------------------------------------------------------------------------
# Collections (all in-memory; empty at boot).
# ---------------------------------------------------------------------------
DB = {
    "children": {},
    "blood_lead_tests": {},
    "dwellings": {},
    "cases": {},
    "inspectors": {},
    "investigations": {},
    "hazard_findings": {},
    "hazard_control_orders": {},
    "clearance_tests": {},
    "relocation_units": {},
    "relocation_placements": {},
    "contractors": {},
    "grant_funds": {},
    "remediation_projects": {},
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]
