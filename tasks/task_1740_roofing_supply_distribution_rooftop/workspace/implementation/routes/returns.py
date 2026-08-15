"""Returns of opened bundles under color/lot discipline (PRD 3.8, 2.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_RETURN_NOT_FOUND,
    ERR_RETURN_NOT_REQUESTED,
    ERR_RETURN_NOT_APPROVED,
    ERR_RETURN_QUANTITY_EXCEEDED,
    ERR_LOT_MISMATCH,
    ERR_INVALID_REQUEST,
)
from middleware import authorized, check_contractor_owns
from routes.helpers import body, body_field, render_list, render_one, require_int
from services.core import create_record, get_or_404, mutate
from services.calculations import return_credit

bp = Blueprint("returns", __name__)

RETURN_READ_ROLES = ["PlatformAdmin", "BranchManager", "WarehouseClerk", "Contractor"]


def _order_or_404(rid):
    return get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)


def _return_or_404(rid):
    return get_or_404("returns", rid, ERR_RETURN_NOT_FOUND)


def _own_order_check(caller, order):
    job = db["job_accounts"].get(order["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)


@bp.post("/roofing/orders/<rid>/returns")
def request_return(rid):
    caller = authorized(["Contractor"])
    order = _order_or_404(rid)
    _own_order_check(caller, order)
    data = body()
    order_line_id = body_field(data, "order_line_id", required=True)
    line = db["order_lines"].get(order_line_id)
    if line is None or line["order_id"] != order["id"]:
        raise_error(ERR_ORDER_LINE_NOT_FOUND,
                    "order_line_id does not identify a line on this order")
    quantity = require_int(body_field(data, "quantity_bundles", required=True),
                           "quantity_bundles", minimum=1)
    opened = require_int(data.get("opened_bundles", 0), "opened_bundles", minimum=0)
    if opened > quantity:
        raise_error(ERR_INVALID_REQUEST, "opened_bundles must be <= quantity_bundles")
    rec = create_record("returns", {
        "order_id": order["id"],
        "order_line_id": line["id"],
        "quantity_bundles": quantity,
        "opened_bundles": opened,
        "lot_match_verified": False,
        "credit_amount_cents": 0,
        "restocking_fee_cents": 0,
        "status": "REQUESTED",
    })
    return render_one("returns", rec, status=201)


@bp.get("/roofing/orders/<rid>/returns")
def list_order_returns(rid):
    caller = authorized(RETURN_READ_ROLES)
    order = _order_or_404(rid)
    _own_order_check(caller, order)
    returns = [r for r in db["returns"].values() if r["order_id"] == order["id"]]
    return render_list(caller, "returns", base_records=returns)


@bp.get("/roofing/returns")
def list_returns():
    caller = authorized(RETURN_READ_ROLES)
    return render_list(caller, "returns",
                       filters={"order_line_id": request.args.get("order_line_id"),
                                "order_id": request.args.get("order_id"),
                                "status": request.args.get("status")})


@bp.get("/roofing/returns/<rid>")
def get_return(rid):
    caller = authorized(RETURN_READ_ROLES)
    rec = _return_or_404(rid)
    order = db["orders"].get(rec["order_id"])
    if order is not None:
        _own_order_check(caller, order)
    return render_one("returns", rec)


@bp.post("/roofing/returns/<rid>/approve")
def approve_return(rid):
    authorized(["BranchManager"])
    rec = _return_or_404(rid)
    if rec["status"] != "REQUESTED":
        raise_error(ERR_RETURN_NOT_REQUESTED, "approve requires the return to be REQUESTED")
    line = db["order_lines"].get(rec["order_line_id"])
    delivered = line["delivered_bundles"] if line else 0
    already_returned = line["returned_bundles"] if line else 0
    if rec["quantity_bundles"] + already_returned > delivered:
        raise_error(ERR_RETURN_QUANTITY_EXCEEDED,
                    "return quantity exceeds delivered minus already-returned bundles")
    unit_price = line["unit_price_cents"] if line else 0
    credit, restocking = return_credit(unit_price, rec["quantity_bundles"], rec["opened_bundles"])
    rec["credit_amount_cents"] = credit
    rec["restocking_fee_cents"] = restocking
    rec["status"] = "APPROVED"
    mutate(rec)
    return render_one("returns", rec)


@bp.post("/roofing/returns/<rid>/receive")
def receive_return(rid):
    authorized(["WarehouseClerk"])
    rec = _return_or_404(rid)
    if rec["status"] != "APPROVED":
        raise_error(ERR_RETURN_NOT_APPROVED, "receive requires the return to be APPROVED")
    line = db["order_lines"].get(rec["order_line_id"])
    lot = db["inventory_lots"].get(line["inventory_lot_id"]) if line else None
    data = body()
    returned_lot_code = body_field(data, "returned_lot_code", required=True)
    if lot is None or returned_lot_code != lot["lot_code"]:
        raise_error(ERR_LOT_MISMATCH,
                    "returned lot_code does not match the line's reserved lot")
    rec["lot_match_verified"] = True
    rec["status"] = "RECEIVED"
    # Unopened bundles restock; opened ones do not (PRD 3.8).
    lot["on_hand_bundles"] += (rec["quantity_bundles"] - rec["opened_bundles"])
    mutate(lot)
    line["returned_bundles"] += rec["quantity_bundles"]
    mutate(line)
    order = db["orders"].get(rec["order_id"])
    if order is not None:
        order["fulfillment_status"] = "RETURN_ADJUSTED"
        mutate(order)
        job = db["job_accounts"].get(order["job_account_id"])
        account = db["contractor_accounts"].get(job["contractor_account_id"]) if job else None
        if account is not None:
            if order["payment_status"] in ("INVOICED", "PAID"):
                account["open_balance_cents"] = max(
                    0, account["open_balance_cents"] - rec["credit_amount_cents"])
            else:
                account["pending_delivery_hold_cents"] = max(
                    0, account["pending_delivery_hold_cents"] - rec["credit_amount_cents"])
            mutate(account)
    mutate(rec)
    return render_one("returns", rec)


@bp.post("/roofing/returns/<rid>/reject")
def reject_return(rid):
    authorized(["BranchManager"])
    rec = _return_or_404(rid)
    if rec["status"] != "REQUESTED":
        raise_error(ERR_RETURN_NOT_REQUESTED, "reject requires the return to be REQUESTED")
    rec["status"] = "REJECTED"
    mutate(rec)
    return render_one("returns", rec)
