"""Shared lookup / mutation helpers."""

from flask import g

from db import by_seq, db, now_utc
from errors import ApiError


def touch(record):
    """Refresh updated_at and bump version by exactly 1 for this request.

    PRD section 2.8: when a write cascades, every entity it touches has its
    updated_at refreshed and its version incremented by 1 -- once per entity per
    request, however many hops of the same cascade reach it.
    """
    if record is None or "version" not in record:
        return record
    key = (record["_kind"], record["id"])
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if key not in touched:
        touched.add(key)
        record["version"] += 1
        record["_updated_at"] = now_utc()
    return record


def path_lookup(collection, resource_id):
    """Rung 4: path parameter existence, evaluated left to right."""
    record = collection.get(resource_id)
    if record is None:
        raise ApiError("ERR_NOT_FOUND")
    return record


def ref_lookup(collection, resource_id):
    """Rung 5: request-body foreign key existence."""
    record = collection.get(resource_id)
    if record is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return record


def ensure_unique(collection, field, value):
    """Rung 14: duplicate code detection."""
    for record in collection.values():
        if record.get(field) == value:
            raise ApiError("ERR_DUPLICATE_CODE", "%s '%s' already exists" % (field, value))


def defects_of(lot_id):
    return by_seq([d for d in db.casting_defects.values() if d["casting_lot_id"] == lot_id])


def build_orders_of_lot(lot_id):
    return by_seq([b for b in db.build_orders.values() if b["casting_lot_id"] == lot_id])


def packages_of_build(build_order_id):
    return by_seq([p for p in db.pump_packages.values() if p["build_order_id"] == build_order_id])


def allocations_of_build(build_order_id):
    return by_seq(
        [a for a in db.kit_allocations.values() if a["build_order_id"] == build_order_id]
    )


def points_of_run(test_run_id):
    return by_seq([p for p in db.test_points.values() if p["test_run_id"] == test_run_id])


def patterns_of_model(model_id):
    return by_seq([p for p in db.pattern_assets.values() if p["pump_model_id"] == model_id])


def lots_of_pattern(pattern_id):
    return by_seq([l for l in db.casting_lots.values() if l["pattern_asset_id"] == pattern_id])


def lots_of_foundry(foundry_id):
    return by_seq([l for l in db.casting_lots.values() if l["foundry_id"] == foundry_id])


def selection_of_build(build_order):
    return db.selections.get(build_order["selection_id"])


def model_of_selection(selection):
    if selection is None:
        return None
    return db.pump_models.get(selection["pump_model_id"])


def config_of_selection(selection):
    if selection is None:
        return None
    return db.material_seal_configs.get(selection["material_seal_config_id"])


def duty_of_selection(selection):
    if selection is None:
        return None
    return db.duty_applications.get(selection["duty_application_id"])


def paginate(records, limit, offset):
    total = len(records)
    window = records[offset:offset + limit]
    return window, total


def apply_filters(records, filters):
    """filters: list of (query value, record field). None query values are ignored."""
    result = records
    for value, field in filters:
        if value is None:
            continue
        result = [r for r in result if str(r.get(field)) == value]
    return result
