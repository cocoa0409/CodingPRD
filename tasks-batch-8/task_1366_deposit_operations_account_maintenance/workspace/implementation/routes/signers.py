"""AuthorizedSigner endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DOCUMENTS_INCOMPLETE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import signer_view
from services.account import get_account_or_404, touch_resource

bp = Blueprint("signers", __name__)

SIGNER_ROLES = {
    "OWNER",
    "AUTHORIZED_SIGNER",
    "POWER_OF_ATTORNEY",
    "TRUSTEE",
    "BUSINESS_OFFICER",
}


@bp.post("/bank/accounts/<account_id>/signers")
def add_signer(account_id):
    require_roles(["OpsOfficer"])
    get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip():
        raise ApiError(ERR_INVALID_REQUEST, "full_name is required")
    tax_id = body.get("tax_id")
    if not isinstance(tax_id, str) or not tax_id.strip():
        raise ApiError(ERR_INVALID_REQUEST, "tax_id is required")
    signer_role = body.get("signer_role")
    if signer_role not in SIGNER_ROLES:
        raise ApiError(ERR_INVALID_REQUEST, "signer_role must be a declared member")
    reference = body.get("signature_card_reference")
    if not isinstance(reference, str) or not reference.strip():
        raise ApiError(ERR_INVALID_REQUEST, "signature_card_reference is required")

    # Requires a VERIFIED SIGNATURE_CARD whose reference_number matches (PRD §3.2).
    verified_card = any(
        d["account_id"] == account_id
        and d["doc_type"] == "SIGNATURE_CARD"
        and d["status"] == "VERIFIED"
        and d["reference_number"] == reference
        for d in db.documents.values()
    )
    if not verified_card:
        raise ApiError(
            ERR_DOCUMENTS_INCOMPLETE,
            "No VERIFIED SIGNATURE_CARD document with that reference_number on this account",
        )

    signer = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "full_name": full_name,
        "tax_id": tax_id,
        "signer_role": signer_role,
        "signature_card_reference": reference,
        "status": "ACTIVE",
        "removed_reason": None,
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.signers[signer["id"]] = signer
    return success_object(signer_view(signer), status=201)


@bp.post("/bank/signers/<signer_id>/remove")
def remove_signer(signer_id):
    require_roles(["OpsOfficer", "OpsManager"])
    signer = db.signers.get(signer_id)
    if signer is None:
        raise ApiError(ERR_NOT_FOUND, f"Signer {signer_id} does not exist")
    if signer["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "Signer is not ACTIVE or SUSPENDED")
    acct = db.accounts.get(signer["account_id"])
    if acct is not None and acct["lifecycle_status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "Account is CLOSED")

    signer["status"] = "REMOVED"
    signer["removed_reason"] = "STAFF_REQUEST"
    touch_resource(signer)
    return success_object(signer_view(signer))


@bp.get("/bank/accounts/<account_id>/signers")
def list_signers(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")

    items = [s for s in db.signers.values() if s["account_id"] == account_id]
    items.sort(key=lambda s: s["_seq"])
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([signer_view(s) for s in page], total, limit, offset)
