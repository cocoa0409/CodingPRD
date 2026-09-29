"""Experience blocks and supervising-engineer verifications (PRD 3.3)."""
from flask import Blueprint

import calc
import cascade
import db
import guards
import schemas
from errors import ApiError
from middleware import actor, endpoint
from response import created, ok
from util import add_days, month_index
from validate import (body, q_enum, q_str, req_bool, req_enum, req_id, req_int,
                      req_month, req_str)

bp = Blueprint("experience", __name__)

RESPONSIBILITY_LEVELS = ("SUBORDINATE", "PROGRESSIVE", "RESPONSIBLE_CHARGE")
VERIFICATION_STATUSES = ("UNVERIFIED", "PENDING_VERIFICATION", "VERIFIED",
                         "DISPUTED", "RECANTED")
RELATIONSHIPS = ("DIRECT_SUPERVISOR", "PROJECT_MANAGER", "PEER")
REFERENCE_STATUSES = ("REQUESTED", "SUBMITTED", "ACCEPTED", "REJECTED", "RECANTED")
READ_ROLES = ("Applicant", "SupervisingEngineer", "BoardReviewer",
              "BoardLicensingOfficer")


@bp.post("/applications/<application_id>/experience-records")
@endpoint("Applicant")
def create_experience_record(application_id):
    data = body()
    employer_name = req_str(data, "employer_name", max_len=120)
    position_title = req_str(data, "position_title", max_len=120)
    period_start_month = req_month(data, "period_start_month")
    period_end_month = req_month(data, "period_end_month")
    responsibility_level = req_enum(data, "responsibility_level", RESPONSIBILITY_LEVELS)
    post_degree = req_bool(data, "post_degree")
    if month_index(period_end_month) < month_index(period_start_month):
        raise ApiError("ERR_INVALID_REQUEST",
                       "period_end_month may not precede period_start_month")
    application = schemas.fetch("applications", application_id,
                                "ERR_APPLICATION_NOT_FOUND")
    guards.owned_by_caller(application["engineer_id"])
    for existing in calc.records_of(application["id"]):
        if existing["verification_status"] == "RECANTED":
            continue
        if calc.months_overlap(period_start_month, period_end_month,
                               existing["period_start_month"],
                               existing["period_end_month"]):
            raise ApiError("ERR_EXPERIENCE_PERIOD_OVERLAP",
                           "the claimed months collide with an existing block")
    record = db.insert("experience_records", {
        "application_id": application["id"],
        "employer_name": employer_name,
        "position_title": position_title,
        "period_start_month": period_start_month,
        "period_end_month": period_end_month,
        "responsibility_level": responsibility_level,
        "post_degree": post_degree,
        "raw_months": 0,
        "credit_multiplier": 0,
        "credited_months": 0,
        "verification_status": "UNVERIFIED",
    })
    record["raw_months"] = calc.raw_months(record)
    record["credit_multiplier"] = calc.credit_multiplier(record)
    if application["status"] == "DRAFT":
        calc.reassess_fee(application)
    calc.recompute_provisional(application)
    return created(schemas.view(record, schemas.EXPERIENCE_RECORD))


@bp.get("/experience-records/<experience_record_id>")
@endpoint(*READ_ROLES)
def read_experience_record(experience_record_id):
    record = schemas.fetch("experience_records", experience_record_id,
                           "ERR_EXPERIENCE_RECORD_NOT_FOUND")
    return ok(schemas.view(record, schemas.EXPERIENCE_RECORD))


@bp.get("/experience-records")
@endpoint(*READ_ROLES)
def list_experience_records():
    application_id = q_str("application_id")
    verification_status = q_enum("verification_status", VERIFICATION_STATUSES)
    responsibility_level = q_enum("responsibility_level", RESPONSIBILITY_LEVELS)

    def keep(row):
        if application_id is not None and row["application_id"] != application_id:
            return False
        if verification_status is not None and row["verification_status"] != verification_status:
            return False
        if responsibility_level is not None and row["responsibility_level"] != responsibility_level:
            return False
        return True

    return schemas.listing("experience_records", schemas.EXPERIENCE_RECORD, keep)


# ------------------------------------------------------------------ references
def _application_of_record(record):
    return db.get("applications", record["application_id"])


@bp.post("/experience-records/<experience_record_id>/references")
@endpoint("Applicant")
def create_reference(experience_record_id):
    data = body()
    referee_engineer_id = req_id(data, "referee_engineer_id")
    relationship = req_enum(data, "relationship", RELATIONSHIPS)
    record = schemas.fetch("experience_records", experience_record_id,
                           "ERR_EXPERIENCE_RECORD_NOT_FOUND")
    schemas.fetch("engineers", referee_engineer_id, "ERR_ENGINEER_NOT_FOUND")
    application = _application_of_record(record)
    guards.owned_by_caller(application["engineer_id"])
    if referee_engineer_id == application["engineer_id"]:
        raise ApiError("ERR_SELF_REFERENCE_FORBIDDEN",
                       "an applicant may not vouch for themselves")
    reference = db.insert("references", {
        "experience_record_id": record["id"],
        "referee_engineer_id": referee_engineer_id,
        "relationship": relationship,
        "status": "REQUESTED",
        "evaluation_score": None,
        "months_confirmed": None,
        "responsibility_confirmed": None,
        "submitted_at": None,
        "recant_reason": None,
    })
    if application["submitted_at"] is not None and record["verification_status"] == "UNVERIFIED":
        db.write(record, verification_status="PENDING_VERIFICATION")
    return created(schemas.view(reference, schemas.REFERENCE))


