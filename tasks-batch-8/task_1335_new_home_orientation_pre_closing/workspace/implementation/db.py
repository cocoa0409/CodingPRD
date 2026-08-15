"""In-memory data store, logical clock, and record helpers (PRD §2.4/§2.5).

The store starts completely empty on every boot — no seeding. The logical
clock starts at exactly 2026-08-01T00:00:00Z and is the single source of
"now" for every temporal rule and every system-stamped timestamp; the server
never falls back to wall-clock time for domain timestamps.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# Serializes all request handling (per-test-server isolation + race tests).
LOCK = threading.RLock()

# Logical clock — startup default per PRD §2.4.
CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

communities = {}
homebuyers = {}
reps = {}
homes = {}
appointments = {}
attendees = {}
deficiency_items = {}
visits = {}
escrows = {}
signatures = {}
surveys = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def now():
    return CLOCK


def set_clock(dt):
    global CLOCK
    CLOCK = dt


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def fmt_dt(d):
    """ISO 8601 UTC. Whole-second instants render without a fractional part
    (matching client-supplied instants); sub-second instants render with
    three fractional digits."""
    d = d.astimezone(timezone.utc)
    if d.microsecond:
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(rec):
    """Initialize common system fields on a freshly created record."""
    ts = fmt_dt(CLOCK)
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next(_seq)
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and increment version (PRD §2.5/§2.9)."""
    rec["updated_at"] = fmt_dt(CLOCK)
    rec["version"] += 1
    return rec


def public(rec):
    """Strip internal bookkeeping keys for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_key(rec):
    """List ordering: created_at ascending, stable by insertion order (PRD §2.3)."""
    return (parse_dt(rec["created_at"]) or CLOCK, rec.get("_seq", 0))
