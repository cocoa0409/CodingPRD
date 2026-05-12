"""Initiator registration and KYC verification."""

from flask import Blueprint, g

from db import DB, LOCK, new_id
from errors import not_found, validation_error
from middleware import require_roles
from response import success_object
from services.audit import append_audit
from services.common import bump_version, get_json_body, require_str, stamp_create
from services.serializers import initiator_view


bp = Blueprint("initiators", __name__)


@bp.route("/initiators", methods=["POST"])
@require_roles("Initiator", "PlatformAdmin")
def create_initiator():
    body = get_json_body()
    legal_name = require_str(body, "legal_name")
    tax_id = body.get("tax_id")
    if tax_id is not None and not isinstance(tax_id, str):
        raise validation_error("tax_id must be a string")
    bank_account_id = body.get("bank_account_id")
    if bank_account_id is not None and not isinstance(bank_account_id, str):
        raise validation_error("bank_account_id must be a string")
    qualification_doc_uri = body.get("qualification_doc_uri")
    if qualification_doc_uri is not None and not isinstance(qualification_doc_uri, str):
        raise validation_error("qualification_doc_uri must be a string")

    with LOCK:
        rec = stamp_create({
            "id": new_id(),
            "legal_name": legal_name,
            "kyc_status": "PENDING",
            "tax_id": tax_id,
            "bank_account_id": bank_account_id,
            "qualification_doc_uri": qualification_doc_uri,
        })
        DB.initiators[rec["id"]] = rec

    return success_object(initiator_view(rec), status=201)


@bp.route("/initiators/<id>/verify-kyc", methods=["POST"])
@require_roles("PlatformAdmin")
def verify_kyc(id):
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("VERIFIED", "REJECTED"):
        raise validation_error("decision must be VERIFIED or REJECTED")
    with LOCK:
        rec = DB.initiators.get(id)
        if rec is None:
            raise not_found()
        from_status = rec["kyc_status"]
        rec["kyc_status"] = decision
        bump_version(rec)
        append_audit(
            subject_type="PROJECT",  # KYC affects an Initiator; no PROJECT subject here
            subject_id=rec["id"],
            event_type="REVIEW_DECISION",
            payload={"kyc_from": from_status, "kyc_to": decision, "initiator_id": rec["id"]},
            actor_role=g.role,
            actor_id=g.user_id,
        )
    return success_object(initiator_view(rec), status=200)
