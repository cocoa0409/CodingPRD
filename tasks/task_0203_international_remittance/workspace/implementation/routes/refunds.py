"""Refund endpoints (PRD §3.7). Direct refunds are SENDER_CANCEL (pre-dispatch)
or DELIVERY_FAILED (after exhausted attempts). COMPLIANCE_REJECT is fired only
by the compensating chain, not requested directly here.
"""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import public, get_json, paginate, require_fields
from services import calculations
from services.ledger import execute_refund

bp = Blueprint("refunds", __name__)

VALID_REASONS = {"SENDER_CANCEL", "COMPLIANCE_REJECT", "DELIVERY_FAILED"}


@bp.route("/refunds", methods=["POST"])
def create_refund():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "PayoutOperator"})
    body = get_json()
    require_fields(body, ["transfer_id", "reason"])
    transfer = db.transfers.get(body["transfer_id"])
    if transfer is None:
        raise err("ERR_NOT_FOUND", "Transfer not found")
    reason = body["reason"]
    if reason not in VALID_REASONS:
        raise err("ERR_INVALID_REQUEST", "reason must be a valid refund reason")

    delivery = transfer["delivery_status"]

    if reason == "SENDER_CANCEL":
        # Pre-dispatch cancellation: allowed only while PENDING.
        if delivery != "PENDING":
            raise err("ERR_REFUND_NOT_ALLOWED",
                      "SENDER_CANCEL only allowed while delivery is PENDING")
    elif reason == "DELIVERY_FAILED":
        # Allowed only while FAILED and attempts exhausted.
        if delivery != "FAILED":
            raise err("ERR_REFUND_NOT_ALLOWED",
                      "DELIVERY_FAILED only allowed while delivery is FAILED")
        failed_count = sum(1 for a in db.payout_attempts.values()
                           if a["transfer_id"] == transfer["id"]
                           and a["outcome"] == "FAILED")
        if failed_count < calculations.MAX_PAYOUT_ATTEMPTS:
            raise err("ERR_ATTEMPTS_NOT_EXHAUSTED",
                      "Payout attempts are not yet exhausted")
    else:  # COMPLIANCE_REJECT cannot be requested directly.
        raise err("ERR_REFUND_NOT_ALLOWED",
                  "COMPLIANCE_REJECT refunds are issued by the compensating chain only")

    corridor = db.corridors[transfer["corridor_id"]]
    refund = execute_refund(transfer, corridor, reason)
    return success(public(refund), 201)


@bp.route("/refunds/<refund_id>", methods=["GET"])
def get_refund(refund_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "PayoutOperator", "ComplianceOfficer"})
    refund = db.refunds.get(refund_id)
    if refund is None:
        raise err("ERR_NOT_FOUND", "Refund not found")
    return success(public(refund), 200)


@bp.route("/refunds", methods=["GET"])
def list_refunds():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "PayoutOperator", "ComplianceOfficer"})
    items = list(db.refunds.values())
    tid = request.args.get("transfer_id")
    reason = request.args.get("reason")
    if tid is not None:
        items = [r for r in items if r["transfer_id"] == tid]
    if reason is not None:
        items = [r for r in items if r["reason"] == reason]
    page, meta = paginate(items)
    return success([public(r) for r in page], 200, pagination=meta)
