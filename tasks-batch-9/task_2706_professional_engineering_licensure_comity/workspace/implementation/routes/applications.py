"""Licensure applications (PRD 3.2, 3.4)."""
from flask import Blueprint

import calc
import cascade
import db
import guards
import schemas
from errors import ApiError
from middleware import actor, endpoint
from response import created, ok
from routes.roster import has_active_license, issue_license
from util import add_days
from validate import (body, opt_bool, q_enum, q_str, req_bool, req_dt, req_enum,
                      req_id, req_int, req_str)

bp = Blueprint("applications", __name__)

PATHWAYS = ("STANDARD_EXAM", "COMITY")
EXAM_CODES = ("PE_CIVIL", "PE_MECHANICAL", "PE_ELECTRICAL")
DEGREE_LEVELS = ("BS", "MS", "PHD")
ACCREDITATION_FINDINGS = ("EABET_ACCREDITED", "NON_ACCREDITED_EVALUATED", "REJECTED")
APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "DEFICIENT",
                        "EXAM_APPROVED", "LICENSE_ISSUED", "DENIED", "WITHDRAWN")
READ_ROLES = ("Applicant", "BoardReviewer", "BoardLicensingOfficer", "BoardSecretary")


def _fetch(application_id):
    return schemas.fetch("applications", application_id, "ERR_APPLICATION_NOT_FOUND")


def _state(application, allowed):
    if application["status"] not in allowed:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "application status %s does not permit this transition"
                       % application["status"])


@bp.post("/applications")
@endpoint("Applicant")
def create_application():
    data = body()
    engineer_id = req_id(data, "engineer_id")
    pathway = req_enum(data, "pathway", PATHWAYS)
    exam_code = req_enum(data, "exam_code", EXAM_CODES)
    req_enum(data, "degree_level", DEGREE_LEVELS)
    expedite_requested = opt_bool(data, "expedite_requested", default=False)
    schemas.fetch("engineers", engineer_id, "ERR_ENGINEER_NOT_FOUND")
    guards.owned_by_caller(engineer_id)
    application = db.insert("applications", {
        "engineer_id": engineer_id,
        "pathway": pathway,
        "exam_code": exam_code,
        "expedite_requested": expedite_requested,
        "status": "DRAFT",
        "education_status": "NOT_EVALUATED",
        "degree_level": None,
        "provisional_experience_months": 0,
        "verified_experience_months": 0,
        "credit_determined_by_user_id": None,
        "reviewer_user_id": None,
        "deficiency_cycle_count": 0,
        "deficiency_reason": None,
        "deficiency_due_at": None,
        "fee_assessment_cents": 0,
        "fee_paid_cents": 0,
        "submitted_at": None,
        "ncees_record_status": "NOT_REQUESTED",
        "ncees_verified_exam_pass": False,
        "ncees_verified_years_licensed": 0,
        "ncees_disciplinary_history_count": 0,
        "ncees_record_expires_on": None,
        "denial_reason": None,
    })
    application["fee_assessment_cents"] = calc.fee_assessment(
        application)["assessment_total_cents"]
    return created(schemas.view(application, schemas.APPLICATION))


@bp.get("/applications/<application_id>")
@endpoint(*READ_ROLES)
def read_application(application_id):
    return ok(schemas.view(_fetch(application_id), schemas.APPLICATION))


@bp.get("/applications")
@endpoint(*READ_ROLES)
def list_applications():
    engineer_id = q_str("engineer_id")
    status = q_enum("status", APPLICATION_STATUSES)
    pathway = q_enum("pathway", PATHWAYS)

    def keep(row):
        if engineer_id is not None and row["engineer_id"] != engineer_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if pathway is not None and row["pathway"] != pathway:
            return False
        return True

    return schemas.listing("applications", schemas.APPLICATION, keep)


@bp.post("/applications/<application_id>/education-evaluation")
@endpoint("BoardReviewer")
def education_evaluation(application_id):
    data = body()
    degree_level = req_enum(data, "degree_level", DEGREE_LEVELS)
    finding = req_enum(data, "accreditation_finding", ACCREDITATION_FINDINGS)
    application = _fetch(application_id)
    changes = {"degree_level": degree_level, "education_status": finding}
    if finding == "REJECTED" and application["status"] == "DRAFT":
        changes["status"] = "DENIED"
        changes["denial_reason"] = "EDUCATION_REJECTED"
    db.write(application, **changes)
    for record in calc.records_of(application["id"]):
        calc.refresh_record_derived(record)
    calc.recompute_provisional(application)
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/ncees-verification")
@endpoint("TestingService")
def ncees_verification(application_id):
    data = body()
    transmitted_id = req_str(data, "ncees_record_id", max_len=20, min_len=1)
    req_str(data, "source_jurisdiction")
    verified_exam_pass = req_bool(data, "verified_exam_pass")
    verified_years_licensed = req_int(data, "verified_years_licensed", minimum=0)
    disciplinary_history_count = req_int(data, "disciplinary_history_count", minimum=0)
    record_expires_on = req_dt(data, "record_expires_on")
    application = _fetch(application_id)
    engineer = db.get("engineers", application["engineer_id"])
    roster_id = engineer["ncees_record_id"] if engineer else None
    matched = roster_id is not None and transmitted_id == roster_id
    db.write(application,
             ncees_record_status="MATCHED" if matched else "MISMATCH",
             ncees_verified_exam_pass=verified_exam_pass,
             ncees_verified_years_licensed=verified_years_licensed,
             ncees_disciplinary_history_count=disciplinary_history_count,
             ncees_record_expires_on=record_expires_on)
    if application["status"] == "DRAFT":
        calc.reassess_fee(application)
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.get("/applications/<application_id>/fee-assessment")
@endpoint("Applicant", "BoardReviewer", "BoardLicensingOfficer")
def read_fee_assessment(application_id):
    application = _fetch(application_id)
    return ok(calc.fee_assessment(application))


