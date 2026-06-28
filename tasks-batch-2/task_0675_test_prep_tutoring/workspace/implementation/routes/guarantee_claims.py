"""GuaranteeClaim endpoints + adjudication state machine (PRD §3.7)."""
from flask import Blueprint

import db
import response
from errors import err
from middleware import require_auth, get_json_body
from services import serialize, validators, core

bp = Blueprint("guarantee_claims", __name__)


def _get_claim_or_404(gid):
    g = db.guarantee_claims.get(gid)
    if g is None:
        raise err("ERR_NOT_FOUND", "Guarantee claim not found.")
    return g


@bp.post("/guarantee-claims")
def file_claim():
    user_id, role = require_auth({"Student", "Registrar"})
    body = get_json_body()

    enrollment_id = validators.require_str(body, "enrollment_id")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found.")

    if role == "Student" and enrollment["student_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Student does not own this enrollment.")

    resolution = validators.require_enum(body, "resolution", validators.RESOLUTIONS)

    rec = {
        "id": db.new_id(),
        "enrollment_id": enrollment_id,
        "resolution": resolution,
        "improvement_delta": None,
        "refund_amount_cents": 0,
        "status": "FILED",
    }
    db.stamp_create(rec)
    db.guarantee_claims[rec["id"]] = rec
    return response.success(serialize.guarantee_claim(rec), 201)


@bp.get("/guarantee-claims/<gid>")
def get_claim(gid):
    user_id, role = require_auth({"Student", "Registrar"})
    g = _get_claim_or_404(gid)
    if role == "Student":
        enrollment = db.enrollments.get(g["enrollment_id"])
        if enrollment is None or enrollment["student_id"] != user_id:
            raise err("ERR_UNAUTHORIZED", "Student does not own this claim.")
    return response.success(serialize.guarantee_claim(g), 200)


@bp.post("/guarantee-claims/<gid>/review")
def review_claim(gid):
    require_auth({"Registrar"})
    g = _get_claim_or_404(gid)

    if g["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim is not FILED.")

    enrollment = db.enrollments[g["enrollment_id"]]
    # Re-check eligibility per PRD §3.7 (re-evaluated at review).
    core.evaluate_guarantee(enrollment)
    if enrollment["guarantee_status"] != "ELIGIBLE":
        raise err("ERR_GUARANTEE_NOT_ELIGIBLE", "Enrollment guarantee is not ELIGIBLE.")

    student = db.students[enrollment["student_id"]]
    g["improvement_delta"] = enrollment["best_practice_score"] - student["diagnostic_score"]
    g["status"] = "UNDER_REVIEW"
    db.touch(g)
    return response.success(serialize.guarantee_claim(g), 200)


@bp.post("/guarantee-claims/<gid>/approve")
def approve_claim(gid):
    require_auth({"Registrar"})
    g = _get_claim_or_404(gid)

    if g["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW.")

    enrollment = db.enrollments[g["enrollment_id"]]
    cohort = db.cohorts[enrollment["cohort_id"]]
    course = db.courses[cohort["course_id"]]

    # Threshold check: improvement_delta must be strictly below guarantee_min_delta.
    if g["improvement_delta"] >= course["guarantee_min_delta"]:
        raise err("ERR_GUARANTEE_THRESHOLD_MET", "Guarantee threshold was met.")

    g["status"] = "APPROVED"

    if g["resolution"] == "REFUND":
        # Conserved refund: plan.amount_paid_cents if a plan exists else
        # enrollment.price_paid_cents (PRD §3.7).
        plan = core.find_any_plan(enrollment["id"])
        if plan is not None:
            g["refund_amount_cents"] = plan["amount_paid_cents"]
        else:
            g["refund_amount_cents"] = enrollment["price_paid_cents"]
        enrollment["guarantee_status"] = "REFUND_ISSUED"
        db.touch(enrollment)
        # Cascade the enrollment's OPEN installment plan OPEN -> REFUNDED.
        core.refund_open_plan(enrollment["id"])
    else:  # RETAKE
        enrollment["guarantee_status"] = "RETAKE_GRANTED"
        g["refund_amount_cents"] = 0
        core.extend_materials_expiry(enrollment, course)
        db.touch(enrollment)

    db.touch(g)
    return response.success(serialize.guarantee_claim(g), 200)


@bp.post("/guarantee-claims/<gid>/reject")
def reject_claim(gid):
    require_auth({"Registrar"})
    g = _get_claim_or_404(gid)

    if g["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW.")

    g["status"] = "REJECTED"
    db.touch(g)

    enrollment = db.enrollments[g["enrollment_id"]]
    enrollment["guarantee_status"] = "INELIGIBLE"
    db.touch(enrollment)
    return response.success(serialize.guarantee_claim(g), 200)
