"""Spare-part catalogue, stock movements and the end-of-support declaration."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import calc, domain, parts as parts_service, validate

bp = Blueprint("parts", __name__)


@bp.post("/fleetcare/parts")
def create_part():
    middleware.auth(middleware.PARTS_PLANNER, middleware.CONTRACT_ADMIN)
    body = middleware.body()
    model_id = validate.identifier(body, "model_id")
    part_number = validate.string(body, "part_number", min_len=1, max_len=40)
    category = validate.enum(body, "category", calc.PART_CATEGORIES)
    unit_price_cents = validate.integer(body, "unit_price_cents", minimum=0)
    is_critical = validate.boolean(body, "is_critical_spare", default=False)
    initial_on_hand = validate.integer(body, "initial_on_hand_qty", minimum=0,
                                       required=False, default=0)
    initial_refurb = validate.integer(body, "initial_refurb_qty", minimum=0,
                                      required=False, default=0)

    domain.need_model(model_id)

    row = db.base_row()
    row.update({
        "model_id": model_id,
        "part_number": part_number,
        "category": category,
        "unit_price_cents": unit_price_cents,
        "is_critical_spare": is_critical,
        "on_hand_qty": initial_on_hand,
        "refurb_on_hand_qty": initial_refurb,
        "allocated_qty": 0,
        "lifecycle_status": "ACTIVE",
        "eos_declared_at": None,
    })
    db.parts[row["id"]] = row
    return response.created_response(row)


@bp.get("/fleetcare/parts")
def list_parts():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.parts, {
        "model_id": response.arg("model_id"),
        "category": response.arg("category"),
        "lifecycle_status": response.arg("lifecycle_status"),
        "is_critical_spare": response.bool_filter("is_critical_spare"),
    })


@bp.get("/fleetcare/parts/<part_id>")
def read_part(part_id):
    middleware.auth(*middleware.ALL_ROLES)
    return response.object_response(domain.need_part(part_id))


@bp.post("/fleetcare/parts/<part_id>/inventory-adjustments")
def adjust_inventory(part_id):
    middleware.auth(middleware.PARTS_PLANNER)
    part = domain.need_part(part_id)
    body = middleware.body()
    new_delta = validate.integer(body, "new_qty_delta")
    refurb_delta = validate.integer(body, "refurb_qty_delta")

    new_on_hand = part["on_hand_qty"] + new_delta
    new_refurb = part["refurb_on_hand_qty"] + refurb_delta
    # The adjustment is refused whole, leaving both buckets untouched.
    if new_on_hand < 0 or new_refurb < 0:
        raise ApiError("ERR_INVENTORY_ADJUSTMENT_INVALID")

    changes = {"on_hand_qty": new_on_hand, "refurb_on_hand_qty": new_refurb}
    slid_to_obsolete = (
        part["lifecycle_status"] == "END_OF_SUPPORT_ANNOUNCED" and new_refurb == 0
    )
    if slid_to_obsolete:
        changes["lifecycle_status"] = "OBSOLETE"
    db.apply_changes(part, changes)
    if slid_to_obsolete:
        parts_service.obsolescence_cascade(part, "OBSOLETE")
    return response.object_response(part)


@bp.post("/fleetcare/parts/<part_id>/declare-end-of-support")
def declare_end_of_support(part_id):
    middleware.auth(middleware.PARTS_PLANNER)
    part = domain.need_part(part_id)

    if part["lifecycle_status"] == "OBSOLETE":
        # OBSOLETE is terminal: only the declaration stamp moves.
        lifecycle_status = "OBSOLETE"
    elif part["refurb_on_hand_qty"] > 0:
        lifecycle_status = "END_OF_SUPPORT_ANNOUNCED"
    else:
        lifecycle_status = "OBSOLETE"

    db.apply_changes(part, {
        "lifecycle_status": lifecycle_status,
        "eos_declared_at": db.now_iso(),
    })
    parts_service.obsolescence_cascade(part, lifecycle_status)
    return response.object_response(part)


# ---------------------------------------------------------------------------
# Part orders
# ---------------------------------------------------------------------------
@bp.get("/fleetcare/part-orders")
def list_part_orders():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.part_orders, {
        "service_call_id": response.arg("service_call_id"),
        "part_id": response.arg("part_id"),
        "status": response.arg("status"),
        "source": response.arg("source"),
    })


@bp.get("/fleetcare/part-orders/<order_id>")
def read_part_order(order_id):
    middleware.auth(*middleware.ALL_ROLES)
    return response.object_response(domain.need_part_order(order_id))


@bp.post("/fleetcare/part-orders/<order_id>/install")
def install_part_order(order_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    order = domain.need_part_order(order_id)
    call = db.calls.get(order["service_call_id"])
    middleware.require_assigned(ctx, call["assigned_technician_id"] if call else None)
    if order["status"] != "ALLOCATED":
        raise ApiError("ERR_PART_ORDER_INVALID_STATE")
    if call is None or call["status"] != "PARTS_HOLD":
        raise ApiError("ERR_PART_ORDER_INVALID_STATE")

    parts_service.install(order)
    return response.object_response(order)


@bp.post("/fleetcare/part-orders/<order_id>/cancel")
def cancel_part_order(order_id):
    middleware.auth(middleware.SERVICE_COORDINATOR, middleware.PARTS_PLANNER)
    order = domain.need_part_order(order_id)
    body = middleware.body()
    reason = validate.string(body, "reason", min_len=1)
    if order["status"] != "ALLOCATED":
        raise ApiError("ERR_PART_ORDER_INVALID_STATE")

    parts_service.cancel(order, reason)
    return response.object_response(order)