@bp.post("/applications/<application_id>/payments")
@endpoint("Applicant")
def record_payment(application_id):
    data = body()
    amount_cents = req_int(data, "amount_cents", minimum=0)
    application = _fetch(application_id)
    guards.owned_by_caller(application["engineer_id"])
    db.write(application,
             fee_paid_cents=application["fee_paid_cents"] + amount_cents)
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/submit")
@endpoint("Applicant")
def submit_application(application_id):
    application = _fetch(application_id)
    guards.owned_by_caller(application["engineer_id"])
    _state(application, ("DRAFT",))
    if application["education_status"] not in ("EABET_ACCREDITED",
                                               "NON_ACCREDITED_EVALUATED"):
        raise ApiError("ERR_EDUCATION_NOT_EVALUATED",
                       "the education evaluation has not been completed")
    records = calc.records_of(application["id"])
    if not records:
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "at least one experience block must be attached")
    if application["fee_paid_cents"] < application["fee_assessment_cents"]:
        raise ApiError("ERR_FEE_UNPAID", "the assessed application fee is unpaid")
    calc.reassess_fee(application)
    db.write(application, status="SUBMITTED", submitted_at=db.clock())
    for record in records:
        if record["verification_status"] == "UNVERIFIED" and calc.references_of(record["id"]):
            db.write(record, verification_status="PENDING_VERIFICATION")
    calc.recompute_provisional(application)
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/start-review")
@endpoint("BoardReviewer")
def start_review(application_id):
    application = _fetch(application_id)
    _state(application, ("SUBMITTED",))
    db.write(application, status="UNDER_REVIEW", reviewer_user_id=actor())
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/deficiency")
@endpoint("BoardReviewer")
def issue_deficiency(application_id):
    data = body()
    reason = req_str(data, "deficiency_reason")
    application = _fetch(application_id)
    _state(application, ("UNDER_REVIEW",))
    if application["deficiency_cycle_count"] >= calc.MAX_DEFICIENCY_CYCLES:
        raise ApiError("ERR_DEFICIENCY_LIMIT_REACHED",
                       "the board tolerates three deficiency cycles only")
    db.write(application,
             status="DEFICIENT",
             deficiency_cycle_count=application["deficiency_cycle_count"] + 1,
             deficiency_reason=reason,
             deficiency_due_at=add_days(db.clock(), calc.DEFICIENCY_RESPONSE_DAYS))
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/respond-deficiency")
@endpoint("Applicant")
def respond_deficiency(application_id):
    data = body()
    req_str(data, "response_note")
    application = _fetch(application_id)
    guards.owned_by_caller(application["engineer_id"])
    _state(application, ("DEFICIENT",))
    due_at = application["deficiency_due_at"]
    if due_at is not None and db.clock() > due_at:
        raise ApiError("ERR_DEFICIENCY_RESPONSE_WINDOW_CLOSED",
                       "the deficiency response window has closed")
    db.write(application, status="UNDER_REVIEW", deficiency_reason=None,
             deficiency_due_at=None)
    calc.recompute_provisional(application)
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/credit-determination")
@endpoint("BoardReviewer", "BoardLicensingOfficer")
def credit_determination(application_id):
    application = _fetch(application_id)
    calc.recompute_verified(application)
    db.write(application, credit_determined_by_user_id=actor())
    return ok(schemas.view(application, schemas.APPLICATION))


def _references_all_adjudicated(application):
    for ref in calc.references_of_application(application["id"]):
        if ref["status"] in ("REQUESTED", "SUBMITTED"):
            return False
    return True


def _require_adjudicated_and_determined(application):
    if application["credit_determined_by_user_id"] is None:
        raise ApiError("ERR_REFERENCE_NOT_ACCEPTED",
                       "the credit determination has not been run")
    if not _references_all_adjudicated(application):
        raise ApiError("ERR_REFERENCE_NOT_ACCEPTED",
                       "a verification request is still outstanding")


def _require_experience(application):
    if application["verified_experience_months"] < calc.REQUIRED_EXPERIENCE_MONTHS:
        raise ApiError("ERR_EXPERIENCE_INSUFFICIENT",
                       "at least 48 verified months of experience are required")


