"""Backorder request endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_BACKORDER_NOT_OPEN, ERR_LOT_EMPTY,
    ERR_STALE_LOT_VERSION,
)
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import STAFF_ROLES, get_one, list_response, public
from services import lot_available, reserve_bucket_for_channel, touch
from validate import get_body, req_str, require_path_resource, require_ref

bp = Blueprint("backorders", __name__)


@bp.get("/pool-supply/backorder-requests")
def list_backorders():
    filters = {
        "branch_id": request.args.get("branch_id"),
        "product_id": request.args.get("product_id"),
        "account_id": request.args.get("account_id"),
        "status": request.args.get("status"),
        "order_line_id": request.args.get("order_line_id"),
        "superseded_by_id": request.args.get("superseded_by_id"),
    }
    return list_response("backorder_requests", STAFF_ROLES, filters)


@bp.get("/pool-supply/backorder-requests/<rid>")
def get_backorder(rid):
    return get_one("backorder_requests", rid, STAFF_ROLES)


@bp.post("/pool-supply/backorder-requests/<rid>/allocate")
def allocate_backorder(rid):
    caller = get_caller()
    require_roles(caller, ["WarehouseLead", "BranchManager"])
    bo = require_path_resource("backorder_requests", rid)
    body = get_body()
    lot_id = req_str(body, "lot_id")
    lot = require_ref("stock_lots", lot_id, "lot_id")
    # state (priority 5) before OCC, OCC before the business qty check (PRD 2.8)
    if bo["status"] != "OPEN":
        raise_error(ERR_BACKORDER_NOT_OPEN, "allocate requires an OPEN backorder")
    if "expected_stock_lot_version" not in body or body["expected_stock_lot_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "expected_stock_lot_version is required")
    elv = body["expected_stock_lot_version"]
    if isinstance(elv, bool) or not isinstance(elv, int):
        raise_error(ERR_INVALID_REQUEST, "expected_stock_lot_version must be an integer")
    if elv != lot["version"]:
        raise_error(ERR_STALE_LOT_VERSION, "stale lot version; re-read and retry")
    if lot["product_id"] != bo["product_id"] or lot["branch_id"] != bo["branch_id"]:
        raise_error(ERR_INVALID_REQUEST, "lot does not match the backorder's product/branch")
    available = lot_available(lot)
    if available < 1:
        raise_error(ERR_LOT_EMPTY, "lot has no available units")
    grant = min(bo["qty_open"], available)
    line = db["order_lines"][bo["order_line_id"]]
    order = db["orders"][line["order_id"]]
    lot[reserve_bucket_for_channel(order["channel"])] += grant
    bo["qty_open"] -= grant
    bo["_reservation_lot_id"] = lot["id"]
    bo["_granted_units"] = bo.get("_granted_units", 0) + grant
    bo["status"] = "CLOSED" if bo["qty_open"] == 0 else "ALLOCATED"
    touch(bo)
    touch(lot)  # manual allocation increments the lot version
    return success_object(public(bo))


@bp.post("/pool-supply/backorder-requests/<rid>/cancel")
def cancel_backorder(rid):
    caller = get_caller()
    require_roles(caller, ["BranchManager"])
    bo = require_path_resource("backorder_requests", rid)
    if bo["status"] != "OPEN":
        raise_error(ERR_BACKORDER_NOT_OPEN, "cancel requires an OPEN backorder")
    bo["status"] = "CANCELLED"
    touch(bo)
    return success_object(public(bo))
