"""In-memory data store, logical clock, and id/timestamp helpers.

Every collection starts EMPTY on boot. No entity data is seeded. All state is
wiped by a fresh process (the harness restarts start.sh before every test).
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Collections: id -> record dict.  Peer collections (flat topology, PRD §1).
# ---------------------------------------------------------------------------
customers = {}
fitters = {}
rooms = {}
appointments = {}
products = {}
skus = {}
orders = {}
order_lines = {}
exchanges = {}
claims = {}
reminders = {}
loyalty_events = {}

# ---------------------------------------------------------------------------
# Logical clock: authoritative "now" for temporal rules. Startup default is
# exactly 2026-07-01T00:00:00Z and never falls back to wall-clock time.
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_CLOCK}

_seq = {"n": 0}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real-time ISO-8601 UTC stamp with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso(dt):
    """Serialize a datetime to ISO-8601 UTC (millisecond precision, Z)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 instant; returns a tz-aware UTC datetime or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_record(extra=None):
    """Create a record carrying the four common system fields (PRD §2.4)."""
    rid = new_id()
    ts = now_iso()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Refresh updated_at and increment version on any mutation (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
