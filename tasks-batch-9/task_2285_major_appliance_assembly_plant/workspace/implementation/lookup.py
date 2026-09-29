"""Entity lookup helpers (validation ladder priorities 4 and 5)."""

from db import db
from errors import ApiError

LINE = ("lines", "ERR_LINE_NOT_FOUND")
STATION = ("stations", "ERR_STATION_NOT_FOUND")
MODEL_VARIANT = ("model_variants", "ERR_MODEL_VARIANT_NOT_FOUND")
SUPPLIER = ("suppliers", "ERR_SUPPLIER_NOT_FOUND")
PART = ("parts", "ERR_PART_NOT_FOUND")
BOM_LINE = ("bom_lines", "ERR_BOM_LINE_NOT_FOUND")
DELIVERY_CALL = ("delivery_calls", "ERR_DELIVERY_CALL_NOT_FOUND")
SHIFT_PLAN = ("shift_plans", "ERR_SHIFT_PLAN_NOT_FOUND")
BUILD_SLOT = ("build_slots", "ERR_BUILD_SLOT_NOT_FOUND")
PRODUCTION_UNIT = ("production_units", "ERR_PRODUCTION_UNIT_NOT_FOUND")
ENGINEERING_CHANGE = ("engineering_changes", "ERR_ENGINEERING_CHANGE_NOT_FOUND")
WARRANTY_RETURN = ("warranty_returns", "ERR_WARRANTY_RETURN_NOT_FOUND")


def must(kind, entity_id):
    """Resolve an identifier or raise the entity's own not-found error."""
    collection, error_id = kind
    record = getattr(db, collection).get(entity_id) if isinstance(entity_id, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def must_fk(kind, entity_id):
    if entity_id is None:
        return None
    return must(kind, entity_id)


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
