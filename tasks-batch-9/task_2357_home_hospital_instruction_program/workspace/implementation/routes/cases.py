"""Case creation, activation, denial, closure and the funding operations."""

from flask import Blueprint

import clock
import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import (
    CLOSE_REASONS,
    DELIVERY_MODES,
    FUNDING_STATUSES,
    SERVICE_STATUSES,
    listing,
)
from services import logic

bp = Blueprint("cases", __name__)

CREATE_BODY = {
    "student_id": {"type": "string", "required": True},
    "referral_date": {"type": "date", "required": True},
    "delivery_mode": {"type": "string", "required": True, "enum": DELIVERY_MODES},
    "referral_note": {"type": "string"},
}

LIST_QUERY = {
    "student_id": {"type": "string"},
    "entitlement_rule_id": {"type": "string"},
    "service_status": {"type": "string", "enum": SERVICE_STATUSES},
    "funding_status": {"type": "string", "enum": FUNDING_STATUSES},
}

# RETURNED_TO_CAMPUS is reserved for a completed transition plan (PRD §3.9).
CLOSE_BODY = {
    "close_reason": {
        "type": "string",
        "required": True,
        "enum": [r for r in CLOSE_REASONS if r != "RETURNED_TO_CAMPUS"],
    }
}


def load_case(case_id):
    row = db.get("cases", case_id)
    if row is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return row


@bp.post("/hhi/cases")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_case():
    body = middleware.body()

    student = db.get("students", body["student_id"])          # tier 5
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")

    for case in db.store["cases"].values():                    # tier 11
        if case["student_id"] == student["id"] and case["service_status"] not in (
            "CLOSED",
            "DENIED",
        ):
            raise ApiError("ERR_OPEN_CASE_EXISTS")

    if student["enrollment_status"] != "ENROLLED":              # tier 12
        raise ApiError("ERR_STUDENT_NOT_ENROLLED")

    row = db.insert(
        "cases",
        {
            "student_id": student["id"],
            "created_by_user_id": middleware.user_id(),
            "referral_date": body["referral_date"],
            "referral_note": body.get("referral_note"),
            "diagnosis_category": None,
            "delivery_mode": body["delivery_mode"],
            "service_status": "DRAFT",
            "funding_status": "NOT_REPORTED",
            "entitlement_rule_id": None,
            "weekly_entitled_minutes": 0,
            "certified_start_date": None,
            "certified_end_date": None,
            "service_start_date": None,
            "reported_apportionment_minutes": 0,
            "service_gap_minutes": 0,
            "makeup_obligation_minutes": 0,
            "extension_count": 0,
            "certification_count": 0,
            "escort_required": False,
            "provisional_apportionment_minutes": 0,
            "final_apportionment_minutes": 0,
            "delivery_ratio_pct": 0.0,
            "recapture_minutes": 0,
            "net_apportionment_minutes": 0,
            "close_reason": None,
        },
    )
    return middleware.obj(row)


@bp.get("/hhi/cases/<case_id>")
@endpoint(
    [
        "ProgramAdministrator",
        "CaseManager",
        "NurseReviewer",
        "HomeboundTeacher",
        "ClassroomTeacher",
    ]
)
def read_case(case_id):
    return middleware.obj(load_case(case_id))


@bp.get("/hhi/cases")
@endpoint(
    ["ProgramAdministrator", "CaseManager", "NurseReviewer"], query=LIST_QUERY
)
def list_cases():
    return listing("cases", LIST_QUERY)


