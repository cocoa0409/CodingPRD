from flask import Blueprint, request

from db import DB, stamp_new, touch
from errors import (
    ERR_EXCHANGE_NOT_REQUESTED,
    ERR_POOL_CUSTOMER_MISMATCH,
    ERR_POOL_PROGRAM_REQUIRED,
    invalid_state,
    not_found,
    raise_err,
)
from middleware import (
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.customers import parse_pagination
from services.core import recompute_pool_available_count

bp = Blueprint("pool_units", __name__)

POO_TERMINAL = {"ISSUED", "WITHDRAWN"}


def get_unit_or_404(uid: str) -> dict:
    unit = DB.pool_units.get(uid)
    if unit is None:
        not_found("Pool unit not found")
    return unit


@bp.route("/pool-units", methods=["POST"])
def create_pool_unit():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    customer_id = as_string(body, "customer_id")
    asset_id = as_string(body, "asset_id")
    customer = DB.customers.get(customer_id)
    if customer is None:
        not_found("Customer not found")
    asset = DB.assets.get(asset_id)
    if asset is None:
        not_found("Asset not found")
    if not customer.get("pool_program"):
        raise_err(ERR_POOL_PROGRAM_REQUIRED, "Customer is not enrolled in the pool program")

    unit = stamp_new(
        {
            "customer_id": customer_id,
            "asset_id": asset_id,
            "pool_status": "IN_POOL",
            "reserved_for_ro_id": None,
        }
    )
    DB.pool_units[unit["id"]] = unit
    recompute_pool_available_count(customer_id)
    return success_object(unit, status=201)


@bp.route("/pool-units", methods=["GET"])
def list_pool_units():
    authenticate()
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    asset_id = request.args.get("asset_id")
    pool_status = request.args.get("pool_status")
    reserved_for_ro_id = request.args.get("reserved_for_ro_id")
    items = sorted(DB.pool_units.values(), key=lambda u: (u["created_at"], u["id"]))
    if customer_id is not None:
        items = [u for u in items if u["customer_id"] == customer_id]
    if asset_id is not None:
        items = [u for u in items if u["asset_id"] == asset_id]
    if pool_status is not None:
        items = [u for u in items if u["pool_status"] == pool_status]
    if reserved_for_ro_id is not None:
        items = [u for u in items if u.get("reserved_for_ro_id") == reserved_for_ro_id]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/pool-units/<uid>", methods=["GET"])
def get_pool_unit(uid):
    caller = authenticate()
    unit = get_unit_or_404(uid)
    require_customer_ownership(caller, unit["customer_id"])
    return success_object(unit)


@bp.route("/pool-units/<uid>/reserve", methods=["POST"])
def reserve_unit(uid):
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    repair_order_id = as_string(body, "repair_order_id")
    unit = get_unit_or_404(uid)
    if unit["pool_status"] != "IN_POOL":
        invalid_state("Pool unit is not IN_POOL")
    ro = DB.repair_orders.get(repair_order_id)
    if ro is None:
        not_found("Repair order not found")
    if ro["status"] in ("CLOSED", "CANCELLED"):
        invalid_state("Repair order is in a terminal state")
    if ro["customer_id"] != unit["customer_id"]:
        raise_err(ERR_POOL_CUSTOMER_MISMATCH, "Pool unit and repair order belong to different customers")
    if not ro.get("exchange_requested"):
        raise_err(ERR_EXCHANGE_NOT_REQUESTED, "Repair order did not request a pool exchange")
    unit["pool_status"] = "RESERVED"
    unit["reserved_for_ro_id"] = ro["id"]
    touch(unit)
    recompute_pool_available_count(unit["customer_id"])
    return success_object(unit)


@bp.route("/pool-units/<uid>/release", methods=["POST"])
def release_unit(uid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    unit = get_unit_or_404(uid)
    if unit["pool_status"] != "RESERVED":
        invalid_state("Pool unit is not RESERVED")
    unit["pool_status"] = "IN_POOL"
    unit["reserved_for_ro_id"] = None
    touch(unit)
    recompute_pool_available_count(unit["customer_id"])
    return success_object(unit)


@bp.route("/pool-units/<uid>/issue", methods=["POST"])
def issue_unit(uid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    unit = get_unit_or_404(uid)
    if unit["pool_status"] != "RESERVED":
        invalid_state("Pool unit is not RESERVED")
    ro = DB.repair_orders.get(unit.get("reserved_for_ro_id") or "")
    allowed = {"AUTHORIZED", "IN_REPAIR", "IN_TEST", "READY_FOR_CERT", "COMPLETE"}
    if ro is None or ro["status"] not in allowed:
        invalid_state("Linked repair order has not reached AUTHORIZED or later")
    unit["pool_status"] = "ISSUED"
    unit["reserved_for_ro_id"] = None
    touch(unit)
    recompute_pool_available_count(unit["customer_id"])
    return success_object(unit)


@bp.route("/pool-units/<uid>/withdraw", methods=["POST"])
def withdraw_unit(uid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["Customer", "IntakeCoordinator"])
    unit = get_unit_or_404(uid)
    require_customer_ownership(caller, unit["customer_id"])
    if unit["pool_status"] != "IN_POOL":
        invalid_state("Pool unit is not IN_POOL")
    unit["pool_status"] = "WITHDRAWN"
    touch(unit)
    recompute_pool_available_count(unit["customer_id"])
    return success_object(unit)
