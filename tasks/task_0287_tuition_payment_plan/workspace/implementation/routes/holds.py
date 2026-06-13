"""Hold routes (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import calc, domain
from services.listing import paginate_and_render
from services.serialize import hold_view

bp = Blueprint("holds", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


@bp.route("/institutions/holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.holds.get(hold_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Hold not found")
    return success(hold_view(record), status=200)


@bp.route("/institutions/holds", methods=["GET"])
def list_holds():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    student_id = request.args.get("student_id")
    enrollment_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    records = list(db.holds.values())
    if student_id is not None:
        records = [r for r in records if r["student_id"] == student_id]
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, hold_view)


@bp.route("/institutions/holds/<hold_id>/release", methods=["POST"])
def release_hold(hold_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    hold = db.holds.get(hold_id)
    if hold is None:
        raise err("ERR_NOT_FOUND", "Hold not found")
    if hold["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Hold must be ACTIVE to release")

    enrollment = db.enrollments[hold["enrollment_id"]]
    # Manual release only when delinquency cured (PRD §3.8): count < 3 AND
    # total overdue < 150000.
    count = enrollment["delinquent_installment_count"]
    total = domain.total_overdue_amount(enrollment)
    if count >= calc.DELINQUENCY_COUNT_LIMIT or total >= calc.DELINQUENCY_AMOUNT_LIMIT:
        raise err("ERR_DELINQUENCY_UNRESOLVED",
                  "Delinquency thresholds still tripped")

    hold["status"] = "RELEASED"
    db.touch(hold)
    student = db.students[hold["student_id"]]
    domain.recompute_student_hold(student)
    db.touch(student)

    return success(hold_view(hold), status=200)
