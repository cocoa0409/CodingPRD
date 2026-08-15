"""ShortDateCredit endpoints (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ORDER_LINE_INVALID_STATE,
    ERR_LOT_LINE_MISMATCH,
    ERR_NOT_SHORT_DATED,
    ERR_CREDIT_INVALID_STATE,
    ERR_RECEIVED_QTY_EXCEEDS_CLAIMED,
)
from middleware import authorized, check_ownership
from response import success_object, success_list
from services.calculations import short_date_rate, per_unit_credit_cents
from services.core import (
    get_body, require_fields, public, get_or_404, paginate,
)
from util import CLOCK, new_id, now_ts, touch

bp = Blueprint("credits", __name__)

READ_ROLES = ["AccountManager", "ClinicBuyer", "ComplianceOfficer"]
SHORT_DATE_WINDOW_DAYS = 180


@bp.route("/vet/short-date-credits", methods=["POST"])
def create_credit():
    caller = authorized(["ClinicBuyer"])
    body = get_body()
    require_fields(body, ["order_line_id", "lot_id", "qty"])
    # Existence left-to-right: order line, then lot.
    line = get_or_404("order_lines", body["order_line_id"])
    lot = get_or_404("inventory_lots", body["lot_id"])
    order = get_or_404("orders", line["order_id"])
    # Ownership on the derived clinic.
    check_ownership(caller, order["clinic_id"])

    qty = body.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise_error(ERR_INVALID_REQUEST, "qty must be an integer")

    # The line must be DELIVERED.
    if line["status"] != "DELIVERED":
        raise_error(ERR_ORDER_LINE_INVALID_STATE,
                    f"order line must be DELIVERED (is {line['status']})")
    # The named lot must be the very lot that covered the line.
    if line["lot_id"] != lot["id"]:
        raise_error(ERR_LOT_LINE_MISMATCH,
                    "lot_id does not equal the order line's allocated lot_id")
    # Quantity in 1..qty_requested.
    if qty < 1 or qty > line["qty_requested"]:
        raise_error(ERR_INVALID_REQUEST,
                    "qty must be between 1 and the line's qty_requested")

    # Eligibility: days_to_expiry_at_request <= 180 (equality eligible).
    days = (lot["expiry_date"] - CLOCK.today()).days
    rate = short_date_rate(days)
    if rate is None:
        raise_error(ERR_NOT_SHORT_DATED,
                    "days_to_expiry_at_request exceeds 180")

    claimed = per_unit_credit_cents(line["unit_price_cents"], rate) * qty

    credit = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "clinic_id": order["clinic_id"],
        "order_line_id": line["id"],
        "lot_id": lot["id"],
        "qty": qty,
        "days_to_expiry_at_request": days,
        "claimed_credit_cents": claimed,
        "final_credit_cents": None,
        "received_qty": None,
        "status": "REQUESTED",
        "approved_on": None,
    }
    db["short_date_credits"][credit["id"]] = credit
    return success_object(public(credit), status=201)


@bp.route("/vet/short-date-credits", methods=["GET"])
def list_credits():
    authorized(READ_ROLES)
    items = list(db["short_date_credits"].values())
    for param in ("clinic_id", "order_line_id", "lot_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if str(c.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([public(c) for c in page], total, limit, offset)


@bp.route("/vet/short-date-credits/<cid>", methods=["GET"])
def get_credit(cid):
    authorized(READ_ROLES)
    credit = get_or_404("short_date_credits", cid)
    return success_object(public(credit))


@bp.route("/vet/short-date-credits/<cid>/approve", methods=["POST"])
def approve_credit(cid):
    authorized(["ComplianceOfficer"])
    credit = get_or_404("short_date_credits", cid)
    if credit["status"] != "REQUESTED":
        raise_error(ERR_CREDIT_INVALID_STATE,
                    f"credit must be REQUESTED (is {credit['status']})")
    credit["status"] = "APPROVED"
    credit["approved_on"] = CLOCK.today()
    touch(credit)
    return success_object(public(credit))


@bp.route("/vet/short-date-credits/<cid>/deny", methods=["POST"])
def deny_credit(cid):
    authorized(["ComplianceOfficer"])
    credit = get_or_404("short_date_credits", cid)
    if credit["status"] != "REQUESTED":
        raise_error(ERR_CREDIT_INVALID_STATE,
                    f"credit must be REQUESTED (is {credit['status']})")
    credit["status"] = "DENIED"
    touch(credit)
    return success_object(public(credit))


@bp.route("/vet/short-date-credits/<cid>/finalize", methods=["POST"])
def finalize_credit(cid):
    authorized(["ComplianceOfficer"])
    credit = get_or_404("short_date_credits", cid)
    if credit["status"] != "APPROVED":
        raise_error(ERR_CREDIT_INVALID_STATE,
                    f"credit must be APPROVED (is {credit['status']})")
    body = get_body()
    require_fields(body, ["received_qty"])
    received_qty = body["received_qty"]
    if isinstance(received_qty, bool) or not isinstance(received_qty, int):
        raise_error(ERR_INVALID_REQUEST, "received_qty must be an integer")
    if received_qty < 1 or received_qty > credit["qty"]:
        raise_error(ERR_RECEIVED_QTY_EXCEEDS_CLAIMED,
                    "received_qty must be between 1 and the claimed qty")

    line = get_or_404("order_lines", credit["order_line_id"])
    lot = get_or_404("inventory_lots", credit["lot_id"])
    # Final variant: tier re-evaluated at the receipt clock date.
    days_rec = (lot["expiry_date"] - CLOCK.today()).days
    rate = short_date_rate(days_rec)
    if rate is None:
        # Receipt beyond the short-date window: no credit rate applies.
        raise_error(ERR_NOT_SHORT_DATED,
                    "days to expiry at receipt exceeds 180")
    credit["final_credit_cents"] = (
        per_unit_credit_cents(line["unit_price_cents"], rate) * received_qty)
    credit["received_qty"] = received_qty
    credit["status"] = "CREDITED"
    touch(credit)
    return success_object(public(credit))
