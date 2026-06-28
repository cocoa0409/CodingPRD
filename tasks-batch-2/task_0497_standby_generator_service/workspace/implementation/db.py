"""In-memory data store. Plain dicts keyed by UUID id.

The store starts EMPTY on every process boot. Nothing is seeded, preloaded, or
hardcoded — every entity is created by a test via the declared API surface.
"""
import uuid

from clock import get_now, to_iso8601

# Each collection: id -> record dict. Insertion order preserved (Python 3.7+),
# which gives natural creation-order iteration for list endpoints.
customers = {}
technicians = {}
models = {}
projects = {}
load_assessments = {}
units = {}
maintenance_plans = {}
maintenance_visits = {}
exercise_logs = {}
warranty_claims = {}
repair_dispatches = {}
recall_campaigns = {}
recall_remediations = {}

# Monotonic counter to break creation-order ties deterministically (multiple
# records can share an identical logical-clock created_at).
_seq = 0


def reset():
    """Wipe all state. Used at import only — fresh boot already gives empty dicts."""
    global _seq
    for coll in (
        customers, technicians, models, projects, load_assessments, units,
        maintenance_plans, maintenance_visits, exercise_logs, warranty_claims,
        repair_dispatches, recall_campaigns, recall_remediations,
    ):
        coll.clear()
    _seq = 0


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def now_iso():
    return to_iso8601(get_now())


def base_record(full_common=True):
    """Build the system-managed common fields.

    full_common=True  -> id, created_at, updated_at, version (most entities)
    full_common=False -> id, created_at only (GeneratorModel, LoadAssessment,
                          ExerciseLog are append-only / lean)
    """
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": _next_seq(),
    }
    if full_common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a mutation: refresh updated_at + bump version (if the entity has them)."""
    if "version" in rec:
        rec["updated_at"] = now_iso()
        rec["version"] += 1


def sort_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def public(rec):
    """Strip internal-only keys (those prefixed with '_') from a record copy."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
