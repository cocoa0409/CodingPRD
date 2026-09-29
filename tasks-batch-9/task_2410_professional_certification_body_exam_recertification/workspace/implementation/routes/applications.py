"""EligibilityApplication endpoints (PRD 3.6)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CANDIDATE,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_EXAM_OPERATIONS,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    req_bool,
    req_enum,
    req_int,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import calc, lookup
from util import add_days

bp = Blueprint("applications", __name__)

EDUCATION_CREDENTIALS = ("DIPLOMA", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE")
DIMENSIONS = ("EDUCATION", "EXPERIENCE")
OUTCOMES = ("PASS", "FAIL")


def _stamp_eligibility(application, program):
    application["eligibility_expires_on"] = add_days(
        DB.now(), program["eligibility_valid_days"]
    )


@bp.post("/applications")
@api
def create_application():
    actor = authenticate([ROLE_CANDIDATE, ROLE_ELIGIBILITY_REVIEWER])
    raw = peek_body()
    payload = raw or {}

    # Layer 4: body references resolve before anything else about the payload.
    candidate = lookup.candidate(payload.get("candidate_id"))
    program = lookup.program(payload.get("program_id"))

    # Layer 5: a Candidate-role caller may only submit their own application.
    if actor.role == ROLE_CANDIDATE and candidate["id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    body = ensure_body(raw)
    education_credential = req_enum(body, "education_credential", EDUCATION_CREDENTIALS)
    education_completion_year = req_int(body, "education_completion_year",
                                       minimum=1000, maximum=9999)
    experience_months = req_int(body, "experience_months", minimum=0)
    attestation_signed = req_bool(body, "attestation_signed")
    if attestation_signed is not True:
        raise ApiError("ERR_INVALID_REQUEST")

    # Layer 13: applications may only cite an ACTIVE program.
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE")

    application = new_record(
        candidate_id=candidate["id"],
        program_id=program["id"],
        education_credential=education_credential,
        education_completion_year=education_completion_year,
        experience_months=experience_months,
        attestation_signed=True,
        education_status="PENDING",
        experience_status="PENDING",
        status="SUBMITTED",
        verifier_user_ids=[],
        auditor_user_id=None,
        audit_sequence_number=None,
        eligibility_expires_on=None,
        denial_reason=None,
    )
    mark_created(application)
    DB.applications[application["id"]] = application
    return created_response(serialize.application(application))


@bp.get("/applications/<application_id>")
@api
def read_application(application_id):
    authenticate([ROLE_ELIGIBILITY_REVIEWER, ROLE_CANDIDATE, ROLE_EXAM_OPERATIONS,
                  ROLE_PROGRAM_ADMIN])
    return object_response(serialize.application(lookup.application(application_id)))


@bp.get("/applications")
@api
def list_applications():
    authenticate([ROLE_ELIGIBILITY_REVIEWER, ROLE_CANDIDATE, ROLE_EXAM_OPERATIONS,
                  ROLE_PROGRAM_ADMIN])
    limit, offset = read_pagination()
    rows = ordered(DB.applications.values())
    rows = apply_filters(rows, {
        "candidate_id": "candidate_id",
        "program_id": "program_id",
        "status": "status",
        "education_status": "education_status",
        "experience_status": "experience_status",
    })
    return paginate(rows, serialize.application, limit, offset)


@bp.post("/applications/<application_id>/verify")
@api
def verify_application(application_id):
    actor = authenticate([ROLE_ELIGIBILITY_REVIEWER])
    application = lookup.application(application_id)
    body = ensure_body(peek_body())
    dimension = req_enum(body, "dimension", DIMENSIONS)
    outcome = req_enum(body, "outcome", OUTCOMES)
    opt_str(body, "review_note")

    if application["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE")

    field = "education_status" if dimension == "EDUCATION" else "experience_status"
    # Layer 18: dimension freshness.
    if application[field] != "PENDING":
        raise ApiError("ERR_DIMENSION_ALREADY_VERIFIED")

    program = DB.programs[application["program_id"]]
    application["verifier_user_ids"] = application["verifier_user_ids"] + [
        {"dimension": dimension, "user_id": actor.user_id}
    ]

    if dimension == "EDUCATION":
        clears = calc.education_ok(application, program, DB.now().year)
        denial_reason = "EDUCATION_FAILED"
    else:
        clears = calc.experience_ok(application, program)
        denial_reason = "EXPERIENCE_FAILED"

    verified = (outcome == "PASS" and clears)
    application[field] = "VERIFIED" if verified else "FAILED"

    if not verified:
        application["status"] = "DENIED"
        application["denial_reason"] = denial_reason
    elif (application["education_status"] == "VERIFIED"
            and application["experience_status"] == "VERIFIED"):
        # The join: deterministic every-Nth audit sampling.
        program["verified_application_counter"] += 1
        touch(program)
        sequence = program["verified_application_counter"]
        application["audit_sequence_number"] = sequence
        if sequence % program["audit_every_nth"] == 0:
            application["status"] = "AUDIT_SELECTED"
        else:
            application["status"] = "APPROVED"
            _stamp_eligibility(application, program)
    else:
        application["status"] = "UNDER_REVIEW"

    touch(application)
    return object_response(serialize.application(application))


@bp.post("/applications/<application_id>/audit-decision")
@api
def decide_application_audit(application_id):
    actor = authenticate([ROLE_ELIGIBILITY_REVIEWER])
    application = lookup.application(application_id)
    body = ensure_body(peek_body())
    outcome = req_enum(body, "outcome", OUTCOMES)
    opt_str(body, "audit_note")

    if application["status"] != "AUDIT_SELECTED":
        raise ApiError("ERR_INVALID_STATE")

    # Layer 19: an auditor may never audit their own verification.
    if actor.user_id in [entry["user_id"] for entry in application["verifier_user_ids"]]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    program = DB.programs[application["program_id"]]
    application["auditor_user_id"] = actor.user_id
    if outcome == "PASS":
        application["status"] = "APPROVED"
        _stamp_eligibility(application, program)
    else:
        application["status"] = "DENIED"
        application["denial_reason"] = "AUDIT_FAILED"
    touch(application)
    return object_response(serialize.application(application))
