"""In-memory data store.

ALL state lives in module-level dicts keyed by id. Nothing is seeded at
startup; every entity is created via the declared API surface. A fresh process
(per-test-server restart) starts completely empty.

Common system fields (PRD §2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO8601 UTC, 3 fractional digits, set on create
  - updated_at: refreshed on every mutation (absent for QualifyingStay)
  - version: integer starting at 1, +1 on every mutation (absent for QualifyingStay)

QualifyingStay is deliberately lightweight: only id + created_at (PRD §2.4).
"""
import uuid

from clock import now_iso

# Entity collections keyed by id.
facilities = {}
pdpm_rates = {}
residents = {}
pasrr_screenings = {}
qualifying_stays = {}
admissions = {}
assessments = {}
therapy_logs = {}
care_plans = {}
care_plan_goals = {}
bed_holds = {}
claims = {}
quality_measures = {}

# Monotonic creation sequence so list ordering by created_at is stable even
# when multiple rows share the same millisecond timestamp.
_seq = 0


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def stamp_create(obj, versioned=True):
    """Attach common system fields (PRD §2.4).

    versioned=True  -> id, created_at, updated_at, version=1 (most entities)
    versioned=False -> id, created_at only (QualifyingStay)
    """
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["_seq"] = _next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Record a mutation: refresh updated_at and bump version by 1 (PRD §2.4)."""
    if "version" in obj:
        obj["updated_at"] = now_iso()
        obj["version"] = obj.get("version", 1) + 1
    return obj
