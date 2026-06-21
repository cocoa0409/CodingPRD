"""PurchaseOrder endpoints + nested reverse-reachability lists (PRD §3.1, §2.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_GL_ACCOUNT_NOT_POSTABLE,
)
from middleware import auth_required, ALL_ROLES
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int,
    parse_pagination, paginate, order_by_created,
)
from routes.gl_accounts import find_gl_by_code
from services.common import new_common_fields

bp = Blueprint("purchase_orders", __name__)


@bp.post("/ap/purchase-orders")
def create_po():
    auth_required({"APManager"})()
    body = get_body()
    require_fields(body, ["vendor_id", "gl_account_code", "ordered_amount_cents"])

    vendor_id = body["vendor_id"]
    if vendor_id not in db.vendors:
        raise APIError(ERR_NOT_FOUND, 404, "Vendor not found")

    gl_account_code = body["gl_account_code"]
    if not isinstance(gl_account_code, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "gl_account_code must be a string")

    ordered = body["ordered_amount_cents"]
    if not is_int(ordered) or ordered < 1:
        raise APIError(ERR_INVALID_REQUEST, 400, "ordered_amount_cents must be an integer >= 1")

    # business_referential: gl_account_code must reference a postable GLAccount (422).
    gl = find_gl_by_code(gl_account_code)
    if gl is None or not gl["is_postable"]:
        raise APIError(ERR_GL_ACCOUNT_NOT_POSTABLE, 422,
                       "gl_account_code must reference a postable GL account")

    po = {
        **new_common_fields(),
        "vendor_id": vendor_id,
        "gl_account_code": gl_account_code,
        "ordered_amount_cents": ordered,
        "received_amount_cents": 0,
        "matched_amount_cents": 0,
        "status": "OPEN",
    }
    db.purchase_orders[po["id"]] = po
    return ok_object(serialize(po), http_status=201)


@bp.get("/ap/purchase-orders/<pid>")
def get_po(pid):
    auth_required(ALL_ROLES)()
    po = db.purchase_orders.get(pid)
    if po is None:
        raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")
    return ok_object(serialize(po))


@bp.get("/ap/purchase-orders")
def list_pos():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    vendor_id = request.args.get("vendor_id")
    items = [p for p in db.purchase_orders.values()
             if vendor_id is None or p["vendor_id"] == vendor_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


def _require_po(pid):
    po = db.purchase_orders.get(pid)
    if po is None:
        raise APIError(ERR_NOT_FOUND, 404, "Purchase order not found")
    return po


@bp.get("/ap/purchase-orders/<pid>/goods-receipts")
def list_po_goods_receipts(pid):
    auth_required(ALL_ROLES)()
    _require_po(pid)
    limit, offset = parse_pagination()
    items = [gr for gr in db.goods_receipts.values() if gr["po_id"] == pid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.get("/ap/purchase-orders/<pid>/accruals")
def list_po_accruals(pid):
    auth_required(ALL_ROLES)()
    _require_po(pid)
    limit, offset = parse_pagination()
    items = [a for a in db.accruals.values() if a["po_id"] == pid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.get("/ap/purchase-orders/<pid>/invoices")
def list_po_invoices(pid):
    auth_required(ALL_ROLES)()
    _require_po(pid)
    limit, offset = parse_pagination()
    items = [inv for inv in db.invoices.values() if inv["po_id"] == pid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
