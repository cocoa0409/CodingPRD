"""SafeHarborProgram and SafeHarborAssessment endpoints (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint, g

from constants import (
    ASSESSMENT_STATUSES,
    DEFAULT_ANNUAL_ASSESSMENT_REQUIRED,
    DEFAULT_ASSESSMENT_GRACE_DAYS,
    DEFAULT_ASSESSMENT_VALIDITY_DAYS,
    MAX_REMEDIATION_ROUNDS,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SAFE_HARBOR_ASSESSOR,
    ROLE_SAFE_HARBOR_CERTIFIER,
)
from db import db, now, ordered, touch
from errors import fail
from helpers import apply_filters, base_row, bump_service, resolve, resolve_body_fk
from middleware import (
    authenticate,
    body,
    opt_bool,
    opt_int,
    opt_string,
    req_bool,
    req_enum,
    req_int,
    req_string,
)
from response import created, ok, paginate
from serializers import assessment_out, program_out

bp = Blueprint("safe_harbor", __name__)

# from -> to : the single role permitted for that transition (PRD §3.10)
TRANSITION_ACTOR = {
    ("DRAFT", "SUBMITTED"): ROLE_SAFE_HARBOR_ASSESSOR,
    ("SUBMITTED", "REMEDIATION_REQUIRED"): ROLE_SAFE_HARBOR_CERTIFIER,
    ("REMEDIATION_REQUIRED", "SUBMITTED"): ROLE_SAFE_HARBOR_ASSESSOR,
    ("REMEDIATION_REQUIRED", "FAILED"): ROLE_SAFE_HARBOR_CERTIFIER,
}


@bp.post("/safe-harbor-programs")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_program():
    data = body()
    program = base_row()
    program.update(
        {
            "program_name": req_string(data, "program_name"),
            "regulator_approved": req_bool(data, "regulator_approved"),
            "annual_assessment_required": opt_bool(
                data, "annual_assessment_required", DEFAULT_ANNUAL_ASSESSMENT_REQUIRED
            ),
            "assessment_validity_days": opt_int(
                data, "assessment_validity_days", DEFAULT_ASSESSMENT_VALIDITY_DAYS
            ),
            "assessment_grace_days": opt_int(
                data, "assessment_grace_days", DEFAULT_ASSESSMENT_GRACE_DAYS
            ),
        }
    )
    db.safe_harbor_programs[program["id"]] = program
    return created(program_out(program))


@bp.post("/safe-harbor-assessments")
@authenticate(ROLE_SAFE_HARBOR_ASSESSOR)
def create_assessment():
    data = body()
    service = resolve_body_fk("service", data, "service_id")
    program = resolve_body_fk("program", data, "program_id")
    assessment_year = req_int(data, "assessment_year")

    # step 19: at most one assessment per (service, program, year)
    for existing in db.safe_harbor_assessments.values():
        if (
            existing["service_id"] == service["id"]
            and existing["program_id"] == program["id"]
            and existing["assessment_year"] == assessment_year
        ):
            fail("ERR_ASSESSMENT_YEAR_DUPLICATE")

    assessment = base_row()
    assessment.update(
        {
            "service_id": service["id"],
            "program_id": program["id"],
            "assessment_year": assessment_year,
            "preparer_user_id": g.user_id,
            "certifier_user_id": None,
            "findings_open_count": 0,
            "remediation_round": 0,
            "status": "DRAFT",
            "certified_at": None,
            "expires_at": None,
            "remediation_note": None,
        }
    )
    db.safe_harbor_assessments[assessment["id"]] = assessment
    bump_service(service)
    return created(assessment_out(assessment))


@bp.get("/safe-harbor-assessments")
@authenticate(
    ROLE_COMPLIANCE_OFFICER, ROLE_SAFE_HARBOR_ASSESSOR, ROLE_SAFE_HARBOR_CERTIFIER
)
def list_assessments():
    rows = ordered(list(db.safe_harbor_assessments.values()))
    rows = apply_filters(
        rows,
        {
            "service_id": "service_id",
            "program_id": "program_id",
            "assessment_year": "assessment_year",
            "status": "status",
        },
    )
    return paginate(rows, assessment_out)


@bp.get("/safe-harbor-assessments/<assessment_id>")
@authenticate(
    ROLE_COMPLIANCE_OFFICER, ROLE_SAFE_HARBOR_ASSESSOR, ROLE_SAFE_HARBOR_CERTIFIER
)
def get_assessment(assessment_id):
    return ok(assessment_out(resolve("assessment", assessment_id)))


@bp.post("/safe-harbor-assessments/<assessment_id>/status")
@authenticate(ROLE_SAFE_HARBOR_ASSESSOR, ROLE_SAFE_HARBOR_CERTIFIER)
def set_assessment_status(assessment_id):
    assessment = resolve("assessment", assessment_id)
    data = body()
    to_status = req_enum(data, "to_status", ASSESSMENT_STATUSES)

    findings_open_count = None
    if to_status == "SUBMITTED":
        findings_open_count = req_int(data, "findings_open_count")

    transition = (assessment["status"], to_status)
    if transition not in TRANSITION_ACTOR:
        fail("ERR_INVALID_STATE")
    if g.role != TRANSITION_ACTOR[transition]:
        fail("ERR_TRANSITION_ROLE_NOT_PERMITTED")

    service = db.online_services[assessment["service_id"]]
    program = db.safe_harbor_programs.get(assessment["program_id"])

    if transition == ("DRAFT", "SUBMITTED"):
        if program is not None and program["annual_assessment_required"] is not True:
            fail("ERR_ASSESSMENT_NOT_REQUIRED")
        assessment["findings_open_count"] = findings_open_count
        assessment["status"] = to_status
        touch(assessment)
        return ok(assessment_out(assessment))

    if transition == ("SUBMITTED", "REMEDIATION_REQUIRED"):
        if assessment["remediation_round"] >= MAX_REMEDIATION_ROUNDS:
            fail("ERR_REMEDIATION_ROUNDS_EXHAUSTED")
        note = opt_string(data, "remediation_note")
        if note is not None:
            assessment["remediation_note"] = note
        assessment["remediation_round"] += 1
        assessment["status"] = to_status
        touch(assessment)
        return ok(assessment_out(assessment))

    if transition == ("REMEDIATION_REQUIRED", "SUBMITTED"):
        assessment["findings_open_count"] = findings_open_count
        assessment["status"] = to_status
        touch(assessment)
        return ok(assessment_out(assessment))

    # ("REMEDIATION_REQUIRED", "FAILED") — only once the loop is closed
    if assessment["remediation_round"] < MAX_REMEDIATION_ROUNDS:
        fail("ERR_INVALID_STATE")
    assessment["status"] = "FAILED"
    touch(assessment)
    bump_service(service)
    return ok(assessment_out(assessment))


@bp.post("/safe-harbor-assessments/<assessment_id>/certify")
@authenticate(ROLE_SAFE_HARBOR_CERTIFIER)
def certify_assessment(assessment_id):
    assessment = resolve("assessment", assessment_id)

    # step 9
    if assessment["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")

    program = db.safe_harbor_programs[assessment["program_id"]]
    service = db.online_services[assessment["service_id"]]

    # step 23 clauses, then step 24 — this order is normative.
    if assessment["findings_open_count"] != 0:
        fail("ERR_OPEN_FINDINGS_PRESENT")
    if program["regulator_approved"] is not True:
        fail("ERR_PROGRAM_NOT_REGULATOR_APPROVED")
    if g.user_id == assessment["preparer_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    certified_at = now()
    assessment["status"] = "CERTIFIED"
    assessment["certifier_user_id"] = g.user_id
    assessment["certified_at"] = certified_at
    assessment["expires_at"] = certified_at + timedelta(
        days=program["assessment_validity_days"]
    )
    touch(assessment)
    bump_service(service)
    return ok(assessment_out(assessment))
