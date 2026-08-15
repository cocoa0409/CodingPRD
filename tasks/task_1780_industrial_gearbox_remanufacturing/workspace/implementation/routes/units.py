"""GearUnit endpoints: odometer, check-in, scrap, order intake (PRD 3.1, 3.2)."""
from flask import Blueprint

from db import store, new_id, new_common, touch
from errors import ApiError
from middleware import (get_context, require_roles, check_customer_scope,
                        owning_customer_id_of_unit, ALL_ROLES)
from response import ok, created, paginate
from services import workflow
from validation import parse_body, require_path_entity, schema_field

bp = Blueprint("units", __name__)


def _load_unit(unit_id):
    return require_path_entity(store.units, unit_id)


@bp.get("/reman/units/<unit_id>")
def get_unit(unit_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    unit = _load_unit(unit_id)
    check_customer_scope(uid, role, owning_customer_id_of_unit(unit))
    return ok(unit)


@bp.post("/reman/units/<unit_id>/record-service-hours")
def record_service_hours(unit_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    unit = _load_unit(unit_id)
    body = parse_body({"hours": schema_field("integer")}, allow_empty=False)
    if unit["physical_status"] == "SCRAPPED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A SCRAPPED unit is locked against any further action")
    # Forward-only odometer: a lower reading simply leaves it unchanged.
    new_value = max(unit["cumulative_service_hours"], body["hours"])
    if new_value != unit["cumulative_service_hours"]:
        unit["cumulative_service_hours"] = new_value
        touch(unit)
    return ok(unit)


@bp.post("/reman/units/<unit_id>/check-in")
def check_in(unit_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    unit = _load_unit(unit_id)
    if unit["physical_status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "check-in exists only from physical_status IN_SERVICE")
    if unit["commercial_status"] == "WARRANTY_FLAGGED":
        raise ApiError("ERR_UNIT_FLAGGED", 409,
                       "A WARRANTY_FLAGGED unit may not be checked in")
    unit["physical_status"] = "AT_SHOP"
    touch(unit)
    return ok(unit)


@bp.post("/reman/units/<unit_id>/scrap")
def scrap(unit_id):
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    unit = _load_unit(unit_id)
    if unit["physical_status"] != "AT_SHOP":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "scrap exists only from physical_status AT_SHOP")
    if workflow.has_nonterminal_order(unit_id):
        raise ApiError("ERR_UNIT_BUSY", 409,
                       "Unit has a RemanOrder in a non-terminal state")
    unit["physical_status"] = "SCRAPPED"
    unit["commercial_status"] = "STANDARD"
    touch(unit)
    return ok(unit)


@bp.post("/reman/units/<unit_id>/orders")
def create_order(unit_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator"])
    unit = _load_unit(unit_id)
    body = parse_body({
        "intake_hours": schema_field("integer"),
        "quoted_estimate_cents": schema_field("integer"),
        "rush": schema_field("boolean", required=False),
    }, allow_empty=False)
    if unit["physical_status"] != "AT_SHOP":
        raise ApiError("ERR_UNIT_NOT_AT_SHOP", 409,
                       "GearUnit.physical_status must be AT_SHOP to open an order")
    if workflow.has_nonterminal_order(unit_id):
        raise ApiError("ERR_UNIT_BUSY", 409,
                       "Unit already has a RemanOrder in a non-terminal state")
    if body["intake_hours"] != unit["cumulative_service_hours"]:
        raise ApiError("ERR_INTAKE_HOURS_MISMATCH", 422,
                       "intake_hours must equal the unit's cumulative_service_hours")
    order = {
        "id": new_id(),
        "gear_unit_id": unit_id,
        "intake_hours": body["intake_hours"],
        "quoted_estimate_cents": body["quoted_estimate_cents"],
        "approved_scope_cents": 0,
        "final_invoice_cents": None,
        "rush": body.get("rush", False),
        "status": "INTAKE",
        "completed_at_hours": None,
        "completed_at_utc": None,
    }
    new_common(order)
    store.orders[order["id"]] = order
    return created(order)


@bp.get("/reman/units/<unit_id>/orders")
def list_unit_orders(unit_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    unit = _load_unit(unit_id)
    check_customer_scope(uid, role, owning_customer_id_of_unit(unit))
    rows = workflow.orders_of_unit(unit_id)
    return ok(paginate(rows), rtype="array", pagination=paginate)
