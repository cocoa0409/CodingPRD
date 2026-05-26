"""IncomeVerification routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_APPLICANT_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_subresource_or_404

bp = Blueprint("income_verifications", __name__)

DOCUMENT_TYPES = {"W2", "PAYSTUB", "TAX_RETURN", "BANK_DEPOSITS"}


def iv_to_dict(iv: dict) -> dict:
    return {
        "id": iv["id"],
        "application_id": iv["application_id"],
        "document_type": iv["document_type"],
        "verified_annual_income_cents": iv["verified_annual_income_cents"],
        "status": iv["status"],
        "rejection_reason": iv.get("rejection_reason"),
        "created_at": iv["created_at"],
        "updated_at": iv["updated_at"],
        "version": iv["version"],
    }


@bp.post("/income-verifications")
@require_auth(roles=["LoanOfficer"])
def create_income_verification():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    document_type = require_enum(body, "document_type", DOCUMENT_TYPES)
    verified_annual_income_cents = require_int(body, "verified_annual_income_cents")
    if verified_annual_income_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "verified_annual_income_cents must be non-negative.")
    with db.lock:
        iv = {
            **new_common_fields(),
            "application_id": application_id,
            "document_type": document_type,
            "verified_annual_income_cents": verified_annual_income_cents,
            "status": "PENDING",
            "rejection_reason": None,
        }
        db.income_verifications[iv["id"]] = iv
    return response.ok(iv_to_dict(iv), status=201)


@bp.get("/income-verifications/<iv_id>")
@require_auth(roles=["LoanOfficer", "Underwriter"])
def read_income_verification(iv_id: str):
    iv = get_subresource_or_404(db.income_verifications, iv_id)
    return response.ok(iv_to_dict(iv))


@bp.get("/income-verifications")
@require_auth(roles=["LoanOfficer", "Underwriter"])
def list_income_verifications():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(db.income_verifications.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([iv_to_dict(x) for x in page], limit, offset, total)


def _parent_app_ok(app_id: str) -> dict:
    la = db.loan_applications.get(app_id)
    if la is None:
        # Shouldn't happen since FK enforced at create. Defensive.
        raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
    if la["status"] not in ("PREQUALIFIED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, "Parent application not in PREQUALIFIED/UNDER_REVIEW.")
    return la


@bp.post("/income-verifications/<iv_id>/accept")
@require_auth(roles=["Underwriter"])
def accept_income_verification(iv_id: str):
    iv = get_subresource_or_404(db.income_verifications, iv_id)
    with db.lock:
        if iv["status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "Verification is not PENDING.")
        _parent_app_ok(iv["application_id"])
        iv["status"] = "ACCEPTED"
        bump(iv)
    return response.ok(iv_to_dict(iv))


@bp.post("/income-verifications/<iv_id>/reject")
@require_auth(roles=["Underwriter"])
def reject_income_verification(iv_id: str):
    iv = get_subresource_or_404(db.income_verifications, iv_id)
    with db.lock:
        if iv["status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "Verification is not PENDING.")
        _parent_app_ok(iv["application_id"])
        body = get_json_body()
        reason = require_str(body, "rejection_reason")
        iv["rejection_reason"] = reason
        iv["status"] = "REJECTED"
        bump(iv)
    return response.ok(iv_to_dict(iv))
