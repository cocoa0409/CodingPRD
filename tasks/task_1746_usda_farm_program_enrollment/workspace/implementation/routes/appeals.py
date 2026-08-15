"""Appeal endpoints (PRD §3.10)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_SEGREGATION_OF_DUTIES, invalid_request, invalid_state,
    not_found, unauthorized,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, get_enrollment_or_404, get_appeal_or_404,
    get_producer_or_404,
)
from validation import body, require_string, require_enum, optional_string

bp = Blueprint("appeals", __name__)

GROUND_CODES = ("FACTUAL_ERROR", "PROCEDURAL_ERROR", "MISAPPLICATION_OF_RULE", "NEW_EVIDENCE")


@bp.post("/fsa/appeals")
def file_appeal():
    user_id, _ = require_roles(["Producer"])
    data = body()
    farm_id = require_string(data, "farm_id")
    enrollment_id = require_string(data, "enrollment_id")
    ground_code = require_enum(data, "ground_code", GROUND_CODES)
    filed_by_producer_id = require_string(data, "filed_by_producer_id")

    get_farm_or_404(farm_id)
    enrollment = get_enrollment_or_404(enrollment_id)
    if enrollment["farm_id"] != farm_id:
        raise not_found("Enrollment does not belong to the given farm")
    get_producer_or_404(filed_by_producer_id)

    # The enrollment must be CERTIFIED or PAYMENT_COMPUTED (PRD §3.10).
    if enrollment["enrollment_status"] not in ("CERTIFIED", "PAYMENT_COMPUTED"):
        raise invalid_state(
            "Appeals may only be filed against CERTIFIED or PAYMENT_COMPUTED enrollments")

    # remands_appeal_id: set when this appeal re-opens a previously remanded case.
    remands_appeal_id = None
    if enrollment.get("last_remanded_appeal_id") is not None:
        remands_appeal_id = enrollment["last_remanded_appeal_id"]

    appeal = db.common_fields()
    appeal.update({
        "farm_id": farm_id,
        "enrollment_id": enrollment_id,
        "appeal_status": "FILED",
        "ground_code": ground_code,
        "remands_appeal_id": remands_appeal_id,
        "filed_by_producer_id": filed_by_producer_id,
        "assigned_reviewer_producer_id": None,
    })
    db.appeals[appeal["id"]] = appeal

    # Side effect: enrollment -> ON_APPEAL, remembering the prior state.
    enrollment["pre_appeal_status"] = enrollment["enrollment_status"]
    enrollment["enrollment_status"] = "ON_APPEAL"
    db.touch(enrollment)

    return success_object(appeal, 201)


@bp.get("/fsa/appeals/<appeal_id>")
def get_appeal(appeal_id):
    require_roles(ALL_ROLES)
    return success_object(get_appeal_or_404(appeal_id))


@bp.get("/fsa/appeals")
def list_appeals():
    require_roles(ALL_ROLES)
    items = list(db.appeals.values())
    for param in ("farm_id", "enrollment_id", "remands_appeal_id",
                  "filed_by_producer_id", "assigned_reviewer_producer_id"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    items.sort(key=lambda a: a["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/farms/<farm_id>/appeals")
def list_farm_appeals(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    status = request.args.get("appeal_status")
    items = [a for a in db.appeals.values() if a["farm_id"] == farm_id]
    if status is not None:
        items = [a for a in items if a["appeal_status"] == status]
    items.sort(key=lambda a: a["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/appeals/<appeal_id>/assign-ced")
def assign_ced(appeal_id):
    require_roles(["CountyExecutiveDirector"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["appeal_status"] != "FILED":
        raise invalid_state("Only a FILED appeal may be assigned to CED review")
    appeal["appeal_status"] = "CED_REVIEW"
    db.touch(appeal)
    return success_object(appeal)


@bp.post("/fsa/appeals/<appeal_id>/refer-to-committee")
def refer_to_committee(appeal_id):
    require_roles(["CountyExecutiveDirector"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["appeal_status"] != "CED_REVIEW":
        raise invalid_state("Only a CED_REVIEW appeal may be referred to committee")
    data = body()
    reviewer_id = require_string(data, "assigned_reviewer_producer_id")
    get_producer_or_404(reviewer_id)
    # The reviewer must differ from the appellant (PRD §3.10).
    if reviewer_id == appeal["filed_by_producer_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "assigned_reviewer_producer_id must differ from filed_by_producer_id",
            422,
        )
    appeal["assigned_reviewer_producer_id"] = reviewer_id
    appeal["appeal_status"] = "COMMITTEE_HEARING"
    db.touch(appeal)
    return success_object(appeal)


def _check_reviewer(appeal, user_id):
    """Committee dispositions require the reviewer to differ from the
    appellant; the acting committee member is the assigned reviewer."""
    reviewer = appeal.get("assigned_reviewer_producer_id")
    if reviewer is not None and reviewer == appeal["filed_by_producer_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "reviewer must differ from appellant",
            422,
        )
    if user_id == appeal["filed_by_producer_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "reviewer must differ from appellant",
            422,
        )


def _restore_enrollment(appeal):
    enrollment = db.enrollments.get(appeal["enrollment_id"])
    if enrollment is not None and enrollment["enrollment_status"] == "ON_APPEAL":
        enrollment["enrollment_status"] = enrollment.get("pre_appeal_status", "CERTIFIED")
        db.touch(enrollment)
    return enrollment


@bp.post("/fsa/appeals/<appeal_id>/uphold")
def uphold_appeal(appeal_id):
    user_id, _ = require_roles(["CountyCommittee"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["appeal_status"] != "COMMITTEE_HEARING":
        raise invalid_state("Only a COMMITTEE_HEARING appeal may be upheld")
    _check_reviewer(appeal, user_id)
    appeal["appeal_status"] = "UPHELD"
    db.touch(appeal)
    _restore_enrollment(appeal)
    return success_object(appeal)


@bp.post("/fsa/appeals/<appeal_id>/reverse")
def reverse_appeal(appeal_id):
    user_id, _ = require_roles(["CountyCommittee"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["appeal_status"] != "COMMITTEE_HEARING":
        raise invalid_state("Only a COMMITTEE_HEARING appeal may be reversed")
    _check_reviewer(appeal, user_id)
    data = body()
    corrected = data.get("corrected_payment_cents")
    if corrected is not None and (isinstance(corrected, bool) or not isinstance(corrected, int)):
        raise invalid_request("corrected_payment_cents must be an integer")
    appeal["appeal_status"] = "REVERSED"
    db.touch(appeal)
    # Payment recomputed per the committee's factual correction (PRD §3.10).
    enrollment = db.enrollments.get(appeal["enrollment_id"])
    if enrollment is not None and corrected is not None:
        enrollment["computed_payment_cents"] = corrected
        db.touch(enrollment)
    return success_object(appeal)


@bp.post("/fsa/appeals/<appeal_id>/remand")
def remand_appeal(appeal_id):
    user_id, _ = require_roles(["CountyCommittee"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["appeal_status"] != "COMMITTEE_HEARING":
        raise invalid_state("Only a COMMITTEE_HEARING appeal may be remanded")
    _check_reviewer(appeal, user_id)
    data = body()
    require_string(data, "remand_instructions")
    appeal["appeal_status"] = "REMANDED"
    db.touch(appeal)
    enrollment = db.enrollments.get(appeal["enrollment_id"])
    if enrollment is not None:
        enrollment["enrollment_status"] = "REMANDED"
        enrollment["last_remanded_appeal_id"] = appeal["id"]
        db.touch(enrollment)
    return success_object(appeal)


@bp.post("/fsa/appeals/<appeal_id>/close")
def close_appeal(appeal_id):
    user_id, _ = require_roles(["Producer"])
    appeal = get_appeal_or_404(appeal_id)
    if appeal["appeal_status"] not in ("FILED", "CED_REVIEW"):
        raise invalid_state("Only a FILED or CED_REVIEW appeal may be closed")
    # Only the appellant may close (PRD §3.10).
    if appeal["filed_by_producer_id"] != user_id:
        raise unauthorized("Only the appellant may close the appeal")
    appeal["appeal_status"] = "CLOSED"
    db.touch(appeal)
    _restore_enrollment(appeal)
    return success_object(appeal)
