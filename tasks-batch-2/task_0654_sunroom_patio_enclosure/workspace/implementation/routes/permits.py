"""PermitApplication + EngineeringReview endpoints (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, calculations
from services.permit_expiry import evaluate_expiry

bp = Blueprint("permits", __name__)

HOA_DECISIONS = {"HOA_APPROVED", "HOA_DENIED"}
PERMIT_OUTCOMES = {"APPROVED", "REJECTED"}


# ---------- PermitApplication ----------
@bp.route("/permit-applications", methods=["POST"])
def create_permit():
    user_id, role = require_roles({"SalesDesigner", "Homeowner"})
    body = common.get_json()

    project_id = common.require_field(body, "project_id", expected_types=["string"])
    jurisdiction_code = common.require_field(
        body, "jurisdiction_code", expected_types=["string"])

    project = common.get_project(project_id)

    # ownership not in priority-3 applies_to for POST /permit-applications;
    # PRD §2.1 lists resubmit but not create. No owner check here.

    hoa_required = bool(project["requires_hoa"])
    hoa_status = "PENDING" if hoa_required else "NOT_REQUIRED"

    entity = {
        "project_id": project_id,
        "jurisdiction_code": jurisdiction_code,
        "hoa_required": hoa_required,
        "hoa_status": hoa_status,
        "status": "SUBMITTED",
        "resubmission_count": 0,
        "expires_at": None,
    }
    common.stamp_create(entity)
    db.permit_applications[entity["id"]] = entity
    return response.success(serialize.permit(entity), status=201)


@bp.route("/permit-applications/<pid>", methods=["GET"])
def get_permit(pid):
    require_roles({"SalesDesigner", "Homeowner", "PermitOfficer"})
    permit = common.get_permit(pid)
    evaluate_expiry(permit)  # lazy EXPIRED evaluation (PRD §2.9, §3.4)
    return response.success(serialize.permit(permit), status=200)


@bp.route("/permit-applications/<pid>/engineering-reviews", methods=["GET"])
def list_engineering(pid):
    require_roles({"SalesDesigner", "PermitOfficer"})
    limit, offset = common.parse_pagination()
    common.get_permit(pid)  # existence (priority 4)
    items = [e for e in db.engineering_reviews.values()
             if e["permit_application_id"] == pid]
    page, total = common.paginate(items, limit, offset)
    return response.array([serialize.engineering(e) for e in page],
                          limit, offset, total)


@bp.route("/permit-applications/<pid>/begin-review", methods=["POST"])
def begin_review(pid):
    require_roles({"PermitOfficer"})
    common.get_json()
    permit = common.get_permit(pid)
    evaluate_expiry(permit)

    if permit["status"] != "SUBMITTED":
        raise errors.invalid_state("Permit must be SUBMITTED to begin review.")

    permit["status"] = "IN_REVIEW"
    if permit["hoa_required"] and permit["hoa_status"] == "NOT_REQUIRED":
        permit["hoa_status"] = "PENDING"
    common.touch(permit)
    return response.success(serialize.permit(permit), status=200)


@bp.route("/permit-applications/<pid>/hoa-decision", methods=["POST"])
def hoa_decision(pid):
    require_roles({"PermitOfficer"})
    body = common.get_json()
    hoa_status = common.require_field(
        body, "hoa_status", expected_types=["string"],
        validator=lambda v: v in HOA_DECISIONS)
    permit = common.get_permit(pid)
    evaluate_expiry(permit)

    permit["hoa_status"] = hoa_status
    common.touch(permit)
    return response.success(serialize.permit(permit), status=200)


@bp.route("/permit-applications/<pid>/decide", methods=["POST"])
def decide_permit(pid):
    require_roles({"PermitOfficer"})
    body = common.get_json()
    outcome = common.require_field(
        body, "outcome", expected_types=["string"],
        validator=lambda v: v in PERMIT_OUTCOMES)
    permit = common.get_permit(pid)
    evaluate_expiry(permit)
    project = common.get_project(permit["project_id"])

    # state (priority 5)
    if permit["status"] != "IN_REVIEW":
        raise errors.invalid_state("Permit must be IN_REVIEW to decide.")

    if outcome == "REJECTED":
        permit["status"] = "REJECTED"
        common.touch(permit)
        return response.success(serialize.permit(permit), status=200)

    # APPROVED branch — HOA gate (priority 16) then engineering gate (priority 17)
    if permit["hoa_required"] and permit["hoa_status"] != "HOA_APPROVED":
        raise errors.ApiError(
            errors.ERR_HOA_NOT_APPROVED, 409,
            "HOA approval required before permit approval.")
    if project["requires_engineering"]:
        has_passed = any(
            e["permit_application_id"] == pid and e["status"] == "PASSED"
            for e in db.engineering_reviews.values())
        if not has_passed:
            raise errors.ApiError(
                errors.ERR_ENGINEERING_PENDING, 409,
                "A passed engineering review is required before approval.")

    permit["expires_at"] = db.now() + timedelta(days=calculations.PERMIT_VALIDITY_DAYS)
    permit["status"] = "APPROVED"
    common.touch(permit)

    # drive Project PERMITTING -> APPROVED_TO_BUILD
    if project["status"] == "PERMITTING":
        project["status"] = "APPROVED_TO_BUILD"
        common.touch(project)
    return response.success(serialize.permit(permit), status=200)


@bp.route("/permit-applications/<pid>/resubmit", methods=["POST"])
def resubmit_permit(pid):
    user_id, role = require_roles({"Homeowner"})
    common.get_json()
    permit = common.get_permit(pid)
    project = common.get_project(permit["project_id"])

    # ownership (priority 3)
    if project["homeowner_id"] != user_id:
        raise errors.not_resource_owner("You do not own this project.")

    evaluate_expiry(permit)

    # state (priority 5)
    if permit["status"] != "REJECTED":
        raise errors.invalid_state("Permit must be REJECTED to resubmit.")

    # resubmission cap (priority 15)
    if permit["resubmission_count"] >= calculations.MAX_RESUBMISSIONS:
        raise errors.ApiError(
            errors.ERR_RESUBMIT_LIMIT, 409,
            "Permit resubmission limit reached.")

    permit["resubmission_count"] += 1
    permit["status"] = "SUBMITTED"
    common.touch(permit)
    return response.success(serialize.permit(permit), status=200)


# ---------- EngineeringReview ----------
@bp.route("/engineering-reviews", methods=["POST"])
def create_engineering():
    require_roles({"SalesDesigner"})
    body = common.get_json()

    permit_application_id = common.require_field(
        body, "permit_application_id", expected_types=["string"])
    project_id = common.require_field(body, "project_id", expected_types=["string"])
    rated_wind_mph = common.require_field(
        body, "rated_wind_mph", expected_types=["integer"],
        validator=lambda v: v >= 0)
    rated_snow_psf = common.require_field(
        body, "rated_snow_psf", expected_types=["number"],
        validator=lambda v: v >= 0)

    # existence left-to-right: permit then project (priority 4)
    permit = common.get_permit(permit_application_id)
    project = common.get_project(project_id)
    homeowner = db.homeowners[project["homeowner_id"]]

    entity = {
        "permit_application_id": permit_application_id,
        "project_id": project_id,
        "required_wind_mph": homeowner["design_wind_speed_mph"],
        "required_snow_psf": homeowner["ground_snow_load_psf"],
        "rated_wind_mph": rated_wind_mph,
        "rated_snow_psf": rated_snow_psf,
        "status": "PENDING",
    }
    common.stamp_create(entity)
    db.engineering_reviews[entity["id"]] = entity
    return response.success(serialize.engineering(entity), status=201)


@bp.route("/engineering-reviews/<eid>/rule", methods=["POST"])
def rule_engineering(eid):
    require_roles({"PermitOfficer"})
    common.get_json()
    review = common.get_engineering(eid)

    # state (priority 5)
    if review["status"] != "PENDING":
        raise errors.invalid_state("Engineering review must be PENDING to rule.")

    underrated = (review["rated_wind_mph"] < review["required_wind_mph"]
                  or review["rated_snow_psf"] < review["required_snow_psf"])

    if underrated:
        review["status"] = "FAILED"
        common.touch(review)
        # cascade: if linked permit IN_REVIEW, reject it
        permit = db.permit_applications.get(review["permit_application_id"])
        if permit is not None and permit["status"] == "IN_REVIEW":
            permit["status"] = "REJECTED"
            common.touch(permit)
        return response.success(serialize.engineering(review), status=200)

    # passes
    review["status"] = "PASSED"
    common.touch(review)
    return response.success(serialize.engineering(review), status=200)
