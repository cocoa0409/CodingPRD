"""Intake, orientation, vouchers, learner reads and the skill-gain view."""

from decimal import Decimal

from flask import Blueprint, request

import calc
from core import (
    auth,
    body,
    by_created,
    clock,
    created,
    deny_scope,
    find_period,
    find_student,
    fmt_clock,
    new_record,
    ok,
    opt_bool,
    pagination,
    paginate,
    pub,
    req_enum,
    req_int,
    req_str,
    store,
    touch,
)
from errors import ApiError

bp = Blueprint("students", __name__)


@bp.post("/students")
def intake_student():
    auth("ProgramCoordinator", "StateAuthority")
    data = body()
    full_name = req_str(data, "full_name", max_len=120)
    email = req_str(data, "email")
    if "@" not in email:
        raise ApiError("ERR_INVALID_REQUEST")
    primary_track = req_enum(data, "primary_track", calc.PROGRAM_TRACKS)
    self_pay = opt_bool(data, "self_pay_authorized", False)
    for existing in store.students.values():
        if existing["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST")

    student = new_record(store.students, {
        "full_name": full_name,
        "email": email,
        "primary_track": primary_track,
        "intake_status": "INTAKE_STARTED",
        "orientation_completed_at": None,
        "placement_efl_level": None,
        "total_instructional_hours": 0.0,
        "voucher_granted_cents": 0,
        "voucher_balance_cents": 0,
        "voucher_spent_cents": 0,
        "self_pay_authorized": self_pay,
        "exam_fee_owed_cents": 0,
        "credential_status": "NONE",
        "active_enrollment_count": 0,
        "_total_instructional_hours": Decimal("0.00"),
    })
    return created(pub(student))


@bp.post("/students/<student_id>/orientation-completion")
def orientation_completion(student_id):
    auth("Registrar", "ProgramCoordinator")
    student = find_student(student_id)
    if student["intake_status"] != "INTAKE_STARTED":
        raise ApiError("ERR_INVALID_INTAKE_STATE")
    student["intake_status"] = "ORIENTED"
    student["orientation_completed_at"] = fmt_clock(clock())
    touch(student)
    return ok(pub(student))


@bp.post("/students/<student_id>/voucher-adjustments")
def voucher_adjustment(student_id):
    auth("ProgramCoordinator", "StateAuthority")
    student = find_student(student_id)
    data = body()
    delta = req_int(data, "delta_cents")
    if student["voucher_balance_cents"] + delta < 0:
        raise ApiError("ERR_VOUCHER_ADJUSTMENT_INVALID")
    student["voucher_granted_cents"] += delta
    student["voucher_balance_cents"] += delta
    touch(student)
    return ok(pub(student))


@bp.get("/students/<student_id>")
def read_student(student_id):
    role, user_id = auth("ProgramCoordinator", "StateAuthority", "Registrar",
                         "Instructor", "Student")
    student = find_student(student_id)
    if role == "Student" and user_id != student["id"]:
        deny_scope()
    return ok(pub(student))


@bp.get("/students")
def list_students():
    auth("ProgramCoordinator", "StateAuthority", "Registrar", "Instructor")
    limit, offset = pagination()
    rows = list(store.students.values())
    for key in ("intake_status", "primary_track", "credential_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginate(by_created(rows), limit, offset)


@bp.get("/students/<student_id>/skill-gain")
def skill_gain(student_id):
    auth("ProgramCoordinator", "StateAuthority", "Registrar")
    student = find_student(student_id)
    variant = request.args.get("variant")
    if variant is None:
        variant = "BEST_POST"
    elif variant not in calc.MSG_VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST")
    period = None
    period_id = request.args.get("funding_period_id")
    if period_id is not None:
        period = find_period(period_id)
    return ok(calc.msg_determination(student["id"], variant, period))
