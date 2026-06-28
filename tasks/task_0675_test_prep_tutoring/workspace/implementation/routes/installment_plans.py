"""InstallmentPlan endpoints + financing state machine (PRD §3.6)."""
from flask import Blueprint

import db
import response
from errors import err
from middleware import require_auth, get_json_body
from services import serialize, validators, core

bp = Blueprint("installment_plans", __name__)


def _get_plan_or_404(pid):
    p = db.installment_plans.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "Installment plan not found.")
    return p


@bp.post("/installment-plans")
def create_plan():
    user_id, role = require_auth({"Student", "Registrar"})
    body = get_json_body()

    enrollment_id = validators.require_str(body, "enrollment_id")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found.")

    # Ownership: a Student finances only its own enrollment.
    if role == "Student" and enrollment["student_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Student does not own this enrollment.")

    num_installments = validators.require_int(body, "num_installments")
    if num_installments not in validators.NUM_INSTALLMENTS:
        raise err("ERR_INVALID_REQUEST", "num_installments must be one of 1,2,3,4,6,12.")

    rec = {
        "id": db.new_id(),
        "enrollment_id": enrollment_id,
        "num_installments": num_installments,
        "total_financed_cents": enrollment["price_paid_cents"],
        "amount_paid_cents": 0,
        "status": "OPEN",
    }
    db.stamp_create(rec)
    db.installment_plans[rec["id"]] = rec
    return response.success(serialize.installment_plan(rec), 201)


@bp.get("/installment-plans/<pid>")
def get_plan(pid):
    user_id, role = require_auth({"Student", "Registrar"})
    p = _get_plan_or_404(pid)
    if role == "Student":
        enrollment = db.enrollments.get(p["enrollment_id"])
        if enrollment is None or enrollment["student_id"] != user_id:
            raise err("ERR_UNAUTHORIZED", "Student does not own this plan.")
    return response.success(serialize.installment_plan(p), 200)


@bp.post("/installment-plans/<pid>/payments")
def record_payment(pid):
    require_auth({"Registrar"})
    p = _get_plan_or_404(pid)
    body = get_json_body()
    amount_cents = validators.require_int(body, "amount_cents", minimum=0)

    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Plan is not OPEN.")

    p["amount_paid_cents"] += amount_cents
    if p["amount_paid_cents"] == p["total_financed_cents"]:
        p["status"] = "PAID_IN_FULL"
    db.touch(p)
    return response.success(serialize.installment_plan(p), 200)


@bp.post("/installment-plans/<pid>/default")
def default_plan(pid):
    require_auth({"Registrar"})
    p = _get_plan_or_404(pid)

    if p["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Plan is not OPEN.")
    # Operator-asserted missed-due-date default; requires amount still outstanding.
    if p["amount_paid_cents"] >= p["total_financed_cents"]:
        raise err("ERR_INVALID_STATE", "Plan is fully paid; cannot default.")

    p["status"] = "DEFAULTED"
    db.touch(p)

    # Cascade: if parent enrollment is ACTIVE or PENDING_PAYMENT, cancel it
    # (releasing seat + promoting waitlist).
    enrollment = db.enrollments.get(p["enrollment_id"])
    if enrollment is not None and enrollment["status"] in ("ACTIVE", "PENDING_PAYMENT"):
        cohort = db.cohorts[enrollment["cohort_id"]]
        core.cancel_enrollment(enrollment)
        db.touch(cohort)
    return response.success(serialize.installment_plan(p), 200)
