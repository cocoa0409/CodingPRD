"""BundleReturn endpoints."""
from datetime import datetime, timezone
from flask import Blueprint, request
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_OVER_RETURN,
    ERR_RATED_NON_RETURNABLE, ERR_ORDER_NOT_STOCKED, ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int,
    new_common_fields, touch,
)
from services.calc import restock_fee_and_credit, RATED_KINDS

bp = Blueprint("returns", __name__)


def _get_return_or_404(rid):
    r = db.bundle_returns.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, "BundleReturn not found", 404)
    return r


def _delivered_qty(order_id, product_id):
    """Delivered (bundles, loose) for a product on an order.

    Drops only carry whole bundles; loose delivered is always 0.
    Returns total sheets delivered.
    """
    total_bundles = 0
    for d in db.stocking_drops.values():
        if d["stocking_order_id"] == order_id and d["product_id"] == product_id:
            total_bundles += d["bundle_count"]
    product = db.products.get(product_id)
    spb = product["sheets_per_bundle"] if product else 0
    return total_bundles * spb  # total sheets delivered


def _accepted_returned_sheets(order_id, product_id):
    total = 0
    for r in db.bundle_returns.values():
        if (
            r["stocking_order_id"] == order_id
            and r["product_id"] == product_id
            and r["status"] == "ACCEPTED"
        ):
            product = db.products.get(product_id)
            spb = product["sheets_per_bundle"] if product else 0
            total += r["bundles_returned"] * spb + r["loose_sheets_returned"]
    return total


@bp.route("/supply/bundle-returns", methods=["POST"])
def create_return():
    require_roles("WarehouseManager")
    b = body()
    require_fields(b, "stocking_order_id", "product_id", "bundles_returned", "loose_sheets_returned")
    order_id = b["stocking_order_id"]
    product_id = b["product_id"]
    if not isinstance(order_id, str):
        raise ApiError(ERR_NOT_FOUND, "StockingOrder not found", 404)
    order = db.stocking_orders.get(order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, "StockingOrder not found", 404)
    if not isinstance(product_id, str):
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    bundles_returned = require_int(b, "bundles_returned", min_val=0)
    loose_sheets_returned = require_int(b, "loose_sheets_returned", min_val=0)
    if loose_sheets_returned >= product["sheets_per_bundle"]:
        raise ApiError(
            ERR_VALIDATION,
            "loose_sheets_returned must be < sheets_per_bundle",
            400,
        )
    # PRD 2.8: rated-non-returnable evaluated BEFORE over-return
    if product["board_kind"] in RATED_KINDS:
        raise ApiError(ERR_RATED_NON_RETURNABLE, "Rated board is not returnable", 422)
    # Over-return check (count pending + accepted? PRD says "previously ACCEPTED + this request")
    spb = product["sheets_per_bundle"]
    delivered_sheets = _delivered_qty(order_id, product_id)
    already_returned = _accepted_returned_sheets(order_id, product_id)
    this_return = bundles_returned * spb + loose_sheets_returned
    if already_returned + this_return > delivered_sheets:
        raise ApiError(ERR_OVER_RETURN, "Cumulative returns exceed delivered quantity", 422)

    r = new_common_fields()
    r.update({
        "stocking_order_id": order_id,
        "product_id": product_id,
        "bundles_returned": bundles_returned,
        "loose_sheets_returned": loose_sheets_returned,
        "restock_fee_cents": 0,
        "credit_cents": 0,
        "status": "PENDING_INSPECTION",
    })
    db.bundle_returns[r["id"]] = r
    return success(r, status=201)


@bp.route("/supply/bundle-returns/<rid>", methods=["GET"])
def get_return(rid):
    require_roles("WarehouseManager", "CreditManager", "AccountsReceivableUser")
    return success(_get_return_or_404(rid))


@bp.route("/supply/bundle-returns", methods=["GET"])
def list_returns():
    require_roles("WarehouseManager", "CreditManager", "AccountsReceivableUser")
    limit, offset = parse_pagination()
    order_id = request.args.get("stocking_order_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = list(db.bundle_returns.values())
    if order_id is not None:
        items = [r for r in items if r["stocking_order_id"] == order_id]
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/bundle-returns/<rid>/accept", methods=["POST"])
def accept_return(rid):
    require_roles("WarehouseManager")
    r = _get_return_or_404(rid)
    if r["status"] != "PENDING_INSPECTION":
        raise ApiError(ERR_INVALID_STATE, "Return is not in PENDING_INSPECTION", 409)
    order = db.stocking_orders.get(r["stocking_order_id"])
    if order is None:
        raise ApiError(ERR_NOT_FOUND, "StockingOrder not found", 404)
    if order["status"] != "STOCKED":
        raise ApiError(ERR_ORDER_NOT_STOCKED, "Source order must be STOCKED", 409)
    product = db.products.get(r["product_id"])
    if product is None:
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    if product["board_kind"] in RATED_KINDS:
        raise ApiError(ERR_RATED_NON_RETURNABLE, "Rated board is not returnable", 422)
    spb = product["sheets_per_bundle"]
    delivered = _delivered_qty(r["stocking_order_id"], r["product_id"])
    already = _accepted_returned_sheets(r["stocking_order_id"], r["product_id"])
    this_return = r["bundles_returned"] * spb + r["loose_sheets_returned"]
    if already + this_return > delivered:
        raise ApiError(ERR_OVER_RETURN, "Cumulative returns exceed delivered quantity", 422)

    # Compute money
    material_value = (r["bundles_returned"] * spb + r["loose_sheets_returned"]) * product["unit_price_cents_per_sheet"]
    # days since stocked (floor of elapsed days)
    stocked_at_str = order.get("stocked_at")
    days_since = 0
    if stocked_at_str:
        s = stocked_at_str
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            stocked_dt = datetime.fromisoformat(s)
            if stocked_dt.tzinfo is None:
                stocked_dt = stocked_dt.replace(tzinfo=timezone.utc)
            delta = db.clock.now() - stocked_dt
            days_since = int(delta.total_seconds() // 86400)
        except Exception:
            days_since = 0
    fee, credit = restock_fee_and_credit(material_value, days_since, r["loose_sheets_returned"])
    r["restock_fee_cents"] = fee
    r["credit_cents"] = credit
    r["status"] = "ACCEPTED"
    touch(r)

    # Apply credit to account AR (floor 0)
    project = db.projects.get(order["project_id"])
    if project:
        account = db.contractor_accounts.get(project["account_id"])
        if account:
            new_ar = account["ar_outstanding_cents"] - credit
            if new_ar < 0:
                new_ar = 0
            account["ar_outstanding_cents"] = new_ar
            touch(account)

    return success(r)


@bp.route("/supply/bundle-returns/<rid>/reject", methods=["POST"])
def reject_return(rid):
    require_roles("WarehouseManager")
    r = _get_return_or_404(rid)
    if r["status"] != "PENDING_INSPECTION":
        raise ApiError(ERR_INVALID_STATE, "Return is not in PENDING_INSPECTION", 409)
    r["status"] = "REJECTED"
    touch(r)
    return success(r)
