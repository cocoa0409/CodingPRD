"""Flat top-level resource lookups: canonical GET-by-id + FK-filtered lists."""
from flask import Blueprint, request

from db import db, LOCK
from middleware import get_identity, require_roles, parse_pagination
from response import success, paginated
from services.common import get_or_404, public, sorted_by_creation, paginate

bp = Blueprint("flat", __name__)

MO_FM = {"MemberOperator", "FacilityManager"}
MO_FM_CO = {"MemberOperator", "FacilityManager", "ComplianceOfficer"}
CO_FM = {"ComplianceOfficer", "FacilityManager"}


def _get_by_id(collection, entity_id, allowed):
    _, role = get_identity()
    require_roles(role, allowed)
    with LOCK:
        rec = get_or_404(collection, entity_id)
        return success(public(rec))


def _list(collection, allowed, filters):
    """filters: list of (query_param, record_key) equality filters."""
    _, role = get_identity()
    require_roles(role, allowed)
    limit, offset = parse_pagination()
    with LOCK:
        records = sorted_by_creation(list(collection.values()))
        for param, key in filters:
            val = request.args.get(param)
            if val is not None:
                records = [r for r in records if str(r.get(key)) == val]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


# ── Bookings ──
@bp.get("/bookings/<entity_id>")
def get_booking(entity_id):
    return _get_by_id(db.bookings, entity_id, MO_FM)


@bp.get("/bookings")
def list_bookings():
    return _list(db.bookings, MO_FM, [("member_id", "member_id"),
                                      ("station_id", "station_id"), ("status", "status")])


# ── Storage assignments ──
@bp.get("/storage-assignments/<entity_id>")
def get_storage_assignment(entity_id):
    return _get_by_id(db.storage_assignments, entity_id, MO_FM_CO)


@bp.get("/storage-assignments")
def list_storage_assignments():
    _, role = get_identity()
    require_roles(role, MO_FM_CO)
    limit, offset = parse_pagination()
    with LOCK:
        records = sorted_by_creation(list(db.storage_assignments.values()))
        member_id = request.args.get("member_id")
        unit_id = request.args.get("storage_unit_id")
        status = request.args.get("status")
        if member_id is not None:
            records = [r for r in records if r["member_id"] == member_id]
        if unit_id is not None:
            records = [r for r in records
                       if any(e["storage_unit_id"] == unit_id for e in r["allocation_plan"])]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


# ── Recipes ──
@bp.get("/recipes/<entity_id>")
def get_recipe(entity_id):
    return _get_by_id(db.recipes, entity_id, MO_FM)


@bp.get("/recipes")
def list_recipes():
    return _list(db.recipes, MO_FM, [("member_id", "member_id"), ("status", "status")])


# ── Recipe components ──
@bp.get("/recipe-components/<entity_id>")
def get_recipe_component(entity_id):
    return _get_by_id(db.recipe_components, entity_id, MO_FM)


@bp.get("/recipe-components")
def list_recipe_components():
    return _list(db.recipe_components, MO_FM,
                 [("recipe_id", "recipe_id"), ("ingredient_id", "ingredient_id")])


# ── Batches ──
@bp.get("/batches/<entity_id>")
def get_batch(entity_id):
    return _get_by_id(db.production_batches, entity_id, MO_FM)


@bp.get("/batches")
def list_batches():
    return _list(db.production_batches, MO_FM,
                 [("member_id", "member_id"), ("recipe_id", "recipe_id"), ("status", "status")])


# ── Temp logs ──
@bp.get("/temp-logs/<entity_id>")
def get_temp_log(entity_id):
    return _get_by_id(db.temp_logs, entity_id, CO_FM)


@bp.get("/temp-logs")
def list_temp_logs():
    _, role = get_identity()
    require_roles(role, CO_FM)
    limit, offset = parse_pagination()
    with LOCK:
        records = sorted_by_creation(list(db.temp_logs.values()))
        unit_id = request.args.get("storage_unit_id")
        in_range = request.args.get("in_range")
        if unit_id is not None:
            records = [r for r in records if r["storage_unit_id"] == unit_id]
        if in_range is not None:
            want = in_range.lower() == "true"
            records = [r for r in records if r["in_range"] == want]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


# ── Ingredient orders ──
@bp.get("/ingredient-orders/<entity_id>")
def get_ingredient_order(entity_id):
    return _get_by_id(db.ingredient_orders, entity_id, MO_FM)


@bp.get("/ingredient-orders")
def list_ingredient_orders():
    return _list(db.ingredient_orders, MO_FM,
                 [("member_id", "member_id"), ("ingredient_id", "ingredient_id"),
                  ("status", "status")])


# ── Packouts ──
@bp.get("/packouts/<entity_id>")
def get_packout(entity_id):
    return _get_by_id(db.event_packouts, entity_id, MO_FM)


@bp.get("/packouts")
def list_packouts():
    return _list(db.event_packouts, MO_FM, [("member_id", "member_id"), ("status", "status")])


# ── Invoices ──
@bp.get("/invoices/<entity_id>")
def get_invoice(entity_id):
    return _get_by_id(db.invoices, entity_id, MO_FM)


@bp.get("/invoices")
def list_invoices():
    return _list(db.invoices, MO_FM, [("member_id", "member_id"), ("status", "status")])
