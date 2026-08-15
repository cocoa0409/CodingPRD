"""In-memory data store, logical clock, id/sequence/timestamp helpers.

Storage is plain Python dicts keyed by id. The store starts EMPTY on every
boot — no seeding, no preload. All state is built via API calls.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4). Startup default is exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
CLOCK = {
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": "2026-08-01T00:00:00Z",  # echoed verbatim by the clock endpoint
}

# ---------------------------------------------------------------------------
# Stores — one dict per entity type, keyed by id.
# ---------------------------------------------------------------------------
STORE = {
    "farms": {},
    "houses": {},
    "flocks": {},
    "feed_deliveries": {},
    "production_days": {},
    "grading_runs": {},
    "lots": {},
    "contracts": {},
    "settlements": {},
    "salmonella_tests": {},
    "compliance_audits": {},
    "recalls": {},
    "dispositions": {},
}

_seq_counter = itertools.count(1)   # creation order tie-break
_tick_counter = itertools.count(1)  # mutation order tie-break


def next_seq():
    return next(_seq_counter)


def next_tick():
    return next(_tick_counter)


def now_dt():
    return CLOCK["dt"]


def today():
    """Current logical clock date."""
    return CLOCK["dt"].date()


def now_iso():
    """Logical clock as ISO 8601 UTC with three fractional digits (PRD §2.5)."""
    dt = CLOCK["dt"]
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_record(has_version=True):
    """Base record with system-managed common fields (PRD §2.5)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "_tick": next_tick(),
    }
    if has_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Increment version and refresh updated_at (PRD §2.5: every mutation,
    including system-driven cascades, increments the entity's own version)."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()
    rec["_tick"] = next_tick()
