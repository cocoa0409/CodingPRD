"""In-memory data store + logical clock.

The store starts completely empty on every boot. No seeding of any kind.
All entities are plain dicts keyed by id in per-collection dicts (insertion
order is preserved, which stabilizes created_at-ascending list sorts).
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.6): starts at exactly 2026-08-01T00:00:00Z,
# advances only via POST /api/_clock/set_current_utc, never reads wall clock.
# ---------------------------------------------------------------------------
_clock = {
    "now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(clock_now())


# ---------------------------------------------------------------------------
# Entity stores: one dict per collection, keyed by id. Empty at boot.
# ---------------------------------------------------------------------------
store = {
    "customers": {},
    "formulas": {},
    "formula_lines": {},
    "raw_materials": {},
    "material_lots": {},
    "identity_tests": {},
    "manufacturing_orders": {},
    "batches": {},
    "batch_consumptions": {},
    "production_lines": {},
    "cleaning_validations": {},
    "assay_results": {},
    "stability_studies": {},
    "stability_chambers": {},
    "recall_events": {},
}


def new_id():
    """Server-minted UUID string with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


def new_entity(fields):
    """Create an entity dict with the uniform system-managed fields."""
    ts = now_iso()
    entity = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    entity.update(fields)
    return entity


def touch(entity):
    """Refresh updated_at and increment version on any mutation (PRD 2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1
