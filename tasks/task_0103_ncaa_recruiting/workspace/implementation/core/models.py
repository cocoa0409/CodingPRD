"""Entity factories and common-field helpers."""

from core.clock import CLOCK, iso_format
from core.store import STORE, gen_id


# Resources that carry the standard common fields (created_at, updated_at, version).
# Append-only logs (RecruitingCalendar, RecruitingContact, EligibilityRecord) only get id+created_at.
COMMON_FIELD_RESOURCES = {
    "Program",
    "Athlete",
    "ScholarshipSlot",
    "NILDeal",
    "TransferPortalEntry",
    "ComplianceViolation",
}


def make_entity(kind: str, fields: dict) -> dict:
    """Build an entity dict with id + system metadata. Returns dict (not stored yet)."""
    now = CLOCK.now_iso()
    base = {"id": gen_id(), "created_at": now}
    if kind in COMMON_FIELD_RESOURCES:
        base["updated_at"] = now
        base["version"] = 1
    base.update(fields)
    base["_seq"] = STORE.next_seq()
    return base


def mark_mutated(entity: dict):
    """Refresh updated_at and bump version on a resource that carries those fields."""
    if "updated_at" in entity:
        entity["updated_at"] = CLOCK.now_iso()
    if "version" in entity:
        entity["version"] = int(entity["version"]) + 1


# -- Serializers: strip private fields ------------------------------------

PRIVATE_KEYS = {"_seq"}


def serialize(entity: dict) -> dict:
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if k not in PRIVATE_KEYS}


def serialize_list(items):
    return [serialize(e) for e in items]