@bp.post("/applications/<application_id>/approve-exam")
@endpoint("BoardLicensingOfficer")
def approve_exam(application_id):
    application = _fetch(application_id)
    guards.segregation(application["credit_determined_by_user_id"])
    _state(application, ("UNDER_REVIEW",))
    if application["pathway"] != "STANDARD_EXAM":
        raise ApiError("ERR_PATHWAY_MISMATCH",
                       "examination approval is only available on an examination file")
    _require_adjudicated_and_determined(application)
    _require_experience(application)
    db.write(application, status="EXAM_APPROVED")
    authorization = db.insert("exam_authorizations", {
        "application_id": application["id"],
        "exam_code": application["exam_code"],
        "status": "APPROVED_TO_SIT",
        "authorization_expires_at": add_days(db.clock(),
                                             calc.AUTHORIZATION_VALID_DAYS),
        "attempt_number": 1,
        "raw_score": None,
        "result": "PENDING",
        "retake_eligible_at": None,
        "ncees_transmission_id": None,
    })
    return created(schemas.view(authorization, schemas.EXAM_AUTHORIZATION))


@bp.post("/applications/<application_id>/issue-license")
@endpoint("BoardLicensingOfficer")
def issue_license_for_application(application_id):
    application = _fetch(application_id)
    guards.segregation(application["credit_determined_by_user_id"])
    _state(application, ("UNDER_REVIEW", "EXAM_APPROVED"))
    comity_door = application["status"] == "UNDER_REVIEW"
    if comity_door:
        if application["pathway"] != "COMITY":
            raise ApiError("ERR_PATHWAY_MISMATCH",
                           "direct issuance is only available on a comity file")
        if (application["ncees_record_status"] != "MATCHED"
                or not application["ncees_verified_exam_pass"]):
            raise ApiError("ERR_NCEES_RECORD_NOT_MATCHED",
                           "the national records packet does not match")
        expires_on = application["ncees_record_expires_on"]
        if expires_on is not None and db.clock() > expires_on:
            raise ApiError("ERR_NCEES_RECORD_EXPIRED",
                           "the national records packet is stale")
        if application["ncees_verified_years_licensed"] < calc.COMITY_MIN_YEARS_LICENSED:
            raise ApiError("ERR_COMITY_YEARS_INSUFFICIENT",
                           "at least four years licensed elsewhere are required")
        _require_adjudicated_and_determined(application)
        _require_experience(application)
    else:
        if application["pathway"] != "STANDARD_EXAM":
            raise ApiError("ERR_PATHWAY_MISMATCH",
                           "this file is not on the examination pathway")
        passed = any(a["status"] == "PASSED"
                     for a in calc.authorizations_of(application["id"]))
        if not passed:
            raise ApiError("ERR_EXAM_STATE_INVALID",
                           "the examination authorization has not passed")
        _require_experience(application)
    if has_active_license(application["engineer_id"]):
        raise ApiError("ERR_DUPLICATE_ACTIVE_LICENSE",
                       "engineer already holds an ACTIVE licence")
    license_row = issue_license(application["engineer_id"],
                                "COMITY" if comity_door else "STANDARD",
                                db.clock(), calc.DEFAULT_PDH_REQUIREMENT)
    db.write(application, status="LICENSE_ISSUED")
    return created(schemas.view(license_row, schemas.LICENSE))


@bp.post("/applications/<application_id>/deny")
@endpoint("BoardLicensingOfficer")
def deny_application(application_id):
    data = body()
    denial_reason = req_str(data, "denial_reason")
    application = _fetch(application_id)
    _state(application, ("UNDER_REVIEW", "DEFICIENT", "EXAM_APPROVED"))
    if application["status"] == "DEFICIENT":
        due_at = application["deficiency_due_at"]
        window_gone = due_at is not None and db.clock() > due_at
        cycles_gone = application["deficiency_cycle_count"] >= calc.MAX_DEFICIENCY_CYCLES
        if not (window_gone or cycles_gone):
            raise ApiError("ERR_APPLICATION_STATE_INVALID",
                           "the cure window is still live")
    elif application["status"] == "UNDER_REVIEW":
        if not (application["ncees_record_status"] == "MISMATCH"
                or application["education_status"] == "REJECTED"):
            raise ApiError("ERR_APPLICATION_STATE_INVALID",
                           "no ground for denial out of review")
    db.write(application, status="DENIED", denial_reason=denial_reason)
    cascade.teardown_authorizations(application)
    return ok(schemas.view(application, schemas.APPLICATION))


@bp.post("/applications/<application_id>/withdraw")
@endpoint("Applicant")
def withdraw_application(application_id):
    application = _fetch(application_id)
    guards.owned_by_caller(application["engineer_id"])
    _state(application, ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "DEFICIENT"))
    from_under_review = application["status"] == "UNDER_REVIEW"
    db.write(application, status="WITHDRAWN")
    for ref in calc.references_of_application(application["id"]):
        if ref["status"] == "REQUESTED":
            db.write(ref, status="REJECTED")
    if from_under_review:
        for record in calc.records_of(application["id"]):
            if record["verification_status"] == "PENDING_VERIFICATION":
                db.write(record, verification_status="UNVERIFIED")
    calc.recompute_verified(application)
    return ok(schemas.view(application, schemas.APPLICATION))
