"""DeviceModel and DeviceUnit endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("catalog", __name__)

CATEGORIES = {"MAGNIFIER", "CCTV", "SCREEN_READER"}
CONDITIONS = {"NEW", "REFURB", "LOANER"}


def recompute_model_counts(model_id):
    model = store.device_models[model_id]
    in_stock = 0
    total = 0
    for unit in store.device_units.values():
        if unit["device_model_id"] == model_id:
            total += 1
            if unit["status"] == "IN_STOCK":
                in_stock += 1
    if model["in_stock_count"] != in_stock or model["total_count"] != total:
        model["in_stock_count"] = in_stock
        model["total_count"] = total
        touch(model)


@bp.post("/api/device-models")
def create_device_model():
    require_roles(["ClinicAdmin"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {
        "name", "category", "list_price_cents", "subscription_monthly_cents", "successor_model_id",
    })
    name = v.req_string(body, "name")
    category = v.req_enum(body, "category", CATEGORIES)
    list_price_cents = v.req_int(body, "list_price_cents", min_v=0)
    subscription_monthly_cents = v.opt_int(body, "subscription_monthly_cents", default=0, min_v=0)
    successor_model_id = v.opt_string(body, "successor_model_id", default=None)

    if successor_model_id is not None and successor_model_id not in store.device_models:
        raise errors.not_found("successor_model_id not found")

    model = new_entity()
    model.update({
        "name": name,
        "category": category,
        "list_price_cents": list_price_cents,
        "subscription_monthly_cents": subscription_monthly_cents,
        "successor_model_id": successor_model_id,
        "in_stock_count": 0,
        "total_count": 0,
    })
    store.device_models[model["id"]] = model
    return success_object(model, status=201)


@bp.get("/api/device-models/<mid>")
def get_device_model(mid):
    require_roles(ALL_ROLES)
    model = store.device_models.get(mid)
    if model is None:
        raise errors.not_found("DeviceModel not found")
    return success_object(model)


@bp.get("/api/device-models/<mid>/predecessors")
def list_model_predecessors(mid):
    require_roles(ALL_ROLES)
    model = store.device_models.get(mid)
    if model is None:
        raise errors.not_found("DeviceModel not found")
    limit, offset = v.parse_pagination(request.args)
    items = v.sort_by_created([
        m for m in store.device_models.values() if m.get("successor_model_id") == mid
    ])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/device-units")
def create_device_unit():
    require_roles(["ClinicAdmin"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"device_model_id", "serial_no", "condition"})
    device_model_id = v.req_string(body, "device_model_id")
    serial_no = v.req_string(body, "serial_no")
    condition = v.req_enum(body, "condition", CONDITIONS)

    if device_model_id not in store.device_models:
        raise errors.not_found("DeviceModel not found")
    for unit in store.device_units.values():
        if unit["serial_no"] == serial_no:
            raise errors.validation("serial_no must be unique across all units")

    unit = new_entity()
    unit.update({
        "device_model_id": device_model_id,
        "serial_no": serial_no,
        "condition": condition,
        "status": "IN_STOCK",
    })
    store.device_units[unit["id"]] = unit
    recompute_model_counts(device_model_id)
    return success_object(unit, status=201)


@bp.get("/api/device-units/<uid>")
def get_device_unit(uid):
    require_roles(ALL_ROLES)
    unit = store.device_units.get(uid)
    if unit is None:
        raise errors.not_found("DeviceUnit not found")
    return success_object(unit)


@bp.get("/api/device-units")
def list_device_units():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    device_model_id = request.args.get("device_model_id")
    status = request.args.get("status")
    condition = request.args.get("condition")
    items = v.apply_filters(list(store.device_units.values()), [
        (device_model_id, "device_model_id"),
        (status, "status"),
        (condition, "condition"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/api/device-units/<uid>/repair-tickets")
def list_unit_repair_tickets(uid):
    require_roles(ALL_ROLES)
    unit = store.device_units.get(uid)
    if unit is None:
        raise errors.not_found("DeviceUnit not found")
    limit, offset = v.parse_pagination(request.args)
    items = v.sort_by_created([
        t for t in store.repair_tickets.values() if t["device_unit_id"] == uid
    ])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/device-units/<uid>/retire")
def retire_device_unit(uid):
    require_roles(["ClinicAdmin"])
    unit = store.device_units.get(uid)
    if unit is None:
        raise errors.not_found("DeviceUnit not found")
    if unit["status"] != "IN_STOCK":
        raise errors.invalid_state("Only an IN_STOCK unit can be retired")
    unit["status"] = "RETIRED"
    touch(unit)
    recompute_model_counts(unit["device_model_id"])
    return success_object(unit)
