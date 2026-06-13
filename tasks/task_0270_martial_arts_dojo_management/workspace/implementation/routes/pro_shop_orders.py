"""Pro-shop orders (PRD §2.8, §3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_UNAUTHORIZED,
)
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_MEMBER,
)
from response import success
from common import (
    get_json_body, require_fields, parse_pagination, paginate, sort_by_created,
)
from services.serialize import view, view_list
from services import domain

bp = Blueprint("pro_shop_orders", __name__)


def _validate_line_items(line_items):
    """ERR_VALIDATION on empty array or bad qty/price (PRD §3.7)."""
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise err(ERR_VALIDATION, "line_items must be a non-empty array.")
    clean = []
    for li in line_items:
        if not isinstance(li, dict):
            raise err(ERR_VALIDATION, "each line item must be an object.")
        sku = li.get("sku")
        unit_price = li.get("unit_price_cents")
        qty = li.get("qty")
        if (not isinstance(unit_price, int) or isinstance(unit_price, bool)
                or unit_price < 0):
            raise err(ERR_VALIDATION, "unit_price_cents must be a non-negative integer.")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise err(ERR_VALIDATION, "qty must be an integer >= 1.")
        clean.append({"sku": sku, "unit_price_cents": unit_price, "qty": qty})
    return clean


@bp.post("/dojo/pro-shop-orders")
def create_order():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    body = get_json_body()
    require_fields(body, ["member_id", "line_items"])

    # FK existence (priority 4)
    member = db.members.get(body["member_id"])
    if member is None:
        raise err(ERR_FK_NOT_FOUND, "member_id references a non-existent member.")
    if role == ROLE_MEMBER and body["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only order for themselves.")

    line_items = _validate_line_items(body["line_items"])
    gross, net = domain.compute_pro_shop_amounts(body["member_id"], line_items)

    now = db.now_iso()
    oid = db.new_id()
    order = {
        "id": oid,
        "member_id": body["member_id"],
        "line_items": line_items,
        "gross_cents": gross,
        "net_cents": net,
        "status": "PLACED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.pro_shop_orders[oid] = order
    return success(view(order), 201)


@bp.get("/dojo/pro-shop-orders/<oid>")
def get_order(oid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    order = db.pro_shop_orders.get(oid)
    if order is None:
        raise err(ERR_NOT_FOUND, "Pro-shop order not found.")
    if role == ROLE_MEMBER and order["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only read their own orders.")
    return success(view(order), 200)


@bp.get("/dojo/pro-shop-orders")
def list_orders():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = []
    for o in db.pro_shop_orders.values():
        if role == ROLE_MEMBER and o["member_id"] != user_id:
            continue
        if member_id is not None and o["member_id"] != member_id:
            continue
        if status is not None and o["status"] != status:
            continue
        items.append(o)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/pro-shop-orders/<oid>/fulfill")
def fulfill_order(oid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    order = db.pro_shop_orders.get(oid)
    if order is None:
        raise err(ERR_NOT_FOUND, "Pro-shop order not found.")
    if order["status"] != "PLACED":
        raise err(ERR_INVALID_STATE, "Pro-shop order not in PLACED state.")
    order["status"] = "FULFILLED"
    domain.touch(order)
    domain.make_invoice(order["member_id"], "PRO_SHOP", order["net_cents"], contract_id=None)
    domain.recompute_member_balance(order["member_id"])
    return success(view(order), 200)


@bp.post("/dojo/pro-shop-orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_MEMBER, ROLE_FRONTDESK])
    order = db.pro_shop_orders.get(oid)
    if order is None:
        raise err(ERR_NOT_FOUND, "Pro-shop order not found.")
    if role == ROLE_MEMBER and order["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only cancel their own orders.")
    if order["status"] != "PLACED":
        raise err(ERR_INVALID_STATE, "Pro-shop order not in PLACED state.")
    order["status"] = "CANCELLED"
    domain.touch(order)
    return success(view(order), 200)
