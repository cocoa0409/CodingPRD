from datetime import timedelta

from flask import Blueprint, request

import errors as E
import response
from db import store, touch, serialize, now
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response
from services.domain import cadence_days, schedule_checkin

bp = Blueprint("checkins", __name__)

CHECKIN_READ_ROLES = ["CaseManager", "BITChair", "DeanOfStudents", "PrivacyOfficer"]


@bp.get("/bit/follow-up-checkins/<cid>")
def get_checkin(cid):
    require_auth(CHECKIN_READ_ROLES)
    rec = get_or_404(store.checkins, cid, "follow-up check-in")
    return response.obj(serialize(rec))


@bp.get("/bit/follow-up-checkins")
def list_checkins():
    require_auth(CHECKIN_READ_ROLES)
    q = request.args
    return list_response(
        store.checkins,
        [("case_id", q.get("case_id")), ("status", q.get("status"))],
    )


@bp.post("/bit/follow-up-checkins/<cid>/complete")
def complete_checkin(cid):
    uid, _ = require_auth(["CaseManager"])
    rec = get_or_404(store.checkins, cid, "follow-up check-in")
    case = store.cases.get(rec["case_id"])
    # Rank 5: check-in state, then case state.
    if rec["status"] != "SCHEDULED":
        raise ApiError(E.ERR_CHECKIN_NOT_SCHEDULED, 409, "complete requires check-in SCHEDULED")
    if case is None or case["status"] != "PLAN_ACTIVE":
        raise ApiError(
            E.ERR_CASE_NOT_PLAN_ACTIVE, 409, "check-in completion requires case PLAN_ACTIVE"
        )
    # Rank 7: caseload ownership.
    if uid != case["assigned_case_manager_id"]:
        raise ApiError(
            E.ERR_NOT_ASSIGNED_CASE_MANAGER,
            403,
            "only the case's assigned case manager may complete the check-in",
        )
    # Rank 9: field validity. MISSED is a sweep status, never a recordable outcome.
    b = body()
    outcome = b.get("outcome")
    if outcome not in ("STABLE", "ESCALATED"):
        raise ApiError(E.ERR_VALIDATION, 400, "outcome must be STABLE or ESCALATED")
    note = b.get("note")
    if not isinstance(note, str) or not note:
        raise ApiError(E.ERR_VALIDATION, 400, "note is required")

    rec["outcome"] = outcome
    rec["note"] = note
    rec["completed_at"] = now()
    rec["status"] = "COMPLETED"
    touch(rec)

    if outcome == "STABLE":
        case["consecutive_stable_checkins"] += 1
        touch(case)
        schedule_checkin(
            case["id"], now() + timedelta(days=cadence_days(case["current_risk_tier"]))
        )
    else:  # ESCALATED
        case["consecutive_stable_checkins"] = 0
        for p in store.plans.values():
            if p["case_id"] == case["id"] and p["status"] == "ACTIVE":
                p["status"] = "SUPERSEDED"
                touch(p)
        case["status"] = "TRIAGED"
        touch(case)
    return response.obj(serialize(rec))
