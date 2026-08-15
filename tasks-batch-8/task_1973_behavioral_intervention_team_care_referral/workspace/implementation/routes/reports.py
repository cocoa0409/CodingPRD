from flask import Blueprint, request

import errors as E
import response
from db import store, new_record, touch, serialize, parse_dt
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response
from services.domain import CONCERN_CATEGORIES

bp = Blueprint("reports", __name__)


@bp.post("/bit/concern-reports")
def create_report():
    uid, _ = require_auth(["Reporter"])
    b = body()
    student_id = b.get("student_id")
    related_report_id = b.get("related_report_id")

    # Rank 3: body FK existence (student_id before related_report_id).
    student = None
    if isinstance(student_id, str):
        student = store.students.get(student_id)
        if student is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"student not found: {student_id}")
    related = None
    if related_report_id is not None and isinstance(related_report_id, str):
        related = store.reports.get(related_report_id)
        if related is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"related report not found: {related_report_id}")

    # Rank 8: enrollment gate — fires before field checks and cross-reference.
    if student is not None and student["enrollment_status"] == "WITHDRAWN":
        raise ApiError(E.ERR_STUDENT_NOT_ACTIVE, 409, "student is WITHDRAWN")

    # Rank 9: required fields / enums.
    if student is None:
        raise ApiError(E.ERR_VALIDATION, 400, "student_id is required")
    category = b.get("category")
    if category not in CONCERN_CATEGORIES:
        raise ApiError(E.ERR_VALIDATION, 400, "category must be a declared concern category")
    narrative = b.get("narrative")
    if not isinstance(narrative, str) or not narrative:
        raise ApiError(E.ERR_VALIDATION, 400, "narrative is required")
    observed_at = parse_dt(b.get("observed_at"))
    if observed_at is None:
        raise ApiError(E.ERR_VALIDATION, 400, "observed_at must be an ISO 8601 UTC timestamp")
    if related_report_id is not None and related is None:
        raise ApiError(E.ERR_VALIDATION, 400, "related_report_id must reference a concern report")

    # Rank 11: cross-reference integrity.
    if related is not None and related["student_id"] != student_id:
        raise ApiError(
            E.ERR_RELATED_REPORT_STUDENT_MISMATCH,
            422,
            "related_report_id references a report for a different student",
        )

    rec = new_record()
    rec.update(
        {
            "student_id": student_id,
            "reporter_id": uid,
            "category": category,
            "narrative": narrative,
            "observed_at": observed_at,
            "related_report_id": related_report_id,
            "care_case_id": None,
            "review_rationale": None,
            "status": "SUBMITTED",
        }
    )
    store.reports[rec["id"]] = rec
    return response.obj(serialize(rec), 201)


@bp.get("/bit/concern-reports/<rid>")
def get_report(rid):
    uid, role = require_auth(["Reporter", "BITChair", "CaseManager", "PrivacyOfficer"])
    rec = get_or_404(store.reports, rid, "concern report")
    # Rank 7 ownership: a Reporter may read only their own reports.
    if role == "Reporter" and rec["reporter_id"] != uid:
        raise ApiError(E.ERR_FORBIDDEN, 403, "Reporter may read only own reports")
    return response.obj(serialize(rec))


@bp.get("/bit/concern-reports")
def list_reports():
    require_auth(["BITChair", "CaseManager", "PrivacyOfficer", "DeanOfStudents"])
    q = request.args
    return list_response(
        store.reports,
        [
            ("student_id", q.get("student_id")),
            ("reporter_id", q.get("reporter_id")),
            ("related_report_id", q.get("related_report_id")),
            ("care_case_id", q.get("care_case_id")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/concern-reports/<rid>/start-review")
def start_review(rid):
    require_auth(["BITChair"])
    rec = get_or_404(store.reports, rid, "concern report")
    if rec["status"] != "SUBMITTED":
        raise ApiError(
            E.ERR_REPORT_NOT_UNDER_REVIEW, 409, "start-review requires report SUBMITTED"
        )
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return response.obj(serialize(rec))


@bp.post("/bit/concern-reports/<rid>/accept")
def accept_report(rid):
    require_auth(["BITChair"])
    rec = get_or_404(store.reports, rid, "concern report")
    b = body()
    case_manager_id = b.get("case_manager_id")
    # Rank 3: body FK existence fires before the report's state check.
    manager = None
    if isinstance(case_manager_id, str):
        manager = store.staff.get(case_manager_id)
        if manager is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"staff member not found: {case_manager_id}")
    # Rank 5: state.
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(E.ERR_REPORT_NOT_UNDER_REVIEW, 409, "accept requires report UNDER_REVIEW")
    # Rank 9: required field.
    if manager is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_manager_id is required")

    # Link to the student's existing non-CLOSED case (untouched), else create INTAKE case.
    existing = None
    for c in store.cases.values():
        if c["student_id"] == rec["student_id"] and c["status"] != "CLOSED":
            if existing is None or (c["created_at"], c["_seq"]) < (
                existing["created_at"],
                existing["_seq"],
            ):
                existing = c
    if existing is not None:
        rec["care_case_id"] = existing["id"]
    else:
        case = new_record()
        case.update(
            {
                "student_id": rec["student_id"],
                "opened_from_report_id": rec["id"],
                "assigned_case_manager_id": case_manager_id,
                "status": "INTAKE",
                "current_risk_score": None,
                "current_risk_tier": None,
                "consecutive_stable_checkins": 0,
                "closed_at": None,
            }
        )
        store.cases[case["id"]] = case
        rec["care_case_id"] = case["id"]
    rec["status"] = "ACCEPTED"
    touch(rec)
    return response.obj(serialize(rec))


@bp.post("/bit/concern-reports/<rid>/close-no-action")
def close_no_action(rid):
    require_auth(["BITChair"])
    rec = get_or_404(store.reports, rid, "concern report")
    if rec["status"] != "UNDER_REVIEW":
        raise ApiError(
            E.ERR_REPORT_NOT_UNDER_REVIEW, 409, "close-no-action requires report UNDER_REVIEW"
        )
    rationale = body().get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ApiError(E.ERR_VALIDATION, 400, "rationale is required")
    rec["review_rationale"] = rationale
    rec["status"] = "CLOSED_NO_ACTION"
    touch(rec)
    return response.obj(serialize(rec))