@bp.post("/hhi/cases/<case_id>/activate")
@endpoint(["ProgramAdministrator"])
def activate_case(case_id):
    case = load_case(case_id)

    if case["service_status"] != "ELIGIBLE":                    # tier 8
        raise ApiError("ERR_INVALID_CASE_STATE")

    review = logic.governing_review(case)
    if case["delivery_mode"] in ("IN_HOME", "HYBRID"):          # tier 10
        if review is None:
            raise ApiError("ERR_SAFETY_REVIEW_MISSING")
        if review["clearance"] not in ("CLEARED", "CLEARED_WITH_ESCORT"):
            raise ApiError("ERR_SAFETY_CLEARANCE_BLOCKED")

    student = logic.student_of(case)
    if student["enrollment_status"] != "ENROLLED":              # tier 12
        raise ApiError("ERR_STUDENT_NOT_ENROLLED")
    if not any(
        a["role"] == "PRIMARY" and a["status"] == "ACTIVE"
        for a in db.by_case("assignments", case["id"])
    ):
        raise ApiError("ERR_NO_PRIMARY_ASSIGNMENT")

    db.set_field(case, "service_status", "ACTIVE")
    db.set_field(case, "service_start_date", clock.get_date().isoformat())
    db.set_field(
        case,
        "escort_required",
        review is not None and review["clearance"] == "CLEARED_WITH_ESCORT",
    )
    db.set_field(case, "funding_status", "ACCRUING")
    db.set_field(case, "service_gap_minutes", 0)
    db.touch(case)
    return middleware.obj(case)


@bp.post("/hhi/cases/<case_id>/deny")
@endpoint(["ProgramAdministrator"], body={"deny_note": {"type": "string"}})
def deny_case(case_id):
    case = load_case(case_id)
    if case["service_status"] not in ("DRAFT", "PENDING_CERT_REVIEW"):
        raise ApiError("ERR_INVALID_CASE_STATE")

    db.set_field(case, "service_status", "DENIED")
    db.set_field(case, "close_reason", "DENIED_ELIGIBILITY")
    for cert in db.by_case("certifications", case["id"]):
        if cert["status"] == "SUBMITTED":
            db.set_field(cert, "status", "REJECTED")
    db.touch(case)
    return middleware.obj(case)


@bp.post("/hhi/cases/<case_id>/close")
@endpoint(["ProgramAdministrator"], body=CLOSE_BODY)
def close_case(case_id):
    case = load_case(case_id)
    if case["service_status"] not in ("ELIGIBLE", "ACTIVE", "EXTENSION_PENDING"):
        raise ApiError("ERR_INVALID_CASE_STATE")

    db.set_field(case, "service_status", "CLOSED")
    db.set_field(case, "close_reason", middleware.body()["close_reason"])
    logic.release_active_assignments(case)
    logic.cancel_scheduled_sessions(case)
    logic.supersede_open_plans(case)
    logic.deny_open_extension_requests(case)
    db.touch(case)
    return middleware.obj(case)


@bp.post("/hhi/cases/<case_id>/funding/report")
@endpoint(["ProgramAdministrator"])
def report_funding(case_id):
    case = load_case(case_id)
    if case["service_status"] not in ("ACTIVE", "EXTENSION_PENDING", "TRANSITION_PLANNED"):
        raise ApiError("ERR_INVALID_CASE_STATE")

    db.set_field(
        case, "provisional_apportionment_minutes", logic.provisional_apportionment(case)
    )
    logic.recompute_service_gap(case)
    db.touch(case)
    return middleware.obj(case)


@bp.post("/hhi/cases/<case_id>/funding/reconcile")
@endpoint(["ProgramAdministrator"])
def reconcile_funding(case_id):
    case = load_case(case_id)
    # Tier 8: the already-reconciled check precedes the generic funding-state
    # check, and the generic code is reserved for NOT_REPORTED / HELD /
    # FORFEITED, so the funding dimension is judged before the service one.
    if case["funding_status"] == "RECONCILED":
        raise ApiError("ERR_FUNDING_ALREADY_RECONCILED")
    if case["funding_status"] != "ACCRUING":
        raise ApiError("ERR_FUNDING_NOT_ACCRUING")
    if case["service_status"] not in (
        "ACTIVE",
        "EXTENSION_PENDING",
        "TRANSITION_PLANNED",
        "CLOSED",
    ):
        raise ApiError("ERR_INVALID_CASE_STATE")

    logic.reconcile_case(case)
    db.touch(case)
    return middleware.obj(case)


@bp.get("/hhi/cases/<case_id>/funding-summary")
@endpoint(["ProgramAdministrator", "CaseManager"])
def funding_summary(case_id):
    return middleware.raw(logic.funding_summary(load_case(case_id)))
