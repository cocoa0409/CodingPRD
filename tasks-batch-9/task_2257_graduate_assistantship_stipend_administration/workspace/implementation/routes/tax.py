"""Tuition-benefit tax assessments (PRD 3.9)."""
from flask import Blueprint

import serialize
import validate as v
from db import db, insert, update, force_update
from errors import ApiError
from middleware import authenticate, require_owner
from response import ok, created, ok_list
from services import effects, queries

bp = Blueprint("tax", __name__)

ASSESSMENT_STATUSES = ("PROVISIONAL", "FINAL", "AMENDED", "SUPERSEDED")
IN_FLIGHT_LIFECYCLE = ("DRAFT", "SUBMITTED", "RETURNED", "FUNDING_VERIFIED")

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "StudentUser"]


@bp.post("/tax-assessments")
def create_assessment():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    term_ref = v.ref_value(body, "term_id")
    term = queries.term_or_404(term_ref) if term_ref is not None else None
    student_ref = v.ref_value(body, "student_id")
    student = queries.student_or_404(student_ref) if student_ref is not None else None

    student_id = v.field_id(body, "student_id")
    term_id = v.field_id(body, "term_id")
    expected_version = v.field_int(body, "expected_student_version", minimum=0)

    if expected_version != student["version"]:
        raise ApiError("ERR_STALE_STUDENT_VERSION",
                       "expected_student_version %s does not match the current version %s"
                       % (expected_version, student["version"]))

    siblings = [row for row in db.tax_assessments.values()
                if row["student_id"] == student_id and row["term_id"] == term_id]
    for row in siblings:
        if row["status"] in ("FINAL", "AMENDED"):
            raise ApiError("ERR_ASSESSMENT_ALREADY_FINAL",
                           "An assessment for this student and term is already %s"
                           % row["status"])
    for row in sorted(siblings, key=lambda r: r["_seq"]):
        if row["status"] == "PROVISIONAL":
            update(row, status="SUPERSEDED")

    cap = queries.term_exempt_cap(term_id)
    benefit, exempt, taxable, withholding = effects.assess_term_provisional(
        student_id, term_id, cap)

    row = insert(db.tax_assessments, {
        "student_id": student_id,
        "term_id": term_id,
        "tax_calendar_year": term["tax_calendar_year"],
        "variant_applied": "TERM_PROVISIONAL",
        "benefit_cents": benefit,
        "exempt_cents": exempt,
        "taxable_cents": taxable,
        "imputed_withholding_cents": withholding,
        "status": "PROVISIONAL",
        "amendment_reason": None,
    })
    force_update(student)
    return created(serialize.assessment(row))


@bp.get("/tax-assessments/<assessment_id>")
def read_assessment(assessment_id):
    actor_id, role = authenticate(READ_ROLES)
    assessment = queries.assessment_or_404(assessment_id)
    require_owner(actor_id, role, assessment["student_id"])
    return ok(serialize.assessment(assessment))


@bp.get("/tax-assessments")
def list_assessments():
    actor_id, role = authenticate(READ_ROLES)
    student_id = v.query_str("student_id")
    if role == "StudentUser":
        if student_id is not None and student_id != actor_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "A StudentUser may only list its own tax assessments")
        student_id = actor_id
    term_id = v.query_str("term_id")
    tax_calendar_year = v.query_int("tax_calendar_year", None)
    status = v.query_enum("status", ASSESSMENT_STATUSES)

    rows = list(db.tax_assessments.values())
    if student_id:
        rows = [r for r in rows if r["student_id"] == student_id]
    if term_id:
        rows = [r for r in rows if r["term_id"] == term_id]
    if tax_calendar_year is not None:
        rows = [r for r in rows if r["tax_calendar_year"] == tax_calendar_year]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, meta = v.paginate(queries.by_created(rows))
    return ok_list([serialize.assessment(r) for r in page], meta)


@bp.post("/tax-assessments/<assessment_id>/finalize")
def finalize_assessment(assessment_id):
    authenticate(["GradSchoolAdmin"])
    assessment = queries.assessment_or_404(assessment_id)
    if assessment["status"] not in ("PROVISIONAL", "AMENDED"):
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE",
                       "Only a PROVISIONAL or AMENDED assessment may be finalized, not %s"
                       % assessment["status"])
    if assessment["status"] == "PROVISIONAL":
        for appointment in queries.appointments_of_term(assessment["term_id"]):
            if (appointment["student_id"] == assessment["student_id"]
                    and appointment["lifecycle_status"] in IN_FLIGHT_LIFECYCLE):
                raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                               "An appointment of this student in this term is still %s"
                               % appointment["lifecycle_status"])

    cap = queries.term_exempt_cap(assessment["term_id"])
    benefit, exempt, taxable, withholding = effects.assess_calendar_year_final(
        assessment, cap)
    update(assessment,
           status="FINAL",
           variant_applied="CALENDAR_YEAR_FINAL",
           benefit_cents=benefit,
           exempt_cents=exempt,
           taxable_cents=taxable,
           imputed_withholding_cents=withholding)

    student = db.students.get(assessment["student_id"])
    if student is not None:
        effects.recompute_student_tax_ytd(student, assessment["tax_calendar_year"])
    return ok(serialize.assessment(assessment))


@bp.post("/tax-assessments/<assessment_id>/amend")
def amend_assessment(assessment_id):
    authenticate(["GradSchoolAdmin"])
    assessment = queries.assessment_or_404(assessment_id)
    body = v.body_dict()
    amendment_reason = v.field_str(body, "amendment_reason")

    if assessment["status"] != "FINAL":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE",
                       "Only a FINAL assessment may be amended, not %s" % assessment["status"])

    cap = queries.term_exempt_cap(assessment["term_id"])
    benefit, exempt, taxable, withholding = effects.assess_calendar_year_final(
        assessment, cap)
    if benefit == assessment["benefit_cents"]:
        raise ApiError("ERR_NO_ASSESSMENT_DELTA",
                       "The recomputed benefit is unchanged; nothing to amend")

    update(assessment,
           status="AMENDED",
           amendment_reason=amendment_reason,
           benefit_cents=benefit,
           exempt_cents=exempt,
           taxable_cents=taxable,
           imputed_withholding_cents=withholding)

    student = db.students.get(assessment["student_id"])
    if student is not None:
        effects.recompute_student_tax_ytd(student, assessment["tax_calendar_year"])
    return ok(serialize.assessment(assessment))
