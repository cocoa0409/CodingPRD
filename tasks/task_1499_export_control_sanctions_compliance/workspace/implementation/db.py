"""In-memory data store + logical clock. The store starts EMPTY on every boot;
no seeding of any kind. All server time derives from the logical clock, which
starts at exactly 2026-08-01T00:00:00Z and never falls back to wall-clock."""

import uuid
from datetime import datetime, timezone

# Entity collections (dicts keyed by id, insertion-ordered)
PRODUCTS = {}
CLASSIFICATIONS = {}
PARTIES = {}
LIST_ENTRIES = {}
SCREENING_RESULTS = {}
ORDERS = {}
LICENSES = {}
SHIPMENTS = {}
TCPS = {}
GRANTS = {}
VIOLATIONS = {}
AUDIT_RECORDS = {}

_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}
_seq = {"n": 0}
_counters = {"license": 0, "vsd": 0}


def now_dt():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def today():
    """Current date (YYYY-MM-DD) of the logical clock."""
    return _clock["now"].date().isoformat()


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(_clock["now"])


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def next_license_number():
    _counters["license"] += 1
    return "LIC-%06d" % _counters["license"]


def next_vsd_reference():
    _counters["vsd"] += 1
    return "VSD-%06d" % _counters["vsd"]


def stamp_new(e):
    """Populate common system fields on a freshly created primary resource."""
    e["id"] = new_id()
    ts = now_iso()
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_created_dt"] = now_dt()
    e["_seq"] = next_seq()
    return e


def touch(e):
    """Mutation stamp: refreshed updated_at and version += 1."""
    e["updated_at"] = now_iso()
    e["version"] += 1


def pub(e):
    """Public serialization: strip internal (underscore-prefixed) keys."""
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_key(e):
    return (e["_created_dt"], e["_seq"])
