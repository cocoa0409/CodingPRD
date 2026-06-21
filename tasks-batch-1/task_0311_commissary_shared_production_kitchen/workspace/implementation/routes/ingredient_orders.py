"""Ingredient replenishment orders: place, receive (restock), cancel."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, get_or_404, sorted_by_creation,
    paginate, require_fields, as_int, as_number,
)

bp = Blueprint("ingredient_orders", __name__)


def _load_member_order(member_id, order_id):
    find_member(member_id)
    order = get_or_404(db.ingredient_orders, order_id)
    if order["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return order


@bp.post("/members/<member_id>/ingredient-orders")
def create_order(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        require_fields(body, ["ingredient_id", "order_qty", "unit_cost_cents"])
        ingredient = get_or_404(db.ingredients, body["ingredient_id"])
        order_qty = as_number(body["order_qty"])
        unit_cost = as_int(body["unit_cost_cents"])

        if member["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_NOT_ACTIVE")
        if order_qty <= 0:
            raise ApiError("ERR_INVALID_REQUEST")
        if unit_cost < 0:
            raise ApiError("ERR_INVALID_REQUEST")

        order = {
            "member_id": member_id,
            "ingredient_id": ingredient["id"],
            "order_qty": order_qty,
            "unit_cost_cents": unit_cost,
            "status": "PLACED",
        }
        stamp_new(order)
        db.ingredient_orders[order["id"]] = order
        return success(public(order), 201)


@bp.get("/members/<member_id>/ingredient-orders")
def list_member_orders(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    ingredient_id = request.args.get("ingredient_id")
    with LOCK:
        find_member(member_id)
        records = [o for o in db.ingredient_orders.values() if o["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [o for o in records if o["status"] == status]
        if ingredient_id:
            records = [o for o in records if o["ingredient_id"] == ingredient_id]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.post("/members/<member_id>/ingredient-orders/<order_id>/receive")
def receive_order(member_id, order_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        order = _load_member_order(member_id, order_id)
        if order["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE")
        ingredient = db.ingredients[order["ingredient_id"]]
        ingredient["on_hand_qty"] = _add_qty(ingredient["on_hand_qty"], order["order_qty"])
        ingredient["unit_cost_cents"] = order["unit_cost_cents"]
        touch(ingredient)
        order["status"] = "RECEIVED"
        touch(order)
        return success(public(order))


def _add_qty(current, delta):
    total = current + delta
    if isinstance(total, float) and total.is_integer():
        return int(total)
    return total


@bp.post("/members/<member_id>/ingredient-orders/<order_id>/cancel")
def cancel_order(member_id, order_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        order = _load_member_order(member_id, order_id)
        if order["status"] != "PLACED":
            raise ApiError("ERR_INVALID_STATE")
        order["status"] = "CANCELLED"
        touch(order)
        return success(public(order))
