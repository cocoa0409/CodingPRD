"""In-memory data store + logical clock (PRD sections 2.4, 2.9).

The store starts empty on every boot. The logical clock starts at exactly
2026-08-01T00:00:00Z and is only moved via POST /_clock/set_current_utc.
The server never consults wall-clock time.
"""
import itertools
import uuid
from datetime import datetime, timezone

START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {
    "clock": START_CLOCK,
    "seq": itertools.count(1),
}

# Entity stores: id -> dict
stations = {}
pumps = {}
runtime_readings = {}
alarm_tickets = {}
operators = {}
pump_rebuilds = {}
wet_well_cleanings = {}
generator_tests = {}
sso_events = {}
confined_space_permits = {}
capital_plans = {}
capital_projects = {}
spare_pumps = {}


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    return next(_state["seq"])


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (2026-08-01T00:00:00.000Z)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(now())


def stamp(entity):
    """Initialize common fields on a freshly created entity (id set by caller)."""
    ts = now()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()


def touch(entity):
    """Record one accepted mutation: version +1, updated_at refreshed."""
    entity["updated_at"] = now()
    entity["version"] += 1
