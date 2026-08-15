"""Refund endpoints (PRD 3.7): list per reservation; APPROVE / PAY / DENY pipeline."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_REFUND_POLICY_VIOLATION,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object, success_list
from services.core import touch, public_refund, sort_created
from util import CLOCK
from validate import (
    get_body, req_str, req_int, req_enum, require_path_resource, get_pagination,
)

bp = Blueprint("refunds", __name__, url_prefix="/v1")


@bp.get("/reservations/<reservation_id>/refunds")
def list_refunds(reservation_id):
    authorized(ALL_READ_ROLES)
    require_path_resource("reservations", reservation_id, "reservation")
    items = [r for r in db["refunds"].values() if r["reservation_id"] == reservation_id]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_refund(r) for r in page], total, limit, offset)


@bp.post("/refunds/<refund_id>/events")
def refund_events(refund_id):
    authorized(["OperationsManager"])
    rec = require_path_resource("refunds", refund_id, "refund")
    body = get_body()
    event_type = req_str(body, "event_type")

    if event_type == "APPROVE":
        approved = req_int(body, "approved_amount_cents", minimum=0)
        if rec["status"] != "REQUESTED":
            raise_error(ERR_INVALID_STATE, f"cannot APPROVE from {rec['status']}")
        if approved > rec["requested_amount_cents"]:
            raise_error(ERR_REFUND_POLICY_VIOLATION,
                        "approved_amount_cents exceeds requested_amount_cents")
        rec["approved_amount_cents"] = approved
        rec["status"] = "APPROVED"
        touch(rec)
        return success_object(public_refund(rec))

    if event_type == "PAY":
        paid_via = req_enum(body, "paid_via", ("ORIGINAL_PAYMENT", "WALLET_CREDIT"))
        if rec["status"] != "APPROVED":
            raise_error(ERR_INVALID_STATE, f"cannot PAY from {rec['status']}")
        rec["paid_via"] = paid_via
        rec["paid_at"] = CLOCK.now_iso()
        rec["status"] = "PAID"
        touch(rec)
        reservation = db["reservations"].get(rec["reservation_id"])
        customer = None
        if reservation is not None:
            reservation["refunded_cents"] += rec["approved_amount_cents"]
            reservation["payment_status"] = (
                "REFUNDED" if reservation["refunded_cents"] == reservation["paid_cents"]
                else "PARTIALLY_REFUNDED")
            touch(reservation)
            customer = db["customers"].get(reservation["customer_id"])
        if customer is not None:
            wallet_delta = 0
            if paid_via == "WALLET_CREDIT":
                wallet_delta += rec["approved_amount_cents"]
            # Operator goodwill lands in the wallet regardless of channel (PRD 3.7)
            if rec["reason"] == "OPERATOR_CANCEL" and reservation is not None:
                wallet_delta += reservation["goodwill_credit_cents"]
            if wallet_delta:
                customer["wallet_credit_cents"] += wallet_delta
                touch(customer)
        return success_object(public_refund(rec))

    if event_type == "DENY":
        if rec["status"] != "REQUESTED":
            raise_error(ERR_INVALID_STATE, f"cannot DENY from {rec['status']}")
        rec["status"] = "DENIED"
        touch(rec)
        return success_object(public_refund(rec))

    raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")
