"""In-memory data store + logical clock.

ALL state lives in module-level dicts keyed by UUID id. The store starts EMPTY
on every boot — nothing is seeded, preloaded, or hardcoded (per the build
contract). start.sh re-invocation wipes every byte because the process restarts.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity tables (id -> dict). Empty at boot.
# ---------------------------------------------------------------------------
courses = {}
instructors = {}
cohorts = {}
students = {}
enrollments = {}
practice_attempts = {}
installment_plans = {}
guarantee_claims = {}

# Monotonic counter so created_at ordering ties break by insertion order.
_seq = 0

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.8). Startup default 2026-04-01T00:00:00Z; never falls
# back to wall-clock time. A Registrar may advance it via /_clock/set_current_utc.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_clock = CLOCK_DEFAULT


def now_clock():
    """Current logical-clock instant (timezone-aware UTC datetime)."""
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def new_id():
    return str(uuid.uuid4())


def _iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _seq
    _seq += 1
    return _seq


def stamp_create(record, with_version=True):
    """Attach common system fields at creation time.

    created_at uses the logical clock (so created_at ordering is deterministic
    under test control). PracticeAttempt sets with_version=False — it carries
    only id and created_at (PRD §2.4).
    """
    now = now_clock()
    record["created_at"] = _iso(now)
    record["_seq"] = next_seq()
    if with_version:
        record["updated_at"] = _iso(now)
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.4).

    Recomputed/derived field changes are mutations too (PRD §2.4), so callers
    invoke this whenever a resource's stored state changes.
    """
    record["updated_at"] = _iso(now_clock())
    record["version"] = record.get("version", 0) + 1
