"""In-memory data store. All state lives in process-local dicts keyed by id.

No persistence of any kind: every fresh process boot starts with empty tables.
The store MUST NOT be seeded here -- tests construct all entities via the API.
"""
import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity tables: id -> dict
# ---------------------------------------------------------------------------
periods = {}
participants = {}
beneficiaries = {}
elections = {}
alignment_runs = {}
attribution_records = {}
claims = {}
benchmarks = {}
quality_scores = {}
settlements = {}
distribution_lines = {}
high_cost_reviews = {}
appeals = {}
adjustments = {}

# ---------------------------------------------------------------------------
# Monotonic wall-clock timestamps (ISO 8601 UTC, 3 fractional digits)
# Guarantees created_at values are strictly increasing so created_at ASC
# sorts and earliest-created tie-breaks are deterministic.
# ---------------------------------------------------------------------------
_ts_lock = threading.Lock()
_last_tick_ms = 0


def next_timestamp():
    global _last_tick_ms
    with _ts_lock:
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        if now <= _last_tick_ms:
            now = _last_tick_ms + 1
        _last_tick_ms = now
        tick = now
    dt = datetime.fromtimestamp(tick / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def stamp_new(entity):
    """Populate common system fields on a freshly created entity."""
    ts = next_timestamp()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def bump(entity):
    """Version +1 and refreshed updated_at on every mutation of a resource."""
    entity["version"] += 1
    entity["updated_at"] = next_timestamp()
    return entity


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.8). Defaults to exactly 2026-08-01T00:00:00Z
# and never falls back to wall-clock time.
# ---------------------------------------------------------------------------
_logical_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return _logical_now


def set_logical_now(dt):
    global _logical_now
    _logical_now = dt


def render_logical(dt):
    """Render a logical-clock datetime as ISO 8601 UTC (Z suffix)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
