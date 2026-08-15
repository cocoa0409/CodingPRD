"""Student endpoints: create, read, list (force-scoped for Student role),
and the advising sap-preview."""

from decimal import Decimal

from flask import Blueprint, g, request

import errors
from db import _new_id, now, store
from middleware import (
    authenticate,
    check_student_ownership,
    get_body,
    paginate,
    pagination_params,
    require_roles,
)
from response import success
from serializers import pub_student
from services import audit
from services.metrics import (
    compute_cumulatives,
    max_tf_attempted_only_exceeded,
    max_tf_projection_exceeded,
    round_half_up,
)

bp = Blueprint("students", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")


@bp.post("/sap/students")
def create_student():
    authenticate()
    require_roles("Registrar")
    body = get_body()

    # Existence (3): program_id resolves before uniqueness and well-formedness.
    program_id = body.get("program_id")
    if program_id is not None and program_id not in store.programs:
        errors.fail(errors.ERR_NOT_FOUND, "Program %s does not exist" % program_id)

    # Student number uniqueness (20) precedes body well-formedness (22).
    number = body.get("student_number")
    if isinstance(number, str):
        for s in store.students.values():
            if s["student_number"] == number:
                errors.fail(errors.ERR_STUDENT_NUMBER_CONFLICT,
                            "Student number %s already exists" % number)

    if not isinstance(number, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "student_number is required")
    full_name = body.get("full_name")
    if not isinstance(full_name, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "full_name is required")
    if not isinstance(program_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "program_id is required")

    ts = now()
    row = {
        "id": _new_id(),
        "student_number": number,
        "full_name": full_name,
        "program_id": program_id,
        "sap_status": "GOOD_STANDING",
        "cumulative_attempted_credits": 0,
        "cumulative_earned_credits": 0,
        "cumulative_quality_points": Decimal("0"),
        "cumulative_gpa_hours": 0,
        "cumulative_gpa": None,
        "pace_pct": None,
        "max_tf_exceeded": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.students[row["id"]] = row
    audit.record("STUDENT_CREATED", "Student", row["id"], row["id"], None, pub_student(row))
    return success(pub_student(row), status=201)


@bp.get("/sap/students/<sid>")
def get_student(sid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.students.get(sid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Student %s does not exist" % sid)
    check_student_ownership(row["id"])
    return success(pub_student(row))


@bp.get("/sap/students")
def list_students():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.students.values())
    # A Student caller is force-scoped to their own record.
    if g.user_role == "Student":
        rows = [s for s in rows if s["id"] == g.user_id]
    program_id = request.args.get("program_id")
    if program_id is not None:
        rows = [s for s in rows if s["program_id"] == program_id]
    sap_status = request.args.get("sap_status")
    if sap_status is not None:
        rows = [s for s in rows if s["sap_status"] == sap_status]
    page, meta = paginate(rows, limit, offset)
    return success([pub_student(s) for s in page], response_type="array", pagination=meta)


@bp.get("/sap/students/<sid>/sap-preview")
def sap_preview(sid):
    authenticate()
    require_roles("Student", "AidOfficer")
    student = store.students.get(sid)
    if student is None:
        errors.fail(errors.ERR_NOT_FOUND, "Student %s does not exist" % sid)
    check_student_ownership(student["id"])

    program = store.programs.get(student["program_id"])
    attempted, earned, _qp, _gh, gpa, pace = compute_cumulatives(student["id"])

    # Projected pace: every IN_PROGRESS row's attempted credits count as both
    # attempted AND earned (best case) on top of the official basis.
    in_progress_attempted = sum(
        e["attempted_credits"] for e in store.enrollments.values()
        if e["student_id"] == student["id"] and e["status"] == "IN_PROGRESS"
    )
    proj_attempted = attempted + in_progress_attempted
    proj_earned = earned + in_progress_attempted
    pace_projected = (
        round_half_up(Decimal(100) * proj_earned / proj_attempted, 2)
        if proj_attempted > 0 else None
    )

    data = {
        "pace_pct_official_basis": float(pace) if pace is not None else None,
        "pace_pct_projected": float(pace_projected) if pace_projected is not None else None,
        "cumulative_gpa": float(gpa) if gpa is not None else None,
        "max_tf_attempted_only_exceeded": max_tf_attempted_only_exceeded(program, attempted),
        "max_tf_projection_exceeded": max_tf_projection_exceeded(program, attempted, earned),
    }
    return success(data)
