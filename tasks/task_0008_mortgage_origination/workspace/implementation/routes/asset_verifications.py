"""AssetVerification routes."""
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

bp = Blueprint("asset_verifications", __name__)

ASSET_TYPES = {"CHECKING", "SAVINGS", "BROKERAGE", "RETIREMENT"}


def av_to_dict(av: dict) -> dict:
    return {
        "id": av["id"],
        "application_id": av["application_id"],
        "asset_type": av["asset_type"],
        "verified_balance_cents": av["verified_balance_cents"],
        "status": av["status"],
        "rejection_reason": av.get("rejection_reason"),
        "created_at": av["created_at"],
        "updated_at": av["updated_at"],
        "version": av["version"],
    }


@bp.post("/asset-verifications")
@require_auth(roles=["LoanOfficer"])
def create_asset_verification():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    asset_type = require_enum(body, "asset_type", ASSET_TYPES)
    verified_balance_cents = require_int(body, "verified_balance_cents")
    if verified_balance_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "verified_balance_cents must be non-negative.")
    with db.lock:
        av = {
            **new_common_fields(),
            "application_id": application_id,
            "asset_type": asset_type,
            "verified_balance_cents": verified_balance_cents,
            "status": "PENDING",
            "rejection_reason": None,
        }
        db.asset_verifications[av["id"]] = av
    return response.ok(av_to_dict(av), status=201)


@bp.get("/asset-verifications/<av_id>")
@require_auth(roles=["LoanOfficer", "Underwriter"])
def read_asset_verification(av_id: str):
    av = get_subresource_or_404(db.asset_verifications, av_id)
    return response.ok(av_to_dict(av))


@bp.get("/asset-verifications")
@require_auth(roles=["LoanOfficer", "Underwriter"])
def list_asset_verifications():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(db.asset_verifications.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([av_to_dict(x) for x in page], limit, offset, total)


def _parent_app_ok(app_id: str) -> dict:
    la = db.loan_applications.get(app_id)
    if la is None:
        raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
    if la["status"] not in ("PREQUALIFIED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, "Parent application not in PREQUALIFIED/UNDER_REVIEW.")
    return la


@bp.post("/asset-verifications/<av_id>/accept")
@require_auth(roles=["Underwriter"])
def accept_asset_verification(av_id: str):
    av = get_subresource_or_404(db.asset_verifications, av_id)
    with db.lock:
        if av["status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "Verification is not PENDING.")
        _parent_app_ok(av["application_id"])
        av["status"] = "ACCEPTED"
        bump(av)
    return response.ok(av_to_dict(av))


@bp.post("/asset-verifications/<av_id>/reject")
@require_auth(roles=["Underwriter"])
def reject_asset_verification(av_id: str):
    av = get_subresource_or_404(db.asset_verifications, av_id)
    with db.lock:
        if av["status"] != "PENDING":
            raise ApiError(ERR_INVALID_STATE, "Verification is not PENDING.")
        _parent_app_ok(av["application_id"])
        body = get_json_body()
        reason = require_str(body, "rejection_reason")
        av["rejection_reason"] = reason
        av["status"] = "REJECTED"
        bump(av)
    return response.ok(av_to_dict(av))