@bp.get("/references/<reference_id>")
@endpoint(*READ_ROLES)
def read_reference(reference_id):
    reference = schemas.fetch("references", reference_id, "ERR_REFERENCE_NOT_FOUND")
    return ok(schemas.view(reference, schemas.REFERENCE))


@bp.get("/references")
@endpoint(*READ_ROLES)
def list_references():
    experience_record_id = q_str("experience_record_id")
    referee_engineer_id = q_str("referee_engineer_id")
    status = q_enum("status", REFERENCE_STATUSES)

    def keep(row):
        if experience_record_id is not None and row["experience_record_id"] != experience_record_id:
            return False
        if referee_engineer_id is not None and row["referee_engineer_id"] != referee_engineer_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return schemas.listing("references", schemas.REFERENCE, keep)


@bp.post("/references/<reference_id>/submit")
@endpoint("SupervisingEngineer")
def submit_reference(reference_id):
    data = body()
    evaluation_score = req_int(data, "evaluation_score", minimum=1, maximum=5)
    months_confirmed = req_int(data, "months_confirmed", minimum=0)
    responsibility_confirmed = req_bool(data, "responsibility_confirmed")
    reference = schemas.fetch("references", reference_id, "ERR_REFERENCE_NOT_FOUND")
    guards.owned_by_caller(reference["referee_engineer_id"])
    if reference["status"] != "REQUESTED":
        raise ApiError("ERR_REFERENCE_STATE_INVALID",
                       "only a REQUESTED verification may be answered")
    record = db.get("experience_records", reference["experience_record_id"])
    if record["verification_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_REFERENCE_STATE_INVALID",
                       "the experience block is not awaiting verification")
    if not any(row["engineer_id"] == reference["referee_engineer_id"]
               and row["status"] == "ACTIVE"
               for row in db.store["licenses"].values()):
        raise ApiError("ERR_REFEREE_LICENSE_INACTIVE",
                       "the referee does not hold an ACTIVE licence")
    db.write(reference, status="SUBMITTED", evaluation_score=evaluation_score,
             months_confirmed=months_confirmed,
             responsibility_confirmed=responsibility_confirmed,
             submitted_at=db.clock())
    return ok(schemas.view(reference, schemas.REFERENCE))


@bp.post("/references/<reference_id>/evaluate")
@endpoint("BoardReviewer")
def evaluate_reference(reference_id):
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "REJECT"))
    reference = schemas.fetch("references", reference_id, "ERR_REFERENCE_NOT_FOUND")
    if reference["status"] != "SUBMITTED":
        raise ApiError("ERR_REFERENCE_STATE_INVALID",
                       "only a SUBMITTED verification may be adjudicated")
    record = db.get("experience_records", reference["experience_record_id"])
    application = _application_of_record(record)
    if decision == "ACCEPT":
        if (reference["evaluation_score"] or 0) < 3 or not reference["responsibility_confirmed"]:
            raise ApiError("ERR_REFERENCE_STATE_INVALID",
                           "acceptance requires a score of at least 3 and a "
                           "confirmed responsibility level")
        db.write(reference, status="ACCEPTED")
        if record["verification_status"] == "PENDING_VERIFICATION":
            db.write(record, verification_status="VERIFIED")
        calc.refresh_record_derived(record)
    else:
        db.write(reference, status="REJECTED")
        if record["verification_status"] == "PENDING_VERIFICATION":
            db.write(record, verification_status="DISPUTED")
    calc.recompute_verified(application)
    return ok(schemas.view(reference, schemas.REFERENCE))


@bp.post("/references/<reference_id>/recant")
@endpoint("SupervisingEngineer")
def recant_reference(reference_id):
    data = body()
    recant_reason = req_str(data, "recant_reason")
    reference = schemas.fetch("references", reference_id, "ERR_REFERENCE_NOT_FOUND")
    guards.owned_by_caller(reference["referee_engineer_id"])
    if reference["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERENCE_STATE_INVALID",
                       "only an ACCEPTED verification may be withdrawn")
    record = db.get("experience_records", reference["experience_record_id"])
    application = _application_of_record(record)
    if application["status"] not in ("UNDER_REVIEW", "DEFICIENT", "EXAM_APPROVED"):
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "the file is no longer open to a withdrawal")

    # Link one: the verification itself.
    db.write(reference, status="RECANTED", recant_reason=recant_reason)
    # Link two: the experience block.
    db.write(record, verification_status="RECANTED", credited_months=0)
    # Link three: the file's board-determined credit.
    was_exam_approved = application["status"] == "EXAM_APPROVED"
    total = calc.recompute_verified(application)
    demoted = False
    if was_exam_approved and total < calc.REQUIRED_EXPERIENCE_MONTHS:
        db.write(application,
                 status="DEFICIENT",
                 deficiency_cycle_count=application["deficiency_cycle_count"] + 1,
                 deficiency_reason="EXPERIENCE_CREDIT_WITHDRAWN",
                 deficiency_due_at=add_days(db.clock(),
                                            calc.DEFICIENCY_RESPONSE_DAYS))
        demoted = True
    if demoted:
        # Links four and five: the authorization, its appointments and the seats.
        for authorization in calc.authorizations_of(application["id"]):
            if authorization["status"] in ("APPROVED_TO_SIT", "SCHEDULED"):
                db.write(authorization, status="CANCELLED")
                cascade.cancel_scheduled_appointments(authorization)
    return ok(schemas.view(reference, schemas.REFERENCE))
