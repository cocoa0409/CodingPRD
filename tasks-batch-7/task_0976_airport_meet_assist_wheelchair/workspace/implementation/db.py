"""In-memory data store + logical clock. Empty on every boot."""
import uuid
from datetime import datetime, timezone
from threading import RLock

LOCK = RLock()

# ---------------------------------------------------------------------------
# Logical clock — starts exactly at 2026-05-01T00:00:00Z per PRD §2.4.
# NEVER falls back to wall-clock for business logic.
# ---------------------------------------------------------------------------
_CLOCK_INIT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_now_utc: datetime = _CLOCK_INIT


def now() -> datetime:
    return _now_utc


def set_now(dt: datetime) -> None:
    global _now_utc
    _now_utc = dt


def fmt_dt(dt: datetime):
    """Format datetime as ISO 8601 UTC with three fractional digits. None -> None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime. Accepts trailing Z or offset. Returns aware datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now_logical() -> str:
    return fmt_dt(_now_utc)


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id. Empty at boot.
# ---------------------------------------------------------------------------
airports = {}
terminals = {}
segments = {}
passengers = {}
agents = {}
wheelchairs = {}
assist_requests = {}
legs = {}
assignments = {}
incidents = {}
invoices = {}
tracking_events = {}


def reset():
    """Test-only helper; clears every store and resets the clock."""
    for d in (airports, terminals, segments, passengers, agents, wheelchairs,
              assist_requests, legs, assignments, incidents, invoices, tracking_events):
        d.clear()
    set_now(_CLOCK_INIT)


def common_fields() -> dict:
    """Fresh common fields for a new entity."""
    ts = iso_now_logical()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version (in place)."""
    entity["updated_at"] = iso_now_logical()
    entity["version"] = entity.get("version", 1) + 1
