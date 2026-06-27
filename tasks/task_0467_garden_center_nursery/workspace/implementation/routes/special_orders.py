"""SpecialOrder endpoints: request, approve, receive, cancel + lists."""
from flask import Blueprint, request

import errors
from db import db, base_versioned, touch
from errors import err
from lookups import body, get_account, get_special_order
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from services import calc
from validation import req_int_gt, req_int_min

bp = Blueprint("special_orders", __name__)


def special_order_view(s):
    return {
        "id": s["id"],
        "account_id": s["account_id"],
        "nursery_id": s["nursery_id"],
        "product_id": s["product_id"],
        "requested_qty": s["requested_qty"],
        "quoted_unit_cost_cents": s["quoted_unit_cost_cents"],
        "deposit_cents": s["deposit_cents"],
        "received_lot_id": s["received_lot_id"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.post("/accounts/<account_id>/special-orders")
@require_roles("SalesClerk")
def create_special_order(account_id):
    account = get_account(account_id)
    data = body()
    product_id = data.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        err(errors.ERR_INVALID_REQUEST, "product_id required")
    requested_qty = req_int_gt(data, "requested_qty", 0)
    quoted = req_int_min(data, "quoted_unit_cost_cents", 0)

    product = db.products.get(product_id)
    if product is None or product["nursery_id"] != account["nursery_id"]:
        err(errors.ERR_PRODUCT_NOT_FOUND, "product not found in nursery")

    s = base_versioned()
    s.update({
        "account_id": account_id,
        "nursery_id": account["nursery_id"],
        "product_id": product_id,
        "requested_qty": requested_qty,
        "quoted_unit_cost_cents": quoted,
        "deposit_cents": 0,
        "received_lot_id": None,
        "status": "REQUESTED",
    })
    db.special_orders[s["id"]] = s
    return created(special_order_view(s))


@bp.get("/special-orders")
@require_roles("InventoryManager", "SalesClerk")
def list_special_orders():
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    received_lot_id = request.args.get("received_lot_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.special_orders.values())
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    if received_lot_id is not None:
        items = [s for s in items if s["received_lot_id"] == received_lot_id]
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([special_order_view(s) for s in page], limit, offset, total)


@bp.get("/special-orders/<so_id>")
@require_roles("InventoryManager", "SalesClerk")
def read_special_order(so_id):
    s = get_special_order(so_id)
    return ok(special_order_view(s))


@bp.get("/special-orders/<so_id>/inventory-lots")
@require_roles("InventoryManager", "SalesClerk")
def list_so_lots(so_id):
    get_special_order(so_id)
    limit, offset = parse_pagination()
    from routes.inventory_lots import lot_view
    items = [l for l in db.inventory_lots.values()
             if l["special_order_id"] == so_id]
    items.sort(key=lambda l: l["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([lot_view(l) for l in page], limit, offset, total)


@bp.post("/special-orders/<so_id>/approve")
@require_roles("InventoryManager")
def approve_special_order(so_id):
    s = get_special_order(so_id)
    if s["status"] != "REQUESTED":
        err(errors.ERR_SPECIAL_ORDER_NOT_REQUESTED, "special order not REQUESTED")
    s["deposit_cents"] = calc.special_order_deposit(
        s["requested_qty"], s["quoted_unit_cost_cents"])
    s["status"] = "APPROVED"
    touch(s)
    return ok(special_order_view(s))


@bp.post("/special-orders/<so_id>/receive")
@require_roles("InventoryManager")
def receive_special_order(so_id):
    s = get_special_order(so_id)
    if s["status"] != "APPROVED":
        err(errors.ERR_SPECIAL_ORDER_NOT_APPROVED, "special order not APPROVED")
    from routes.inventory_lots import mint_lot
    product = db.products[s["product_id"]]
    lot = mint_lot(product, s["requested_qty"], s["quoted_unit_cost_cents"], s["id"])
    s["received_lot_id"] = lot["id"]
    s["status"] = "RECEIVED"
    touch(s)
    return ok(special_order_view(s))


@bp.post("/special-orders/<so_id>/cancel")
@require_roles("InventoryManager", "SalesClerk")
def cancel_special_order(so_id):
    s = get_special_order(so_id)
    if s["status"] not in ("REQUESTED", "APPROVED"):
        err(errors.ERR_SPECIAL_ORDER_NOT_CANCELLABLE, "special order not cancellable")
    s["status"] = "CANCELLED"
    touch(s)
    return ok(special_order_view(s))
