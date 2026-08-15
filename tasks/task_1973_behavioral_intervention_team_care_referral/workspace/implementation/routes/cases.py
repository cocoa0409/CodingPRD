from flask import Blueprint, request

import errors as E
import response
from db import store, touch, serialize
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response
from services.domain import case_view_level, serialize_case_scoped, cancel_scheduled_checkins

bp = Blueprint("cases", __name__)

CASE_READ_ROLES = [
    "Reporter",
    "CaseManager",
    "BITChair",
    "CounselingEvaluator",
    "DeanOfStudents",
    "PrivacyOfficer",
]


@bp.get("/bit/care-cases/<cid>")
def get_case(cid):
    uid, role = require_auth(CASE_READ_ROLES)
    rec = get_or_404(store.cases, cid, "care case")
    # Rank 6: privacy scope gating.
    level = case_view_level(rec, uid, role)
    return response.obj(serialize_case_scoped(rec, level, serialize))


@bp.get("/bit/care-cases")
def list_cases():
    require_auth(["CaseManager", "BITChair", "CounselingEvaluator", "DeanOfStudents", "PrivacyOfficer"])
    q = request.args
    return list_response(
        store.cases,
        [
            ("student_id", q.get("student_id")),
            ("assigned_case_manager_id", q.get("assigned_case_manager_id")),
            ("opened_from_report_id", q.get("opened_from_report_id")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/care-cases/<cid>/assign-manager")
def assign_manager(cid):
    require_auth(["BITChair"])
    rec = get_or_404(store.cases, cid, "care case")
    b = body()
    case_manager_id = b.get("case_manager_id")
    manager = None
    if isinstance(case_manager_id, str):
        manager = store.staff.get(case_manager_id)
        if manager is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"staff member not found: {case_manager_id}")
    if manager is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_manager_id is required")
    rec["assigned_case_manager_id"] = case_manager_id
    touch(rec)
    return response.obj(serialize(rec))


@bp.post("/bit/care-cases/<cid>/close")
def close_case(cid):
    require_auth(["BITChair"])
    rec = get_or_404(store.cases, cid, "care case")
    # Rank 5: state precondition.
    if rec["status"] != "PLAN_ACTIVE":
        raise ApiError(E.ERR_CASE_NOT_PLAN_ACTIVE, 409, "close requires case PLAN_ACTIVE")
    # Rank 9: closure eligibility aggregate.
    closable = (
        rec["consecutive_stable_checkins"] >= 3
        and rec["current_risk_tier"] == "LOW"
        and not any(
            a["case_id"] == cid and a["status"] == "SCHEDULED"
            for a in store.assessments.values()
        )
        and not any(
            d["case_id"] == cid and d["status"] == "PENDING"
            for d in store.leave_decisions.values()
        )
        and not any(
            e["case_id"] == cid and e["status"] == "PENDING" for e in store.reentries.values()
        )
    )
    if not closable:
        raise ApiError(
            E.ERR_CASE_NOT_CLOSABLE, 409, "case does not satisfy closure eligibility"
        )
    rec["status"] = "CLOSED"
    rec["closed_at"] = store.clock
    touch(rec)
    cancel_scheduled_checkins(cid)
    return response.obj(serialize(rec))
