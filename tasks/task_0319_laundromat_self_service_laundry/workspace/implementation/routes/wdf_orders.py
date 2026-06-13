"""WdfOrder endpoints (PRD §3.5)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import (
    err,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_INSUFFICIENT_WALLET,
)
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
    require_bool,
    parse_pagination,
    paginate,
    get_or_404,
    require_active_plan,
    open_shift_for,
)
from services.calc import wdf_total_cents
from services.serialize import view

bp = Blueprint("wdf_orders", __name__)

PAY_METHODS = {"APP_WALLET", "CARD", "CASH"}


@bp.post("/wdf-orders")
def intake():
    user_id, role = get_identity()
    require_roles(role, {"Attendant"})
    body = get_body()
    require_fields(body, ["intake_attendant_id", "weight_lb"])
    intake_attendant_id = require_str(body["intake_attendant_id"], "intake_attendant_id")
    weight_lb = require_int(body["weight_lb"], "weight_lb", gt=0)
    member_id = body.get("member_id")
    rush = body.get("rush", False)
    if rush is None:
        rush = False
    require_bool(rush, "rush")
    with db.lock:
        member = None
        if member_id is not None:
            member = get_or_404(db.members, member_id, "Member")
        plan = require_active_plan()
        quoted = wdf_total_cents(plan, weight_lb, rush)
        # Stamp the OPEN shift active at intake (the acting attendant's shift).
        shift = open_shift_for(user_id)
        shift_id = shift["id"] if shift is not None else None
        order = {
            "member_id": member_id,
            "intake_attendant_id": intake_attendant_id,
            "shift_id": shift_id,
            "weight_lb": weight_lb,
            "rush": rush,
            "quoted_total_cents": quoted,
            "paid_amount_cents": 0,
            "pay_method": None,
            "status": "DROPPED",
        }
        stamp_create(order)
        db.wdf_orders[order["id"]] = order
    return object_response(view(order), status=201)


@bp.get("/wdf-orders")
def list_orders():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    member_id = request.args.get("member_id")
    intake_attendant_id = request.args.get("intake_attendant_id")
    shift_id = request.args.get("shift_id")
    items = list(db.wdf_orders.values())
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if member_id is not None:
        items = [o for o in items if o.get("member_id") == member_id]
    if intake_attendant_id is not None:
        items = [o for o in items if o["intake_attendant_id"] == intake_attendant_id]
    if shift_id is not None:
        items = [o for o in items if o.get("shift_id") == shift_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(o) for o in window], limit, offset, total)


@bp.get("/wdf-orders/<order_id>")
def get_order(order_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    order = get_or_404(db.wdf_orders, order_id, "WdfOrder")
    return object_response(view(order))


@bp.post("/wdf-orders/<order_id>/start")
def start_order(order_id):
    _, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        order = get_or_404(db.wdf_orders, order_id, "WdfOrder")
        if order["status"] != "DROPPED":
            raise err(ERR_INVALID_STATE, "Order is not DROPPED")
        order["status"] = "WASHING"
        touch(order)
    return object_response(view(order))


@bp.post("/wdf-orders/<order_id>/ready")
def ready_order(order_id):
    _, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        order = get_or_404(db.wdf_orders, order_id, "WdfOrder")
        if order["status"] != "WASHING":
            raise err(ERR_INVALID_STATE, "Order is not WASHING")
        order["status"] = "READY"
        touch(order)
    return object_response(view(order))


@bp.post("/wdf-orders/<order_id>/pay")
def pay_order(order_id):
    user_id, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    with db.lock:
        order = get_or_404(db.wdf_orders, order_id, "WdfOrder")
        body = get_body()
        require_fields(body, ["pay_method"])
        pay_method = body["pay_method"]
        require_enum(pay_method, PAY_METHODS, "pay_method")
        # Ownership (priority 5): a Member may pay only their own order.
        if role == "Member" and order.get("member_id") != user_id:
            raise err(ERR_FORBIDDEN, "Member may only pay their own order")
        # State (priority 6).
        if order["status"] != "READY":
            raise err(ERR_INVALID_STATE, "Order is not READY")
        paid = order["quoted_total_cents"]
        member = None
        if pay_method == "APP_WALLET":
            # Must name a member.
            if order.get("member_id") is None:
                raise err(ERR_INVALID_STATE, "APP_WALLET pay requires the order to name a member")
            member = db.members.get(order["member_id"])
            # member existence guaranteed at intake; guard anyway.
            if member is None:
                raise err(ERR_INVALID_STATE, "Order member not found")
            if member["status"] != "ACTIVE":
                raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")
            if member["wallet_cents"] < paid:
                raise err(ERR_INSUFFICIENT_WALLET, "Insufficient wallet balance")
        order["pay_method"] = pay_method
        order["paid_amount_cents"] = paid
        order["status"] = "PAID"
        touch(order)
        if pay_method == "APP_WALLET":
            member["wallet_cents"] -= paid
            touch(member)
    return object_response(view(order))


@bp.post("/wdf-orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    with db.lock:
        order = get_or_404(db.wdf_orders, order_id, "WdfOrder")
        # Ownership (priority 5).
        if role == "Member" and order.get("member_id") != user_id:
            raise err(ERR_FORBIDDEN, "Member may only cancel their own order")
        if order["status"] not in ("DROPPED", "WASHING", "READY"):
            raise err(ERR_INVALID_STATE, "Order is not cancellable")
        order["status"] = "CANCELLED"
        touch(order)
    return object_response(view(order))
