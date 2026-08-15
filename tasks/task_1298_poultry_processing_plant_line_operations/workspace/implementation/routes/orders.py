"""Product orders: create, amend (OCC), cancel."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_ORDER_VERSION,
    ERR_ORDER_NOT_AMENDABLE,
    ERR_ORDER_NOT_CANCELLABLE,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_number,
    check_int,
    check_string,
    parse_iso8601,
)
from response import success_object
from services.core import new_entity, _touch, recompute_shift_labor
from services.serializers import serialize_order

bp = Blueprint("orders", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)
PRODUCT_CODES = ("WINGS", "BREAST_FILLET", "THIGH_MEAT", "TENDERLOIN", "WHOLE_BIRD")
TEMP_REQS = ("FRESH", "FROZEN", "FLEXIBLE")


@bp.route("/poultry/orders", methods=["POST"])
def create_order():
    require_roles("OrderPlanner")
    body = get_json_body()
    check_no_unknown(
        body,
        {"customer_name", "product_code", "pounds_ordered", "temperature_requirement", "due_at"},
    )
    check_required(
        body,
        {"customer_name", "product_code", "pounds_ordered", "temperature_requirement", "due_at"},
    )
    check_string(body["customer_name"], "customer_name")
    check_enum(body["product_code"], PRODUCT_CODES, "product_code")
    check_number(body["pounds_ordered"], "pounds_ordered", min_value=0, exclusive_min=True)
    check_enum(body["temperature_requirement"], TEMP_REQS, "temperature_requirement")
    due_at = parse_iso8601(body["due_at"], "due_at")

    order = new_entity()
    order.update({
        "customer_name": body["customer_name"],
        "product_code": body["product_code"],
        "pounds_ordered": body["pounds_ordered"],
        "temperature_requirement": body["temperature_requirement"],
        "due_at": due_at,
        "fulfillment_status": "PENDING",
        "allocation_status": "UNALLOCATED",
        "filled_lb": 0,
    })
    db.orders[order["id"]] = order
    return success_object(serialize_order(order), 201)


@bp.route("/poultry/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_roles(*ALL_ROLES)
    order = db.orders.get(order_id)
    if not order:
        raise ApiError(ERR_NOT_FOUND, "Order not found", 404)
    return success_object(serialize_order(order))


@bp.route("/poultry/orders/<order_id>", methods=["PUT"])
def amend_order(order_id):
    require_roles("OrderPlanner")
    order = db.orders.get(order_id)
    if not order:
        raise ApiError(ERR_NOT_FOUND, "Order not found", 404)
    body = get_json_body()
    check_no_unknown(
        body,
        {"pounds_ordered", "due_at", "temperature_requirement", "expected_order_version"},
    )
    check_required(body, ["expected_order_version"])
    check_int(body["expected_order_version"], "expected_order_version")

    # OCC first (priority 3.5), before business validation
    if body["expected_order_version"] != order["version"]:
        raise ApiError(
            ERR_STALE_ORDER_VERSION,
            "expected_order_version does not match the order's current version",
            412,
        )

    if order["fulfillment_status"] != "PENDING":
        raise ApiError(
            ERR_ORDER_NOT_AMENDABLE,
            "Order amend attempted after fulfillment left PENDING",
            409,
        )

    if "pounds_ordered" in body and body["pounds_ordered"] is not None:
        check_number(body["pounds_ordered"], "pounds_ordered", min_value=0, exclusive_min=True)
        order["pounds_ordered"] = body["pounds_ordered"]
    if "due_at" in body and body["due_at"] is not None:
        order["due_at"] = parse_iso8601(body["due_at"], "due_at")
    if "temperature_requirement" in body and body["temperature_requirement"] is not None:
        check_enum(body["temperature_requirement"], TEMP_REQS, "temperature_requirement")
        order["temperature_requirement"] = body["temperature_requirement"]

    _touch(order)
    return success_object(serialize_order(order))


@bp.route("/poultry/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    require_roles("OrderPlanner")
    order = db.orders.get(order_id)
    if not order:
        raise ApiError(ERR_NOT_FOUND, "Order not found", 404)

    if order["fulfillment_status"] not in ("PENDING", "IN_PRODUCTION"):
        raise ApiError(
            ERR_ORDER_NOT_CANCELLABLE,
            "Order cancel attempted from a non-cancellable state",
            409,
        )

    active = any(
        b for b in db.deboning_batches.values()
        if b["order_id"] == order["id"] and b["status"] in ("IN_PROGRESS", "ON_HOLD")
    )
    if active:
        raise ApiError(
            ERR_ORDER_NOT_CANCELLABLE,
            "Order cancel attempted while batches are IN_PROGRESS or ON_HOLD",
            409,
        )

    # Cascade: SCHEDULED batches -> CANCELLED, releasing estimated labor
    affected_shifts = set()
    for b in db.deboning_batches.values():
        if b["order_id"] == order["id"] and b["status"] == "SCHEDULED":
            b["status"] = "CANCELLED"
            _touch(b)
            affected_shifts.add(b["shift_id"])

    order["fulfillment_status"] = "CANCELLED"
    _touch(order)

    for sid in affected_shifts:
        shift = db.shifts.get(sid)
        if shift:
            recompute_shift_labor(shift)
            _touch(shift)

    return success_object(serialize_order(order))
