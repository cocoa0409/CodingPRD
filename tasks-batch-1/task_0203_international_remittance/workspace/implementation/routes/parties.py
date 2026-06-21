"""Sender and Recipient endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import (stamp_create, touch, public, get_json,
                             paginate, require_fields)

bp = Blueprint("parties", __name__)

PAYOUT_METHODS = {"BANK", "CASH_PICKUP", "WALLET"}
KYC_TIERS = {"TIER0", "TIER1", "TIER2"}


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------
@bp.route("/senders", methods=["POST"])
def create_sender():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    body = get_json()
    require_fields(body, ["full_name", "country", "date_of_birth"])
    sender = {
        "full_name": body["full_name"],
        "country": body["country"],
        "date_of_birth": body["date_of_birth"],
        "kyc_tier": "TIER0",   # system-initialized; client input ignored
        "status": "ACTIVE",
    }
    stamp_create(sender)
    db.senders[sender["id"]] = sender
    return success(public(sender), 201)


@bp.route("/senders/<sender_id>", methods=["GET"])
def get_sender(sender_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer"})
    sender = db.senders.get(sender_id)
    if sender is None:
        raise err("ERR_NOT_FOUND", "Sender not found")
    return success(public(sender), 200)


@bp.route("/senders", methods=["GET"])
def list_senders():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer"})
    items = list(db.senders.values())
    country = request.args.get("country")
    status = request.args.get("status")
    if country is not None:
        items = [s for s in items if s["country"] == country]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate(items)
    return success([public(s) for s in page], 200, pagination=meta)


@bp.route("/senders/<sender_id>/verify-kyc", methods=["POST"])
def verify_sender_kyc(sender_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    sender = db.senders.get(sender_id)
    if sender is None:
        raise err("ERR_NOT_FOUND", "Sender not found")
    body = get_json()
    require_fields(body, ["kyc_tier"])
    if body["kyc_tier"] not in KYC_TIERS:
        raise err("ERR_INVALID_REQUEST", "kyc_tier must be TIER0/TIER1/TIER2")
    sender["kyc_tier"] = body["kyc_tier"]
    touch(sender)
    return success(public(sender), 200)


# ---------------------------------------------------------------------------
# Recipient
# ---------------------------------------------------------------------------
@bp.route("/recipients", methods=["POST"])
def create_recipient():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    body = get_json()
    require_fields(body, ["sender_id", "full_name", "country", "payout_method",
                          "payout_account_ref"])
    # Existence of FK before further body validation (PRD §2.6 left-to-right).
    if body["sender_id"] not in db.senders:
        raise err("ERR_NOT_FOUND", "Sender not found")
    if body["payout_method"] not in PAYOUT_METHODS:
        raise err("ERR_INVALID_REQUEST", "payout_method must be BANK/CASH_PICKUP/WALLET")
    recipient = {
        "sender_id": body["sender_id"],
        "full_name": body["full_name"],
        "country": body["country"],
        "payout_method": body["payout_method"],
        "payout_account_ref": body["payout_account_ref"],
        "kyc_status": "UNVERIFIED",
        "kyc_doc_ref": None,
        "kyc_review_count": 0,
    }
    stamp_create(recipient)
    db.recipients[recipient["id"]] = recipient
    return success(public(recipient), 201)


@bp.route("/recipients/<recipient_id>", methods=["GET"])
def get_recipient(recipient_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer", "PayoutOperator"})
    recipient = db.recipients.get(recipient_id)
    if recipient is None:
        raise err("ERR_NOT_FOUND", "Recipient not found")
    return success(public(recipient), 200)


@bp.route("/recipients", methods=["GET"])
def list_recipients():
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent", "ComplianceOfficer", "PayoutOperator"})
    items = list(db.recipients.values())
    sid = request.args.get("sender_id")
    ks = request.args.get("kyc_status")
    if sid is not None:
        items = [r for r in items if r["sender_id"] == sid]
    if ks is not None:
        items = [r for r in items if r["kyc_status"] == ks]
    page, meta = paginate(items)
    return success([public(r) for r in page], 200, pagination=meta)


@bp.route("/recipients/<recipient_id>/submit-kyc", methods=["POST"])
def submit_recipient_kyc(recipient_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    recipient = db.recipients.get(recipient_id)
    if recipient is None:
        raise err("ERR_NOT_FOUND", "Recipient not found")
    body = get_json()
    # State precondition: submit-kyc allowed only from UNVERIFIED or REJECTED.
    if recipient["kyc_status"] not in ("UNVERIFIED", "REJECTED"):
        raise err("ERR_INVALID_STATE",
                  "submit-kyc only allowed from UNVERIFIED or REJECTED")
    # kyc_doc_ref required (specific error, precedes generic state machine side).
    if "kyc_doc_ref" not in body or body["kyc_doc_ref"] is None:
        raise err("ERR_KYC_DOC_REQUIRED", "kyc_doc_ref is required")

    from_rejected = recipient["kyc_status"] == "REJECTED"
    recipient["kyc_doc_ref"] = body["kyc_doc_ref"]
    recipient["kyc_status"] = "PENDING_REVIEW"
    if from_rejected:
        recipient["kyc_review_count"] += 1
    touch(recipient)
    return success(public(recipient), 200)


@bp.route("/recipients/<recipient_id>/decide-kyc", methods=["POST"])
def decide_recipient_kyc(recipient_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    recipient = db.recipients.get(recipient_id)
    if recipient is None:
        raise err("ERR_NOT_FOUND", "Recipient not found")
    body = get_json()
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("APPROVE", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be APPROVE or REJECT")
    if recipient["kyc_status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", "decide-kyc only allowed from PENDING_REVIEW")
    recipient["kyc_status"] = "VERIFIED" if decision == "APPROVE" else "REJECTED"
    touch(recipient)
    return success(public(recipient), 200)
