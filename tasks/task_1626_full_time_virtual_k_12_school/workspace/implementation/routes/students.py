"""Student lifecycle and EnrollmentTerm endpoints (PRD sections 3.2-3.3).

Validation cascade order is honored in every handler: authentication (401)
-> authorization (403) -> path existence (404) -> body FK existence (404)
-> state admissibility (409) -> OCC (412) -> business rules (422) -> input
shape (400).
"""

import db
import services
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_DISTRICT_CAP_REACHED,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, pagination_params, paginate, apply_filters,
    require_fk, exist_body_fks, occ_version,
)

bp = make_blueprint("students")

WITHDRAWAL_REASONS = [
    "MOVED_DISTRICT", "RETURN_TO_BRICK_AND_MORTAR", "HOMESCHOOL",
    "DROPOUT", "ADMINISTRATIVE",
]
TERM_ROLES = ["PlatformAdmin", "EnrollmentOfficer", "FinanceOfficer"]


def _public_student(student):
    services.reconcile_student(student)
    return db.public(student)


# --- Student ---------------------------------------------------------------

@bp.post("/students")
def create_student():
    authenticate(["EnrollmentOfficer", "PlatformAdmin"])
    body = body_json()
    exist_body_fks(body, {"district_of_residence_id": ("districts", "district")})
    check_shape(body, {
        "legal_name": {"type": "string", "required": True},
        "date_of_birth": {"type": "datetime", "required": True},
        "grade_level": {"type": "integer", "required": True, "min": 0, "max": 12},
        "district_of_residence_id": {"type": "string", "required": True},
        "special_education_flag": {"type": "boolean", "required": False},
    })
    student = db.new_entity("students", {
        "legal_name": body["legal_name"],
        "date_of_birth": body["date_of_birth"],
        "grade_level": body["grade_level"],
        "district_of_residence_id": body["district_of_residence_id"],
        "special_education_flag": body.get("special_education_flag", False),
        "enrollment_status": "APPLIED",
        "residency_verified_at": None,
        "funding_days_claimed": 0,
        "funding_claim_cents": 0,
        "truancy_flag": False,
        "truancy_unexcused_count": 0,
    })
    return success_obj(db.public(student), 201)


@bp.get("/students/<sid>")
def get_student(sid):
    authenticate(ALL_ROLES)
    student = require_fk("students", sid, "student")
    return success_obj(_public_student(student), 200)


@bp.get("/students")
def list_students():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(
        db.all_of("students"),
        ["district_of_residence_id", "enrollment_status", "truancy_flag"],
    )
    page, total, has_more = paginate(items, limit, offset)
    return success_list([_public_student(s) for s in page], limit, offset, total, has_more)


@bp.post("/students/<sid>/verify-residency")
def verify_residency(sid):
    authenticate(["EnrollmentOfficer"])
    student = require_fk("students", sid, "student")
    # State admissibility (priority 5).
    if student["enrollment_status"] != "APPLIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an APPLIED student can be residency-verified")
    # District of residence must still exist (its slot check follows).
    district = db.get("districts", student["district_of_residence_id"])
    if district is None:
        raise ApiError("ERR_NOT_FOUND", 404, "district not found")
    # District cap (priority 14).
    if not services.district_open_slot(district, student):
        raise ApiError(ERR_DISTRICT_CAP_REACHED, 422,
                       "district enrollment_cap has been reached")
    student["enrollment_status"] = "ELIGIBLE"
    student["residency_verified_at"] = db.fmt_ts(db.now())
    db.touch(student)
    return success_obj(_public_student(student), 200)


@bp.post("/students/<sid>/enroll")
def enroll_student(sid):
    authenticate(["EnrollmentOfficer"])
    student = require_fk("students", sid, "student")
    body = body_json()
    # Gate 1: state admissibility (priority 5) -- ELIGIBLE or REENROLL_PENDING.
    if student["enrollment_status"] not in ("ELIGIBLE", "REENROLL_PENDING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "student status does not admit enrollment")
    # Gate 2: OCC on Student.version (priority 6).
    occ_version("expected_student_version", student["version"])(body)
    # Gate 3: district open slot under the same cap rule as verification.
    district = db.get("districts", student["district_of_residence_id"])
    if not services.district_open_slot(district, student):
        raise ApiError(ERR_DISTRICT_CAP_REACHED, 422,
                       "district enrollment_cap has been reached")
    # Input shape (priority 16): the version field is required.
    check_shape(body, {
        "expected_student_version": {"type": "integer", "required": True},
    })
    # Side effects: open a fresh ACTIVE term, reset the truancy window.
    db.new_entity("enrollment_terms", {
        "student_id": student["id"],
        "term_start_date": db.fmt_date(db.now()),
        "term_end_date": None,
        "term_status": "ACTIVE",
        "withdrawal_reason": None,
        "proration_mode": None,
        "claimable_days": 0,
    })
    student["enrollment_status"] = "ENROLLED"
    student["truancy_unexcused_count"] = 0
    student["truancy_flag"] = False
    db.touch(student)
    return success_obj(_public_student(student), 200)


@bp.post("/students/<sid>/withdraw")
def withdraw_student(sid):
    authenticate(["EnrollmentOfficer"])
    student = require_fk("students", sid, "student")
    body = body_json()
    # State admissibility (priority 5): ENROLLED with an ACTIVE current term.
    if student["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ENROLLED student can be withdrawn")
    term = next(
        (t for t in db.all_of("enrollment_terms")
         if t["student_id"] == student["id"] and t["term_status"] == "ACTIVE"),
        None,
    )
    if term is None:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "student has no ACTIVE enrollment term")
    # Input shape (priority 16): withdrawal_reason required, declared enum.
    check_shape(body, {
        "withdrawal_reason": {"type": "enum", "required": True,
                              "values": WITHDRAWAL_REASONS},
    })
    services.withdraw_cascade(student, term, body["withdrawal_reason"])
    return success_obj(_public_student(student), 200)


@bp.post("/students/<sid>/request-reenrollment")
def request_reenrollment(sid):
    authenticate(["EnrollmentOfficer"])
    student = require_fk("students", sid, "student")
    if student["enrollment_status"] != "WITHDRAWN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a WITHDRAWN student can request re-enrollment")
    student["enrollment_status"] = "REENROLL_PENDING"
    db.touch(student)
    return success_obj(_public_student(student), 200)


# --- EnrollmentTerm ----------------------------------------------------------

@bp.get("/students/<sid>/enrollment-terms")
def list_student_terms(sid):
    authenticate(TERM_ROLES)
    student = require_fk("students", sid, "student")
    limit, offset = pagination_params()
    items = [t for t in db.all_of("enrollment_terms")
             if t["student_id"] == student["id"]]
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.get("/enrollment-terms/<tid>")
def get_term(tid):
    authenticate(TERM_ROLES)
    term = require_fk("enrollment_terms", tid, "enrollment term")
    return success_obj(db.public(term), 200)
