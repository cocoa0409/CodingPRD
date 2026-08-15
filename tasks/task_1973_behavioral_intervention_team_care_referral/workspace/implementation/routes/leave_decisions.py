from datetime import timedelta

from flask import Blueprint, request

import errors as E
import response
from db import store, touch, serialize, now
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response
from services.domain import cadence_days, schedule_checkin

bp = Blueprint("leave_decisions", __name__)

LEAVE_READ_ROLES = ["BITChair", "DeanOfStudents", "CaseManager", "PrivacyOfficer"]


@bp.get("/bit/leave-decisions/<lid>")
def get_leave_decision(lid):
    require_auth(LEAVE_READ_ROLES)
    rec = get_or_404(store.leave_decisions, lid, "leave decision")
    return response.obj(serialize(rec))


@bp.get("/bit/leave-decisions")
def list_leave_decisions():
    require_auth(LEAVE_READ_ROLES)
    q = request.args
    return list_response(
        store.leave_decisions,
        [
            ("case_id", q.get("case_id")),
            ("requested_by", q.get("requested_by")),
            ("decided_by", q.get("decided_by")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/leave-decisions/<lid>/decide")
def decide_leave(lid):
    uid, _ = require_auth(["DeanOfStudents"])
    rec = get_or_404(store.leave_decisions, lid, "leave decision")
    if rec["status"] != "PENDING":
        raise ApiError(E.ERR_DECISION_NOT_PENDING, 409, "decide requires decision PENDING")
    if uid == rec["requested_by"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES,
            403,
            "leave decider must differ from the requester",
        )
    b = body()
    decision = b.get("decision")
    if decision not in ("GRANT_LEAVE", "DENY_LEAVE"):
        raise ApiError(E.ERR_VALIDATION, 400, "decision must be GRANT_LEAVE or DENY_LEAVE")
    rationale = b.get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ApiError(E.ERR_VALIDATION, 400, "rationale is required")

    rec["decision"] = decision
    rec["rationale"] = rationale
    rec["decided_by"] = uid
    rec["decided_at"] = now()
    touch(rec)

    case = store.cases.get(rec["case_id"])
    if decision == "GRANT_LEAVE":
        rec["status"] = "GRANTED"
        if case is not None:
            case["status"] = "ON_LEAVE"
            touch(case)
            student = store.students.get(case["student_id"])
            if student is not None:
                student["enrollment_status"] = "LEAVE_OF_ABSENCE"
                touch(student)
            for p in store.plans.values():
                if p["case_id"] == case["id"] and p["status"] == "ACTIVE":
                    p["status"] = "SUSPENDED"
                    touch(p)
    else:
        rec["status"] = "DENIED"
        if case is not None:
            case["status"] = "PLAN_ACTIVE"
            touch(case)
            schedule_checkin(
                case["id"], now() + timedelta(days=cadence_days(case["current_risk_tier"]))
            )
    return response.obj(serialize(rec))
