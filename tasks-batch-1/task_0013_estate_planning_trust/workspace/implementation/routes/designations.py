"""BeneficiaryDesignation routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    optional_string,
    pagination_params,
    require_enum,
    require_int,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_CONTINGENT_PARENT_INVALID,
    ERR_INVALID_REQUEST,
    ERR_SHARE_OVERALLOCATION,
    invalid_state,
    not_found,
    stale_version,
)
from middleware import require_roles
from response import created, list_response, success
from services.cascades import cascade_revoke_designation
from views import view_designation


bp = Blueprint("designations", __name__)

RELATIONSHIPS = {"SPOUSE", "CHILD", "GRANDCHILD", "PARENT", "SIBLING", "CHARITY", "OTHER"}


def _validate_contingent_parent(estate_id: str, parent_id: str) -> None:
    parent = db.beneficiary_designations.get(parent_id)
    if parent is None or parent["estate_id"] != estate_id or parent["status"] != "ACTIVE":
        raise APIError(
            ERR_CONTINGENT_PARENT_INVALID,
            "contingent_of_designation_id must reference an ACTIVE designation on the same estate.",
            422,
        )


@bp.post("/beneficiary-designations")
@require_roles("EstatePlanner")
def create_designation():
    body = get_body()
    estate_id = require_string(body, "estate_id")
    if estate_id not in db.estates:
        raise not_found("Estate")

    beneficiary_full_name = require_string(body, "beneficiary_full_name")
    relationship = require_enum(body, "relationship", RELATIONSHIPS)
    share_bp = require_int(body, "share_basis_points")
    if share_bp <= 0 or share_bp > 10000:
        raise APIError(ERR_INVALID_REQUEST, "share_basis_points must satisfy 0 < x <= 10000.", 400)

    contingent_of = optional_string(body, "contingent_of_designation_id")
    if contingent_of is not None:
        _validate_contingent_parent(estate_id, contingent_of)

    now = db.now_utc()
    b = {
        "estate_id": estate_id,
        "beneficiary_full_name": beneficiary_full_name,
        "relationship": relationship,
        "share_basis_points": share_bp,
        "status": "DRAFT",
        "contingent_of_designation_id": contingent_of,
    }
    stamp_common_fields(b, now)
    db.beneficiary_designations[b["id"]] = b
    return created(view_designation(b))


@bp.get("/beneficiary-designations/<bid>")
@require_roles("EstatePlanner", "Executor", "Judge", "Beneficiary")
def get_designation(bid: str):
    b = db.beneficiary_designations.get(bid)
    if b is None:
        raise not_found("BeneficiaryDesignation")
    return success(view_designation(b))


@bp.get("/beneficiary-designations")
@require_roles("EstatePlanner", "Executor", "Judge")
def list_designations():
    limit, offset = pagination_params()
    estate_id = request.args.get("estate_id")
    status = request.args.get("status")
    contingent_of = request.args.get("contingent_of_designation_id")

    items = list(db.beneficiary_designations.values())
    if estate_id is not None:
        items = [b for b in items if b["estate_id"] == estate_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if contingent_of is not None:
        items = [b for b in items if b.get("contingent_of_designation_id") == contingent_of]

    items.sort(key=lambda b: b["created_at"])
    total = len(items)
    page = [view_designation(b) for b in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


@bp.post("/beneficiary-designations/<bid>/activate")
@require_roles("EstatePlanner")
def activate_designation(bid: str):
    b = db.beneficiary_designations.get(bid)
    if b is None:
        raise not_found("BeneficiaryDesignation")
    if b["status"] != "DRAFT":
        raise invalid_state("Designation must be DRAFT to activate.")

    estate = db.estates.get(b["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] == "CLOSED":
        raise invalid_state("Cannot activate designation on a CLOSED estate.")

    # Contingent-parent referential integrity (priority 7)
    if b.get("contingent_of_designation_id") is not None:
        _validate_contingent_parent(b["estate_id"], b["contingent_of_designation_id"])

    # Share overallocation check (priority 9)
    active_sum = sum(
        x["share_basis_points"]
        for x in db.beneficiary_designations.values()
        if x["estate_id"] == b["estate_id"] and x["status"] == "ACTIVE"
    )
    if active_sum + b["share_basis_points"] > 10000:
        raise APIError(
            ERR_SHARE_OVERALLOCATION,
            "Activating this designation would push ACTIVE share total above 10000.",
            422,
        )

    now = db.now_utc()
    b["status"] = "ACTIVE"
    touch(b, now)
    return success(view_designation(b))


@bp.post("/beneficiary-designations/<bid>/revoke")
@require_roles("EstatePlanner")
def revoke_designation(bid: str):
    b = db.beneficiary_designations.get(bid)
    if b is None:
        raise not_found("BeneficiaryDesignation")

    estate = db.estates.get(b["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] not in ("ALIVE", "DECEASED"):
        raise invalid_state("Designation revocation only allowed while estate is ALIVE or DECEASED.")
    if b["status"] != "ACTIVE":
        raise invalid_state("Designation must be ACTIVE to revoke.")

    body = get_body()
    expected_v = require_int(body, "expected_estate_version")
    if expected_v != estate["version"]:
        raise stale_version()

    now = db.now_utc()
    b["status"] = "REVOKED"
    touch(b, now)
    cascade_revoke_designation(b, now)
    touch(estate, now)
    return success(view_designation(b))
