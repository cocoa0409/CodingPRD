"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded; every record is created by a client through a declared endpoint.
"""

import datetime
import random
import string
import threading
import uuid

# ---------------------------------------------------------------------------
# Collections (all keyed by record id)
# ---------------------------------------------------------------------------
display_models = {}
burn_in_chambers = {}
commissioning_crews = {}
display_projects = {}
drawing_revisions = {}
cabinets = {}
modules = {}
burn_in_runs = {}
commissioning_visits = {}
service_contracts = {}
service_cases = {}

LOCK = threading.RLock()

DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"
_clock = {"now": DEFAULT_CLOCK}
_seq = {"n": 0}

ALNUM = string.ascii_letters + string.digits


def reset():
    for coll in (display_models, burn_in_chambers, commissioning_crews,
                 display_projects, drawing_revisions, cabinets, modules,
                 burn_in_runs, commissioning_visits, service_contracts,
                 service_cases):
        coll.clear()
    _clock["now"] = DEFAULT_CLOCK
    _seq["n"] = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def wall_now():
    """Real wall-clock instant, ISO 8601 UTC with exactly 3 fractional digits."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def logical_now():
    return _clock["now"]


def set_logical_now(value):
    _clock["now"] = value
    return _clock["now"]


# ---------------------------------------------------------------------------
# Datetime parsing / formatting (millisecond resolution)
# ---------------------------------------------------------------------------
def parse_dt(text):
    """Parse an ISO-8601 UTC datetime string, returning an aware datetime.

    Returns None when the value is not a parseable instant.
    """
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def canon_dt(text):
    """Canonicalise a client-supplied datetime to millisecond precision."""
    dt = parse_dt(text)
    if dt is None:
        return None
    return fmt_dt(dt)


def ms(text):
    """Millisecond epoch value of a stored datetime string (for comparisons)."""
    dt = parse_dt(text)
    if dt is None:
        return None
    return int(dt.timestamp() * 1000)


def add_hours(text, hours):
    dt = parse_dt(text)
    return fmt_dt(dt + datetime.timedelta(hours=hours))


def add_minutes(text, minutes):
    dt = parse_dt(text)
    return fmt_dt(dt + datetime.timedelta(minutes=minutes))


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(extra=None):
    stamp = wall_now()
    rec = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Bump version + updated_at on a record a write or cascade touched."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = wall_now()
    return rec


def ordered(coll):
    """All records of a collection ordered by created_at ascending (seq tiebreak)."""
    return sorted(coll.values(), key=lambda r: (r["created_at"], r["_seq"]))
