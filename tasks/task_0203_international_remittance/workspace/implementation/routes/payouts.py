"""PayoutAttempt endpoints (PRD §3.6). Reporting an outcome bubbles up to the
transfer's delivery_status; SUCCEEDED additionally releases the corridor
reservation and writes a RECIPIENT_CREDIT ledger entry.
"""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import touch, public, get_json, paginate, require_fields
from services.ledger import write_entry

bp = Blueprint("payouts", __name__)

FAILURE_REASONS = {"INVALID_ACCOUNT", "PICKUP_EXPIRED", "WALLET_REJECTED"}


@bp.route("/payout-attempts/<attempt_id>", methods=["GET"])
def get_attempt(attempt_id):
    _, role = get_user_context()
    require_role(role, {"PayoutOperator", "RemittanceAgent"})
    attempt = db.payout_attempts.get(attempt_id)
    if attempt is None:
        raise err("ERR_NOT_FOUND", "Payout attempt not found")
    return success(public(attempt), 200)


@bp.route("/payout-attempts", methods=["GET"])
def list_attempts():
    _, role = get_user_context()
    require_role(role, {"PayoutOperator", "RemittanceAgent", "ComplianceOfficer"})
    items = list(db.payout_attempts.values())
    tid = request.args.get("transfer_id")
    outcome = request.args.get("outcome")
    if tid is not None:
        items = [a for a in items if a["transfer_id"] == tid]
    if outcome is not None:
        items = [a for a in items if a["outcome"] == outcome]
    page, meta = paginate(items)
    return success([public(a) for a in page], 200, pagination=meta)


@bp.route("/payout-attempts/<attempt_id>/report-outcome", methods=["POST"])
def report_outcome(attempt_id):
    _, role = get_user_context()
    require_role(role, {"PayoutOperator"})
    attempt = db.payout_attempts.get(attempt_id)
    if attempt is None:
        raise err("ERR_NOT_FOUND", "Payout attempt not found")
    body = get_json()
    require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("SUCCEEDED", "FAILED"):
        raise err("ERR_INVALID_REQUEST", "outcome must be SUCCEEDED or FAILED")
    if outcome == "FAILED":
        reason = body.get("failure_reason")
        if reason is None or reason not in FAILURE_REASONS:
            raise err("ERR_INVALID_REQUEST",
                      "failure_reason must be INVALID_ACCOUNT/PICKUP_EXPIRED/WALLET_REJECTED")

    # State: report allowed only while the attempt is PENDING.
    if attempt["outcome"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Attempt outcome already reported")

    transfer = db.transfers[attempt["transfer_id"]]

    if outcome == "SUCCEEDED":
        attempt["outcome"] = "SUCCEEDED"
        touch(attempt)
        transfer["delivery_status"] = "DELIVERED"
        corridor = db.corridors[transfer["corridor_id"]]
        corridor["reserved_minor"] -= transfer["send_principal_minor"]
        write_entry(transfer["id"], "RECIPIENT_CREDIT",
                    transfer["send_principal_minor"], "Delivery to recipient")
        touch(transfer)
    else:
        attempt["outcome"] = "FAILED"
        attempt["failure_reason"] = body["failure_reason"]
        touch(attempt)
        transfer["delivery_status"] = "FAILED"
        touch(transfer)

    return success(public(attempt), 200)
