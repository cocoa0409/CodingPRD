"""Point mall items + redemption orders."""
from flask import Blueprint, g, request

import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INSUFFICIENT_POINTS,
    ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    err,
)
from middleware import auth_required
from pagination import parse_pagination, slice_sorted
from response import list_response, success
from services.occ import check_occ
from validators import as_int, as_str, opt_field, require_field
from views import view_point_mall_item, view_redemption_order


bp = Blueprint("point_mall", __name__)


@bp.post("/point-mall-items")
@auth_required(["SkillAdmin"])
def create_item():
    body = request.get_json(silent=True) or {}
    sku = as_str(require_field(body, "sku"), "sku", 2, 40)
    name = as_str(require_field(body, "name"), "name", 1)
    point_cost = as_int(require_field(body, "point_cost"), "point_cost", 1, 100000)
    stock = as_int(require_field(body, "stock"), "stock", 0)

    with db.lock():
        for it in db.point_mall_items.values():
            if it["sku"] == sku:
                raise err(ERR_INVALID_INPUT, "sku already exists")
        row = {
            "sku": sku,
            "name": name,
            "point_cost": point_cost,
            "stock": stock,
            "status": "ACTIVE",
        }
        db.init_common(row)
        db.point_mall_items[row["id"]] = row
    return success(view_point_mall_item(row), status_code=201)


@bp.post("/point-mall-items/<iid>/restock")
@auth_required(["SkillAdmin"])
def restock(iid):
    item = db.point_mall_items.get(iid)
    if not item:
        raise err(ERR_NOT_FOUND, "item not found")
    body = request.get_json(silent=True) or {}
    check_occ(item, body)
    delta = require_field(body, "delta")
    delta = as_int(delta, "delta")
    if delta <= 0:
        raise err(ERR_INVALID_INPUT, "delta must be positive")
    with db.lock():
        if item["status"] == "ARCHIVED":
            raise err(ERR_INVALID_STATE, "cannot restock ARCHIVED item")
        item["stock"] = int(item.get("stock", 0)) + delta
        item["status"] = "ACTIVE"
        db.touch(item)
    return success(view_point_mall_item(item))


@bp.post("/point-mall-items/<iid>/archive")
@auth_required(["SkillAdmin"])
def archive_item(iid):
    item = db.point_mall_items.get(iid)
    if not item:
        raise err(ERR_NOT_FOUND, "item not found")
    body = request.get_json(silent=True) or {}
    check_occ(item, body)
    with db.lock():
        if item["status"] not in {"ACTIVE", "OUT_OF_STOCK"}:
            raise err(ERR_INVALID_STATE, "cannot archive in current state")
        item["status"] = "ARCHIVED"
        db.touch(item)
    return success(view_point_mall_item(item))


@bp.get("/point-mall-items")
@auth_required(["Volunteer", "SkillAdmin"])
def list_items():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    rows = list(db.point_mall_items.values())
    if status:
        rows = [r for r in rows if r.get("status") == status]
    page, total = slice_sorted(rows, limit, offset)
    return list_response([view_point_mall_item(r) for r in page], limit, offset, total)


@bp.post("/redemption-orders")
@auth_required(["Volunteer"])
def create_redemption():
    body = request.get_json(silent=True) or {}
    item_id = as_str(require_field(body, "item_id"), "item_id", 1)
    quantity = as_int(require_field(body, "quantity"), "quantity", 1, 10)
    item = db.point_mall_items.get(item_id)
    if not item:
        raise err(ERR_NOT_FOUND, "item not found")
    vol = db.volunteers.get(g.user_id)
    if not vol:
        raise err(ERR_FORBIDDEN, "acting volunteer not found")

    with db.lock():
        if item["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "item not ACTIVE")
        if int(item.get("stock", 0)) < quantity:
            raise err(ERR_INSUFFICIENT_STOCK, "stock too low")
        total_points = int(item["point_cost"]) * quantity
        if int(vol.get("points_balance", 0)) < total_points:
            raise err(ERR_INSUFFICIENT_POINTS, "points balance too low")

        row = {
            "volunteer_id": g.user_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_points": total_points,
            "status": "PENDING",
        }
        db.init_common(row)
        db.redemption_orders[row["id"]] = row
    return success(view_redemption_order(row), status_code=201)


@bp.post("/redemption-orders/<oid>/fulfill")
@auth_required(["SkillAdmin"])
def fulfill_redemption(oid):
    order = db.redemption_orders.get(oid)
    if not order:
        raise err(ERR_NOT_FOUND, "order not found")
    body = request.get_json(silent=True) or {}
    check_occ(order, body)

    with db.lock():
        if order["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "order not PENDING")
        item = db.point_mall_items.get(order["item_id"])
        if not item:
            raise err(ERR_NOT_FOUND, "item not found")
        vol = db.volunteers.get(order["volunteer_id"])
        if not vol:
            raise err(ERR_NOT_FOUND, "volunteer not found")
        # PRD §2.9 race contract: when a concurrent fulfillment drives stock to
        # zero and cascades the parent item from ACTIVE to OUT_OF_STOCK, the
        # loser of the race must receive ERR_INSUFFICIENT_STOCK (not the
        # generic ERR_INVALID_STATE for item-not-ACTIVE). Checking stock
        # before the ACTIVE-status guard preserves that race outcome.
        if int(item.get("stock", 0)) < order["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "stock too low")
        if item["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "item not ACTIVE")
        if int(vol.get("points_balance", 0)) < order["total_points"]:
            raise err(ERR_INSUFFICIENT_POINTS, "points balance too low")

        # Apply atomic decrements
        item["stock"] = int(item["stock"]) - order["quantity"]
        vol["points_balance"] = int(vol["points_balance"]) - order["total_points"]
        # FIFO consume from per-application unspent points ledger
        _fifo_consume_points(vol["id"], order["total_points"])

        order["status"] = "FULFILLED"

        if item["stock"] == 0 and item["status"] == "ACTIVE":
            item["status"] = "OUT_OF_STOCK"
        db.touch(item)
        db.touch(vol)
        db.touch(order)
    return success(view_redemption_order(order))


@bp.post("/redemption-orders/<oid>/cancel")
@auth_required(["Volunteer"])
def cancel_redemption(oid):
    order = db.redemption_orders.get(oid)
    if not order:
        raise err(ERR_NOT_FOUND, "order not found")
    if order["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(order, body)
    with db.lock():
        if order["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "order not PENDING")
        order["status"] = "CANCELLED"
        db.touch(order)
    return success(view_redemption_order(order))


def _fifo_consume_points(volunteer_id: str, amount: int) -> None:
    """Consume `amount` unspent points from the volunteer's COMPLETED applications,
    oldest check_out_at first; tie-break by smaller application id."""
    if amount <= 0:
        return
    apps = [a for a in db.applications.values()
            if a["volunteer_id"] == volunteer_id and a["status"] == "COMPLETED"
            and db.application_points_ledger.get(a["id"], 0) > 0]
    apps.sort(key=lambda a: (a.get("check_out_at") or "", a["id"]))
    remaining = amount
    for a in apps:
        if remaining <= 0:
            break
        avail = db.application_points_ledger.get(a["id"], 0)
        take = min(avail, remaining)
        db.application_points_ledger[a["id"]] = avail - take
        remaining -= take
