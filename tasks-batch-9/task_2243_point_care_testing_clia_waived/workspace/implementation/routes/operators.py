"""Operator roster and competency assessments (PRD 3.3)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("operators", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")
NON_OPERATOR = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor")

ROLE_TITLES = ("PHYSICIAN", "DOCTORAL_SCIENTIST", "MIDLEVEL_PRACTITIONER",
               "MEDICAL_TECHNOLOGIST", "MEDICAL_ASSISTANT", "NURSE")
ASSESSMENT_TYPES = ("INITIAL", "SEMIANNUAL_1", "SEMIANNUAL_2", "ANNUAL")


# --------------------------------------------------------------------------
# Roster
# --------------------------------------------------------------------------

@route(bp, "/operators", ["POST"], ["ProgramAdmin"])
def create_operator(user_id, role):
    payload = valid.body()
    site = valid.resolve_body("sites", payload, "site_id")
    full_name = valid.req_str(payload, "full_name")
    role_title = valid.req_enum(payload, "role_title", ROLE_TITLES)
    hire_date = valid.req_date(payload, "hire_date")

    row = db.insert("operators", {
        "site_id": site["id"],
        "full_name": full_name,
        "role_title": role_title,
        "hire_date": hire_date.isoformat(),
        "training_completed_at": None,
        "training_module_code": None,
        "competency_status": "PENDING",
        "access_status": "LOCKED_OUT",
        "lockout_reason": "NEVER_TRAINED",
        "competency_expires_at": None,
        "current_grace_days": 0,
        "lapse_deadline": None,
        "consecutive_rejection_count": 0,
    })
    derive.recompute_site(site)
    return response.object_response(serializers.dump("operators", row), 201)


@route(bp, "/operators/<operator_id>", ["GET"], ALL_ROLES)
def read_operator(user_id, role, operator_id):
    row = valid.resolve("operators", operator_id)
    return response.object_response(serializers.dump("operators", row))


@route(bp, "/operators", ["GET"], NON_OPERATOR)
def list_operators(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    competency = valid.arg("competency_status")
    access = valid.arg("access_status")
    items = [o for o in db.rows("operators")
             if (site_id is None or o["site_id"] == site_id)
             and (competency is None or o["competency_status"] == competency)
             and (access is None or o["access_status"] == access)]
    return response.list_response(
        serializers.dump_many("operators", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/operators/<operator_id>/training", ["POST"],
       ["ProgramAdmin", "QualityCoordinator"])
def record_training(user_id, role, operator_id):
    operator = valid.resolve("operators", operator_id)
    payload = valid.body()
    module_code = valid.req_str(payload, "training_module_code")
    valid.req_date(payload, "completed_on")
    # Rank 50 — the transition is only available from the initial pair.
    if (operator["competency_status"] != "PENDING"
            or operator["access_status"] != "LOCKED_OUT"
            or operator["lockout_reason"] != "NEVER_TRAINED"):
        raise errors.invalid_state(
            "Training requires PENDING competency and LOCKED_OUT access with "
            "lockout_reason NEVER_TRAINED.")

    operator["training_module_code"] = module_code
    operator["training_completed_at"] = clock.now_iso()
    operator["competency_status"] = "PROVISIONAL"
    operator["access_status"] = "ACTIVE"
    operator["lockout_reason"] = None
    db.touch(operator)

    derive.recompute_site_by_id(operator["site_id"])
    return response.object_response(serializers.dump("operators", operator))


@route(bp, "/operators/<operator_id>/access-reinstatement", ["POST"],
       ["LabDirector", "ProgramAdmin"])
def reinstate_access(user_id, role, operator_id):
    operator = valid.resolve("operators", operator_id)
    payload = valid.body()
    valid.req_str(payload, "justification")
    site = db.get("sites", operator["site_id"])
    # Rank 42.
    if site is not None and site["oversight_posture"] == "SUSPENDED":
        raise errors.ApiError("ERR_SITE_OVERSIGHT_SUSPENDED", 409)
    # Rank 50.
    if operator["access_status"] != "LOCKED_OUT":
        raise errors.invalid_state("Reinstatement requires LOCKED_OUT access.")
    if operator["competency_status"] not in ("PROVISIONAL", "COMPETENT"):
        raise errors.invalid_state(
            "Reinstatement requires PROVISIONAL or COMPETENT competency.")

    operator["access_status"] = "ACTIVE"
    operator["lockout_reason"] = None
    db.touch(operator)

    derive.recompute_site(site)
    return response.object_response(serializers.dump("operators", operator))


# --------------------------------------------------------------------------
# Competency assessments
# --------------------------------------------------------------------------

@route(bp, "/competency-assessments", ["POST"],
       ["QualityCoordinator", "LabDirector"])
def submit_assessment(user_id, role):
    payload = valid.body()
    # Rank 11 — operator existence, subject then assessor.
    subject = valid.resolve_body("operators", payload, "operator_id")
    assessor = valid.resolve_body("operators", payload, "assessor_operator_id")
    # Rank 20.
    device_model = valid.req_str(payload, "device_model")
    assessment_type = valid.req_enum(payload, "assessment_type", ASSESSMENT_TYPES)
    methods = valid.req_int(payload, "methods_demonstrated", 0, 6)
    effective = valid.req_date(payload, "effective_date")
    expires = valid.req_date(payload, "expires_at")
    if expires <= effective:
        raise errors.invalid_request(
            "expires_at must fall strictly after effective_date.")
    expected_version = valid.req_int(payload, "expected_operator_version")
    # Rank 30.
    if expected_version != subject["version"]:
        raise errors.ApiError("ERR_STALE_VERSION", 412)
    # Rank 53 — the assessor's competency must be current.
    if assessor["competency_status"] not in ("PROVISIONAL", "COMPETENT"):
        raise errors.ApiError("ERR_OPERATOR_COMPETENCY_LAPSED", 422)
    # Rank 60.
    if assessor["site_id"] != subject["site_id"]:
        raise errors.ApiError("ERR_CROSS_SITE_REFERENCE", 422)
    # Rank 63.
    if methods < 6:
        raise errors.ApiError("ERR_INSUFFICIENT_COMPETENCY_METHODS", 422)
    # Rank 65 (b).
    if assessor["id"] == subject["id"]:
        raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES", 422)
    # Rank 68 — half-open collision against APPROVED windows.
    if calc.assessment_collides(subject["id"], device_model, effective, expires):
        raise errors.ApiError("ERR_ASSESSMENT_WINDOW_OVERLAP", 409)

    for earlier in db.rows("assessments"):
        if earlier["operator_id"] != subject["id"]:
            continue
        if earlier["device_model"] != device_model:
            continue
        if earlier["status"] != "SUBMITTED":
            continue
        snap = db.snapshot(earlier)
        earlier["status"] = "VOIDED"
        earlier["decision_note"] = "superseded by a later submission"
        db.touch_if_changed(earlier, snap)

    row = db.insert("assessments", {
        "operator_id": subject["id"],
        "assessor_operator_id": assessor["id"],
        "device_model": device_model,
        "assessment_type": assessment_type,
        "methods_demonstrated": methods,
        "effective_date": effective.isoformat(),
        "expires_at": expires.isoformat(),
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "decision_note": None,
    })
    db.touch(subject)
    return response.object_response(serializers.dump("assessments", row), 201)


@route(bp, "/competency-assessments/<assessment_id>", ["GET"], NON_OPERATOR)
def read_assessment(user_id, role, assessment_id):
    row = valid.resolve("assessments", assessment_id)
    return response.object_response(serializers.dump("assessments", row))


@route(bp, "/competency-assessments", ["GET"], NON_OPERATOR)
def list_assessments(user_id, role):
    limit, offset = valid.pagination()
    operator_id = valid.arg("operator_id")
    assessor_id = valid.arg("assessor_operator_id")
    status = valid.arg("status")
    items = [a for a in db.rows("assessments")
             if (operator_id is None or a["operator_id"] == operator_id)
             and (assessor_id is None or a["assessor_operator_id"] == assessor_id)
             and (status is None or a["status"] == status)]
    return response.list_response(
        serializers.dump_many("assessments", valid.page(items, limit, offset)),
        limit, offset, len(items))


@route(bp, "/competency-assessments/<assessment_id>/decision", ["POST"],
       ["LabDirector", "ProgramAdmin"])
def decide_assessment(user_id, role, assessment_id):
    assessment = valid.resolve("assessments", assessment_id)
    payload = valid.body()
    decision = valid.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    note = valid.opt_str(payload, "note")
    # Rank 49.
    if assessment["status"] != "SUBMITTED":
        raise errors.ApiError("ERR_ASSESSMENT_NOT_SUBMITTED", 409)

    subject = db.get("operators", assessment["operator_id"])
    site = db.get("sites", subject["site_id"]) if subject else None

    # Rank 50 — the approval transition needs the window to contain today.
    if decision == "APPROVE":
        today = clock.today()
        effective = clock.parse_date(assessment["effective_date"])
        expires = clock.parse_date(assessment["expires_at"])
        if not (effective <= today < expires):
            raise errors.invalid_state(
                "The assessment window does not contain the current logical date.")

    # Rank 65 (a) — LabDirector three-way duty separation.
    if role == "LabDirector":
        director_id = site["lab_director_operator_id"] if site else None
        if (user_id != director_id
                or user_id == assessment["assessor_operator_id"]
                or user_id == assessment["operator_id"]):
            raise errors.ApiError("ERR_SEGREGATION_OF_DUTIES", 422)

    snap = db.snapshot(assessment)
    assessment["decided_by_user_id"] = user_id
    assessment["decision_note"] = note

    if decision == "APPROVE":
        assessment["status"] = "APPROVED"
        db.touch_if_changed(assessment, snap)
        osnap = db.snapshot(subject)
        subject["competency_status"] = "COMPETENT"
        derive.recompute_competency_expiry(subject)
        subject["consecutive_rejection_count"] = 0
        db.touch_if_changed(subject, osnap)
    else:
        assessment["status"] = "REJECTED"
        db.touch_if_changed(assessment, snap)
        osnap = db.snapshot(subject)
        subject["consecutive_rejection_count"] = int(
            subject["consecutive_rejection_count"] or 0) + 1
        if subject["consecutive_rejection_count"] >= 2:
            subject["competency_status"] = "REVOKED"
            subject["access_status"] = "DEACTIVATED"
            subject["lockout_reason"] = "COMPETENCY_REVOKED"
        db.touch_if_changed(subject, osnap)

    derive.recompute_site(site)
    return response.object_response(serializers.dump("assessments", assessment))
