"""Milestone endpoints."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response

bp = Blueprint("milestones", __name__)


@bp.post("/licensing/milestones")
def create_milestone():
    middleware.require_role("LicensingAnalyst")
    body = common.get_body()
    common.validate_body(body, [
        ("agreement_id", "string", True),
        ("name", "string", True),
        ("trigger_type", "enum:CUMULATIVE_SALES,DATE", True),
        ("threshold_cents", "int", False),
        ("trigger_date", "datetime", False),
        ("fee_cents", "int", True),
    ])
    # Tier 3: body FK existence
    agr = db.agreements.get(body["agreement_id"])
    if agr is None:
        raise errors.err_agreement_not_found()

    # Conditional-required schema rules
    if body["trigger_type"] == "CUMULATIVE_SALES":
        if "threshold_cents" not in body:
            raise errors.err_validation(
                "threshold_cents is required for CUMULATIVE_SALES milestones")
        if "trigger_date" in body:
            raise errors.err_validation(
                "trigger_date is forbidden for CUMULATIVE_SALES milestones")
        if body["threshold_cents"] <= 0:
            raise errors.err_validation("threshold_cents must be > 0")
    else:  # DATE
        if "trigger_date" not in body:
            raise errors.err_validation("trigger_date is required for DATE milestones")
        if "threshold_cents" in body:
            raise errors.err_validation(
                "threshold_cents is forbidden for DATE milestones")

    if body["fee_cents"] < 0:
        raise errors.err_validation("fee_cents must be >= 0")

    # Tier 7: agreement standing (DRAFT or ACTIVE)
    if agr["status"] not in ("DRAFT", "ACTIVE"):
        raise errors.err_agreement_not_active(
            "Milestones may only be created on DRAFT or ACTIVE agreements")

    m = common.new_resource({
        "agreement_id": body["agreement_id"],
        "name": body["name"],
        "trigger_type": body["trigger_type"],
        "threshold_cents": body.get("threshold_cents"),
        "trigger_date": body.get("trigger_date"),
        "fee_cents": body["fee_cents"],
        "status": "PENDING",
        "achieved_at": None,
    })
    db.milestones[m["id"]] = m
    return response.success_object(m, 201)


@bp.get("/licensing/milestones")
def list_milestones():
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee")
    args = common.request.args
    agreement_id = args.get("agreement_id")
    status = args.get("status")
    items = list(db.milestones.values())
    if role == "Licensee":
        items = [m for m in items
                 if db.agreements[m["agreement_id"]]["licensee_id"] == user_id]
    if agreement_id is not None:
        items = [m for m in items if m["agreement_id"] == agreement_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/milestones/<mid>")
def get_milestone(mid):
    user_id, role = middleware.require_role(
        "LicensingAnalyst", "LegalCounsel", "FinanceOfficer", "Licensee")
    m = db.milestones.get(mid)
    if m is None:
        raise errors.err_agreement_not_found()
    if role == "Licensee" and \
            db.agreements[m["agreement_id"]]["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    return response.success_object(m)
