"""In-memory data store.

Storage is process-local only: plain dicts keyed by resource id. The store
starts EMPTY on every boot -- no seeding, no preload, no disk persistence.
The logical clock starts at exactly 2026-05-01T00:00:00Z and never falls
back to wall-clock time (PRD section 2.5).
"""
import itertools
import uuid
from datetime import datetime, timezone

COLLECTIONS = (
    "tours",
    "markets",
    "venues",
    "legs",
    "shows",
    "holds",
    "packets",
    "budget_lines",
    "spends",
    "settlements",
    "compliance_holds",
)

store = {name: {} for name in COLLECTIONS}

# Logical clock (PRD 2.5). Default reads exactly 2026-05-01T00:00:00Z.
clock = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

_seq = itertools.count(1)


def now_iso():
    """Wall-clock UTC timestamp with three fractional digits (resource metadata)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_entity():
    """Common resource properties (PRD 2.4): id, created_at, updated_at, version.

    version starts at 1 at creation and increments by one on every mutation.
    """
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),  # internal insertion order tiebreak for created_at sort
    }


def touch(e):
    """Record a mutation: bump version and refresh updated_at."""
    e["version"] += 1
    e["updated_at"] = now_iso()
