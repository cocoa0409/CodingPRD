"""CoreReturn endpoints + adjudication state machine."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    conflict,
    ERR_CORE_RETURN_NOT_PENDING,
    ERR_CORE_RETURN_LINE_NOT_SHIPPED,
    ERR_CORE_EXCEEDS_OUTSTANDING,
)
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    touch,
    serialize,
    get_order_line,
    get_core_return,
    get_sales_order,
    get_account,
)

bp = Blueprint("core_returns", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")


@bp.post("/core-returns")
def create_core_return():
    require_role("CounterClerk", "WholesaleRep", "WarrantyAdmin")
    body = get_body()
    order_line_id = c.as_nonempty_string(body, "order_line_id", required=True)
    qty = c.as_int(body, "qty", required=True, min_value=1)
    line = get_order_line(order_line_id)

    # qty must not exceed cores_outstanding (business rule at creation)
    if qty > line["cores_outstanding"]:
        raise conflict(ERR_CORE_EXCEEDS_OUTSTANDING)

    refund_cents = qty * line["unit_core_price_cents"]
    cr = {
        "order_line_id": order_line_id,
        "qty": qty,
        "refund_cents": refund_cents,
        "status": "PENDING_INSPECTION",
    }
    stamp_common(cr)
    db.core_returns[cr["id"]] = cr
    return success(serialize(cr), 201)


@bp.get("/core-returns")
def list_core_returns():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    order_line_id = request.args.get("order_line_id")
    status = request.args.get("status")
    filters = []
    if order_line_id is not None:
        filters.append(lambda r: r["order_line_id"] == order_line_id)
    if status is not None:
        filters.append(lambda r: r["status"] == status)
    page, total = c.paginate(db.core_returns.values(), limit, offset, filters)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.get("/core-returns/<cid>")
def get_one_core_return(cid):
    require_role(*ALL_ROLES)
    return success(serialize(get_core_return(cid)))


@bp.post("/core-returns/<cid>/accept")
def accept_core_return(cid):
    require_role("WarrantyAdmin")
    cr = get_core_return(cid)
    # precondition: PENDING_INSPECTION
    if cr["status"] != "PENDING_INSPECTION":
        raise conflict(ERR_CORE_RETURN_NOT_PENDING)
    line = get_order_line(cr["order_line_id"])
    # precondition: line SHIPPED
    if line["status"] != "SHIPPED":
        raise conflict(ERR_CORE_RETURN_LINE_NOT_SHIPPED)
    # precondition: qty <= cores_outstanding
    if cr["qty"] > line["cores_outstanding"]:
        raise conflict(ERR_CORE_EXCEEDS_OUTSTANDING)

    # cascade hop 1: decrement cores_outstanding on the line
    line["cores_outstanding"] -= cr["qty"]
    touch(line)
    # cascade hop 2: credit refund against the order's account (clamp 0)
    order = get_sales_order(line["order_id"])
    account = get_account(order["account_id"])
    account["ar_balance_cents"] -= cr["refund_cents"]
    if account["ar_balance_cents"] < 0:
        account["ar_balance_cents"] = 0
    touch(account)

    cr["status"] = "ACCEPTED"
    touch(cr)
    return success(serialize(cr))


@bp.post("/core-returns/<cid>/reject")
def reject_core_return(cid):
    require_role("WarrantyAdmin")
    cr = get_core_return(cid)
    if cr["status"] != "PENDING_INSPECTION":
        raise conflict(ERR_CORE_RETURN_NOT_PENDING)
    cr["status"] = "REJECTED"
    touch(cr)
    return success(serialize(cr))
