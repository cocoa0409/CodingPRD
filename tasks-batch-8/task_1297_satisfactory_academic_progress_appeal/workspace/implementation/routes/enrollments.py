"""TermEnrollment endpoints: create, read, list, post grades, amend grades.

Posting and amendment recompute the student's cumulative fields (bumping the
student version); amendment additionally supersedes any OFFICIAL evaluation
for the (student, term) pair and re-runs the per-student pipeline.
"""

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
from serializers import pub_enrollment, pub_evaluation
from services import audit
from services.metrics import recompute_student, to_decimal
from services.pipeline import run_student_pipeline

bp = Blueprint("enrollments", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@bp.post("/sap/term-enrollments")
def create_enrollment():
    authenticate()
    require_roles("Registrar")
    body = get_body()

    # Existence, left to right: student_id, then term_id.
    student_id = body.get("student_id")
    if student_id is not None and student_id not in store.students:
        errors.fail(errors.ERR_NOT_FOUND, "Student %s does not exist" % student_id)
    term_id = body.get("term_id")
    if term_id is not None and term_id not in store.terms:
        errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % term_id)

    # Enrollment creation requires an OPEN term.
    if term_id is not None and store.terms[term_id]["status"] != "OPEN":
        errors.fail(errors.ERR_INVALID_STATE, "Term is not OPEN for enrollment")

    if not isinstance(student_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "student_id is required")
    if not isinstance(term_id, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "term_id is required")
    attempted = body.get("attempted_credits")
    if not _is_int(attempted):
        errors.fail(errors.ERR_INVALID_REQUEST, "attempted_credits must be an integer")

    ts = now()
    row = {
        "id": _new_id(),
        "student_id": student_id,
        "term_id": term_id,
        "attempted_credits": attempted,
        "earned_credits": None,
        "quality_points": None,
        "gpa_hours": None,
        "status": "IN_PROGRESS",
        "amendment_count": 0,
        "amendment_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.enrollments[row["id"]] = row
    audit.record("ENROLLMENT_CREATED", "TermEnrollment", row["id"],
                 student_id, None, pub_enrollment(row))
    return success(pub_enrollment(row), status=201)


@bp.get("/sap/term-enrollments/<eid>")
def get_enrollment(eid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.enrollments.get(eid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "TermEnrollment %s does not exist" % eid)
    check_student_ownership(row["student_id"])
    return success(pub_enrollment(row))


@bp.get("/sap/term-enrollments")
def list_enrollments():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.enrollments.values())
    if g.user_role == "Student":
        rows = [e for e in rows if e["student_id"] == g.user_id]
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [e for e in rows if e["student_id"] == student_id]
    term_id = request.args.get("term_id")
    if term_id is not None:
        rows = [e for e in rows if e["term_id"] == term_id]
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    page, meta = paginate(rows, limit, offset)
    return success([pub_enrollment(e) for e in page], response_type="array", pagination=meta)


def _validate_outcome_fields(body):
    earned = body.get("earned_credits")
    if not _is_int(earned):
        errors.fail(errors.ERR_INVALID_REQUEST, "earned_credits must be an integer")
    qp = body.get("quality_points")
    if not _is_num(qp):
        errors.fail(errors.ERR_INVALID_REQUEST, "quality_points must be a number")
    gh = body.get("gpa_hours")
    if not _is_int(gh):
        errors.fail(errors.ERR_INVALID_REQUEST, "gpa_hours must be an integer")
    return earned, to_decimal(qp), gh


@bp.post("/sap/term-enrollments/<eid>/post")
def post_enrollment(eid):
    authenticate()
    require_roles("Registrar")
    row = store.enrollments.get(eid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "TermEnrollment %s does not exist" % eid)
    if row["status"] != "IN_PROGRESS":
        errors.fail(errors.ERR_INVALID_STATE, "Only an IN_PROGRESS enrollment can be posted")
    body = get_body()
    earned, qp, gh = _validate_outcome_fields(body)

    ts = now()
    before = pub_enrollment(row)
    row["earned_credits"] = earned
    row["quality_points"] = qp
    row["gpa_hours"] = gh
    row["status"] = "POSTED"
    row["updated_at"] = ts
    row["version"] += 1

    student = store.students.get(row["student_id"])
    if student is not None:
        recompute_student(student)
        student["updated_at"] = ts
        student["version"] += 1

    audit.record("ENROLLMENT_POSTED", "TermEnrollment", row["id"],
                 row["student_id"], before, pub_enrollment(row))
    return success(pub_enrollment(row))


@bp.post("/sap/term-enrollments/<eid>/amend")
def amend_enrollment(eid):
    authenticate()
    require_roles("Registrar")
    row = store.enrollments.get(eid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "TermEnrollment %s does not exist" % eid)
    if row["status"] not in ("POSTED", "AMENDED"):
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only a POSTED or AMENDED enrollment can be amended")
    body = get_body()
    earned, qp, gh = _validate_outcome_fields(body)
    reason = body.get("amendment_reason")
    if not isinstance(reason, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "amendment_reason is required")

    ts = now()
    before = pub_enrollment(row)
    row["earned_credits"] = earned
    row["quality_points"] = qp
    row["gpa_hours"] = gh
    row["status"] = "AMENDED"
    row["amendment_count"] += 1
    row["amendment_reason"] = reason
    row["updated_at"] = ts
    row["version"] += 1

    student = store.students.get(row["student_id"])
    if student is not None:
        recompute_student(student)
        student["updated_at"] = ts
        student["version"] += 1

    audit.record("ENROLLMENT_AMENDED", "TermEnrollment", row["id"],
                 row["student_id"], before, pub_enrollment(row))

    # Amendment-driven re-evaluation: supersede the OFFICIAL evaluation for
    # this (student, term), if any, and re-run the per-student pipeline.
    if student is not None:
        official = None
        for ev in store.evaluations.values():
            if (ev["student_id"] == student["id"] and ev["term_id"] == row["term_id"]
                    and ev["status"] == "OFFICIAL"):
                official = ev
                break
        if official is not None:
            ev_before = pub_evaluation(official)
            official["status"] = "SUPERSEDED"
            official["updated_at"] = ts
            official["version"] += 1
            audit.record("EVALUATION_SUPERSEDED", "SapEvaluation", official["id"],
                         student["id"], ev_before, pub_evaluation(official))
            term = store.terms.get(row["term_id"])
            if term is not None:
                run_student_pipeline(student, term)

    return success(pub_enrollment(row))
