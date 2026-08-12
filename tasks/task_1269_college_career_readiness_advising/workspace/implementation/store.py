"""In-memory data store + logical clock. The store starts empty on every boot;
no entity is ever seeded at startup."""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5). Defaults to exactly 2026-05-01T00:00:00Z and never
# falls back to wall-clock time for entity timestamps or deadline comparisons.
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def fmt_ts(dt):
    """ISO 8601 UTC with exactly 3 fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Stores: dicts keyed by id. Insertion sequence for deterministic tie-breaks.
# ---------------------------------------------------------------------------

_seq_counter = itertools.count(1)

stores = {
    "students": {},
    "advisors": {},
    "teachers": {},
    "pathways": {},
    "plans": {},
    "enrollments": {},
    "applications": {},
    "milestones": {},
    "rec_requests": {},
    "certifications": {},
    "sites": {},
    "placements": {},
    "audits": {},
    "outcomes": {},
    "ops_runs": {},
}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def mint(store_name):
    """Create the common shell of a new record: id/created_at/updated_at/version."""
    ts = now()
    return {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(rec):
    """Refresh updated_at without touching version (non-versioned mutation)."""
    rec["updated_at"] = now()


def bump(rec):
    """Versioned mutation: version += 1 and updated_at refresh."""
    rec["version"] += 1
    rec["updated_at"] = now()
