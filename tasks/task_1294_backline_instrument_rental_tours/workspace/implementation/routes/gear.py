"""GearModel and GearUnit endpoints (PRD §3.3, §3.6)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain
from util import (body, req_str, opt_int, opt_enum, opt_str_list, req_enum,
                  parse_date, new_resource, touch, pagination_params, paginate,
                  sort_by_created)

bp = Blueprint("gear", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}
CATEGORIES = {"GUITAR", "BASS", "DRUMS", "KEYS", "AMP", "PA", "BACKLINE_MISC"}
WEIGHT_CLASSES = {"HAND_CARRY", "STANDARD", "HEAVY", "OVERSIZE"}


# ---------------------------------------------------------------------------
# Gear models
# ---------------------------------------------------------------------------

@bp.route("/backline/gear-models", methods=["POST"])
def create_gear_model():
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    data = body()
    sku = req_str(data, "sku")
    daily_rate = opt_int(data, "daily_rate_cents", minimum=0)
    if daily_rate is None:
        raise errors.invalid_request("Missing required field: daily_rate_cents")
    replacement_value = opt_int(data, "replacement_value_cents")
    if replacement_value is None:
        raise errors.invalid_request("Missing required field: replacement_value_cents")
    if replacement_value <= 0:
        raise errors.invalid_request("replacement_value_cents must be > 0")
    # Catalog-unique SKU (ERR_DUPLICATE)
    for m in store.gear_models.values():
        if m.get("sku") == sku:
            raise errors.duplicate("sku already exists")
    model = new_resource()
    model.update({
        "sku": sku,
        "category": req_enum(data, "category", CATEGORIES),
        "daily_rate_cents": daily_rate,
        "replacement_value_cents": replacement_value,
        "weight_class": req_enum(data, "weight_class", WEIGHT_CLASSES),
        "substitute_model_ids": opt_str_list(data, "substitute_model_ids", default=[]),
    })
    store.gear_models[model["id"]] = model
    return success_object(domain.serialize(model), status=201)


@bp.route("/backline/gear-models/<model_id>", methods=["GET"])
def fetch_gear_model(model_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    model = domain.get_gear_model(model_id)
    return success_object(domain.serialize(model), status=200)


@bp.route("/backline/gear-models", methods=["GET"])
def list_gear_models():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    category = request.args.get("category")
    items = list(store.gear_models.values())
    if category is not None:
        items = [m for m in items if m.get("category") == category]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(m) for m in page], meta, status=200)


# ---------------------------------------------------------------------------
# Gear units
# ---------------------------------------------------------------------------

@bp.route("/backline/gear-units", methods=["POST"])
def create_gear_unit():
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    data = body()
    gear_model_id = req_str(data, "gear_model_id")
    model = domain.get_gear_model(gear_model_id)
    serial_number = req_str(data, "serial_number")
    # Fleet-unique serial (ERR_DUPLICATE)
    for u in store.gear_units.values():
        if u.get("serial_number") == serial_number:
            raise errors.duplicate("serial_number already exists")
    unit = new_resource()
    unit.update({
        "gear_model_id": gear_model_id,
        "serial_number": serial_number,
        "home_city_code": req_str(data, "home_city_code"),
        "status": "AVAILABLE",
        "condition_score": 100,
        "rental_days_since_service": 0,
        "flight_case_required": model.get("weight_class") in {"HEAVY", "OVERSIZE"},
        "active_reservation_id": None,
    })
    store.gear_units[unit["id"]] = unit
    return success_object(domain.serialize(unit), status=201)


@bp.route("/backline/gear-units/<unit_id>", methods=["GET"])
def fetch_gear_unit(unit_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    unit = domain.get_gear_unit(unit_id)
    return success_object(domain.serialize(unit), status=200)


@bp.route("/backline/gear-units", methods=["GET"])
def list_gear_units():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    gear_model_id = request.args.get("gear_model_id")
    home_city_code = request.args.get("home_city_code")
    status = request.args.get("status")
    active_reservation_id = request.args.get("active_reservation_id")
    items = list(store.gear_units.values())
    if gear_model_id is not None:
        items = [u for u in items if u.get("gear_model_id") == gear_model_id]
    if home_city_code is not None:
        items = [u for u in items if u.get("home_city_code") == home_city_code]
    if status is not None:
        items = [u for u in items if u.get("status") == status]
    if active_reservation_id is not None:
        items = [u for u in items if u.get("active_reservation_id") == active_reservation_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(u) for u in page], meta, status=200)


@bp.route("/backline/gear-units/<unit_id>/shipment-lines", methods=["GET"])
def list_unit_shipment_lines(unit_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    domain.get_gear_unit(unit_id)
    limit, offset = pagination_params()
    items = [sl for sl in store.shipment_lines.values() if sl.get("gear_unit_id") == unit_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(sl) for sl in page], meta, status=200)


@bp.route("/backline/gear-units/<unit_id>/retire", methods=["POST"])
def retire_gear_unit(unit_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    unit = domain.get_gear_unit(unit_id)
    if unit["status"] != "AVAILABLE":
        raise errors.invalid_state("Unit must be AVAILABLE to retire")
    # No reservation in DRAFT/SOURCED/DISPATCHED/DELIVERED may reference it
    for r in store.reservation_lines.values():
        if r.get("gear_unit_id") == unit["id"] and r.get("status") in \
                {"DRAFT", "SOURCED", "DISPATCHED", "DELIVERED"}:
            raise errors.invalid_state("Unit is referenced by an open reservation")
    unit["status"] = "RETIRED"
    touch(unit)
    return success_object(domain.serialize(unit), status=200)


@bp.route("/backline/gear-units/<unit_id>/availability", methods=["GET"])
def gear_unit_availability(unit_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager", "TourManager", "LogisticsCoordinator"})
    unit = domain.get_gear_unit(unit_id)
    raw_start = request.args.get("start_date")
    raw_end = request.args.get("end_date")
    if raw_start is None or raw_end is None:
        raise errors.invalid_request("Query parameters start_date and end_date are required")
    start_dt = parse_date(raw_start, "start_date")
    end_dt = parse_date(raw_end, "end_date")
    conflicting = []
    for r in store.reservation_lines.values():
        if r.get("gear_unit_id") != unit["id"]:
            continue
        if r.get("status") not in {"SOURCED", "DISPATCHED", "DELIVERED"}:
            continue
        # half-open overlap; adjacent end==start does not conflict
        if r["_start_dt"] < end_dt and r["_end_dt"] > start_dt:
            conflicting.append(r["id"])
    return success_object({
        "available": len(conflicting) == 0,
        "conflicting_reservation_ids": conflicting,
    }, status=200)
