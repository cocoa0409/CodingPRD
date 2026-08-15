"""TitleChangeRequest endpoints (PRD §3.3): the cyclic SUBMITTED ->
APPROVED / REJECTED -> SUBMITTED workflow, OCC-guarded at filing.
"""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ACCOUNT_RESTRICTED,
    ERR_ACTIVE_REQUEST_EXISTS,
    ERR_DOCUMENTS_INCOMPLETE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import title_change_view
from services.account import (
    OWNERSHIP_TYPES,
    get_account_or_404,
    touch_account,
    touch_resource,
)

bp = Blueprint("title_changes", __name__)

REQUIRED_DOCS = {
    "POD": ["POD_DESIGNATION"],
    "TRUST": ["TRUST_AGREEMENT"],
    "BUSINESS": ["BUSINESS_RESOLUTION", "SIGNATURE_CARD"],
    "INDIVIDUAL": ["SIGNATURE_CARD"],
    "JOINT": ["SIGNATURE_CARD"],
}


def _get_request_or_404(request_id):
    req = db.title_changes.get(request_id)
    if req is None:
        raise ApiError(ERR_NOT_FOUND, f"Title change request {request_id} does not exist")
    return req


@bp.post("/bank/accounts/<account_id>/title-changes")
def file_title_change(account_id):
    user_id, _ = require_roles(["OpsOfficer"])
    acct = get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    requested = body.get("requested_ownership_type")
    if requested not in OWNERSHIP_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "requested_ownership_type must be a declared member")
    if requested == acct["ownership_type"]:
        raise ApiError(
            ERR_INVALID_REQUEST, "requested_ownership_type must differ from the current type"
        )
    beneficiary = body.get("pod_beneficiary_name")
    if requested == "POD":
        if not isinstance(beneficiary, str) or not beneficiary.strip():
            raise ApiError(
                ERR_INVALID_REQUEST,
                "pod_beneficiary_name is required when the requested type is POD",
            )
    elif beneficiary is not None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "pod_beneficiary_name is only allowed when the requested type is POD",
        )
    expected = body.get("expected_account_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_account_version is required")

    # Tier 5: OCC (PRD §2.11).
    if expected != acct["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_account_version does not match the current version")

    # Tier 7: at most one SUBMITTED request per account.
    if any(
        r["account_id"] == account_id and r["status"] == "SUBMITTED"
        for r in db.title_changes.values()
    ):
        raise ApiError(ERR_ACTIVE_REQUEST_EXISTS, "A SUBMITTED title change request already exists")

    req = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "current_ownership_type": acct["ownership_type"],
        "requested_ownership_type": requested,
        "pod_beneficiary_name": beneficiary if requested == "POD" else None,
        "required_doc_types": list(REQUIRED_DOCS[requested]),
        "status": "SUBMITTED",
        "created_by_user_id": user_id,
        "decided_by_user_id": None,
        "decision_reason": None,
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.title_changes[req["id"]] = req
    # Filing registers against the account, bumping its version (PRD §3.3).
    touch_account(acct)
    return success_object(title_change_view(req), status=201)


@bp.post("/bank/title-changes/<request_id>/approve")
def approve_title_change(request_id):
    user_id, _ = require_roles(["OpsManager"])
    req = _get_request_or_404(request_id)
    acct = get_account_or_404(req["account_id"])

    if req["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED request can be approved")
    if acct["lifecycle_status"] != "OPEN" or acct["restriction_status"] != "NONE":
        raise ApiError(ERR_ACCOUNT_RESTRICTED, "Account must be OPEN with restriction NONE")
    verified_types = {
        d["doc_type"]
        for d in db.documents.values()
        if d["account_id"] == acct["id"] and d["status"] == "VERIFIED"
    }
    if any(t not in verified_types for t in req["required_doc_types"]):
        raise ApiError(
            ERR_DOCUMENTS_INCOMPLETE,
            "A required document type lacks a VERIFIED document on the account",
        )
    if user_id == req["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Approver cannot be the request creator")

    acct["ownership_type"] = req["requested_ownership_type"]
    if req["requested_ownership_type"] == "POD":
        acct["pod_beneficiary_name"] = req["pod_beneficiary_name"]
    req["status"] = "APPROVED"
    req["decided_by_user_id"] = user_id
    touch_resource(req)
    touch_account(acct)
    return success_object(title_change_view(req))


@bp.post("/bank/title-changes/<request_id>/reject")
def reject_title_change(request_id):
    user_id, _ = require_roles(["OpsManager"])
    req = _get_request_or_404(request_id)
    body = request.get_json(silent=True) or {}

    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(ERR_INVALID_REQUEST, "reason is required")

    if req["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED request can be rejected")

    req["status"] = "REJECTED"
    req["decision_reason"] = reason
    req["decided_by_user_id"] = user_id
    touch_resource(req)
    return success_object(title_change_view(req))


@bp.post("/bank/title-changes/<request_id>/resubmit")
def resubmit_title_change(request_id):
    require_roles(["OpsOfficer"])
    req = _get_request_or_404(request_id)
    acct = get_account_or_404(req["account_id"])

    if req["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, "Only a REJECTED request can be resubmitted")
    if acct["lifecycle_status"] != "OPEN" or acct["restriction_status"] != "NONE":
        raise ApiError(ERR_ACCOUNT_RESTRICTED, "Account must be OPEN with restriction NONE")
    if any(
        r["account_id"] == acct["id"] and r["status"] == "SUBMITTED" and r["id"] != req["id"]
        for r in db.title_changes.values()
    ):
        raise ApiError(ERR_ACTIVE_REQUEST_EXISTS, "Another SUBMITTED request exists on the account")

    req["status"] = "SUBMITTED"
    req["required_doc_types"] = list(REQUIRED_DOCS[req["requested_ownership_type"]])
    req["decision_reason"] = None
    req["decided_by_user_id"] = None
    touch_resource(req)
    return success_object(title_change_view(req))


@bp.get("/bank/accounts/<account_id>/title-changes")
def list_title_changes(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")

    items = [r for r in db.title_changes.values() if r["account_id"] == account_id]
    items.sort(key=lambda r: r["_seq"])
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([title_change_view(r) for r in page], total, limit, offset)
