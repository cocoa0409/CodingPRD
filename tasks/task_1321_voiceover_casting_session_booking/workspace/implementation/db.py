"""In-memory data store. The store starts empty on every boot; no entity seeding.

Only the ClockState singleton is initialized at startup, as mandated by PRD §2.5
("At startup the clock reads exactly 2026-08-01T00:00:00Z").
"""
import uuid
from datetime import datetime, timezone

DB = {
    "talents": {},
    "clients": {},
    "projects": {},
    "self_auditions": {},
    "studios": {},
    "sessions": {},
    "usage_terms": {},
    "invoices": {},
    "conflict_exclusions": {},
    "deliveries": {},
}

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Logical clock singleton (ClockState resource).
CLOCK = {"id": None, "created_at": None, "current_utc": None}

# Monotonic insertion sequence for stable created_at ordering.
_seq = [0]


def init_store():
    CLOCK["id"] = new_id()
    CLOCK["created_at"] = datetime.now(timezone.utc)
    CLOCK["current_utc"] = parse_iso(DEFAULT_CLOCK)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now_wall():
    return datetime.now(timezone.utc)


def wall_iso(dt):
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_iso(dt):
    """Logical-clock timestamp, ISO 8601 UTC at second precision."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def clock_now():
    return CLOCK["current_utc"]
