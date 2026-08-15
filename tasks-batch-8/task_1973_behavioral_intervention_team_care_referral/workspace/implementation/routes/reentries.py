from datetime import timedelta

from flask import Blueprint, request

import errors as E
import response
from db import store, new_record, touch, serialize, now
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response, is_intlike
from services.domain import REENTRY_FIRST_CHECKIN_DAYS, schedule_checkin

bp = Blueprint("reentries", __name__)

REENTRY_READ_ROLES = ["BITChair", "DeanOfStudents", "CaseManager", "PrivacyOfficer"]


def _active_granted_leave(case_id):
    granted = [
        d
        for d in store.leave_decisions.values()
        if d["case_id"] == case_id and d["status"] == "GRANTED"
    ]
    if not granted:
        return None
    granted.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return granted[-1]


@bp.post("/bit/reentry-evaluations")
def create_reentry():
    uid, _ = require_auth(["CaseManager"])
    b = body()
    case_id = b.get("case_id")
    case = None
    if isinstance(case_id, str):
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"care case not found: {case_id}")

    # Rank 4: OCC — a stale observation surfaces before the state check.
    ecv = b.get("expected_case_version")
    if is_intlike(ecv) and case is not None and ecv != case["version"]:
        raise ApiError(
            E.ERR_STALE_CASE_VERSION,
            412,
            "expected_case_version does not match the CareCase current version",
        )

    # Rank 5: state.
    if case is not None and case["status"] != "ON_LEAVE":
        raise ApiError(E.ERR_CASE_NOT_ON_LEAVE, 409, "re-entry petition requires case ON_LEAVE")

    # Rank 9: required fields, then pending-petition exclusion.
    if case is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_id is required")
    if not is_intlike(ecv):
        raise ApiError(E.ERR_VALIDATION, 400, "expected_case_version is required")
    petition_summary = b.get("petition_summary")
    if not isinstance(petition_summary, str) or not petition_summary:
        raise ApiError(E.ERR_VALIDATION, 400, "petition_summary is required")
    if any(
        e["case_id"] == case["id"] and e["status"] == "PENDING" for e in store.reentries.values()
    ):
        raise ApiError(
            E.ERR_REENTRY_ALREADY_PENDING,
            409,
            "a PENDING re-entry evaluation already exists for the case",
        )

    granted = _active_granted_leave(case["id"])
    rec = new_record()
    rec.update(
        {
            "case_id": case["id"],
            "leave_decision_id": granted["id"] if granted is not None else None,
            "petitioned_by": uid,
            "petition_summary": petition_summary,
            "decided_by": None,
            "outcome": None,
            "conditions": None,
            "rationale": None,
            "decided_at": None,
            "status": "PENDING",
        }
    )
    store.reentries[rec["id"]] = rec
    case["status"] = "REENTRY_REVIEW"
    touch(case)
    return response.obj(serialize(rec), 201)


@bp.get("/bit/reentry-evaluations/<rid>")
def get_reentry(rid):
    require_auth(REENTRY_READ_ROLES)
    rec = get_or_404(store.reentries, rid, "re-entry evaluation")
    return response.obj(serialize(rec))


@bp.get("/bit/reentry-evaluations")
def list_reentries():
    require_auth(REENTRY_READ_ROLES)
    q = request.args
    return list_response(
        store.reentries,
        [
            ("case_id", q.get("case_id")),
            ("petitioned_by", q.get("petitioned_by")),
            ("decided_by", q.get("decided_by")),
            ("leave_decision_id", q.get("leave_decision_id")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/reentry-evaluations/<rid>/decide")
def decide_reentry(rid):
    uid, _ = require_auth(["DeanOfStudents"])
    rec = get_or_404(store.reentries, rid, "re-entry evaluation")
    if rec["status"] != "PENDING":
        raise ApiError(E.ERR_DECISION_NOT_PENDING, 409, "decide requires evaluation PENDING")
    # Segregation: the dean who granted the leave cannot rule on the return.
    leave = store.leave_decisions.get(rec["leave_decision_id"])
    if leave is not None and uid == leave["decided_by"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES,
            403,
            "re-entry decider must differ from the original leave decider",
        )
    b = body()
    outcome = b.get("outcome")
    if outcome not in ("APPROVED_WITH_CONDITIONS", "DENIED"):
        raise ApiError(
            E.ERR_VALIDATION, 400, "outcome must be APPROVED_WITH_CONDITIONS or DENIED"
        )
    rationale = b.get("rationale")
    if not isinstance(rationale, str) or not rationale:
        raise ApiError(E.ERR_VALIDATION, 400, "rationale is required")
    conditions = b.get("conditions")
    if outcome == "APPROVED_WITH_CONDITIONS" and (
        not isinstance(conditions, list) or len(conditions) == 0
    ):
        raise ApiError(
            E.ERR_CONDITIONS_REQUIRED,
            400,
            "APPROVED_WITH_CONDITIONS requires a non-empty conditions array",
        )

    rec["outcome"] = outcome
    rec["rationale"] = rationale
    rec["decided_by"] = uid
    rec["decided_at"] = now()
    case = store.cases.get(rec["case_id"])

    if outcome == "APPROVED_WITH_CONDITIONS":
        rec["status"] = "APPROVED"
        rec["conditions"] = conditions
        if case is not None:
            case["status"] = "PLAN_ACTIVE"
            case["consecutive_stable_checkins"] = 0
            touch(case)
            student = store.students.get(case["student_id"])
            if student is not None:
                student["enrollment_status"] = "ENROLLED"
                touch(student)
            for p in store.plans.values():
                if p["case_id"] == case["id"] and p["status"] == "SUSPENDED":
                    p["status"] = "ACTIVE"
                    p["reentry_conditions"] = conditions
                    touch(p)
            # Fixed post-re-entry horizon of exactly seven days, regardless of tier.
            schedule_checkin(
                case["id"], now() + timedelta(days=REENTRY_FIRST_CHECKIN_DAYS)
            )
    else:
        rec["status"] = "DENIED"
        if case is not None:
            case["status"] = "ON_LEAVE"
            touch(case)
    touch(rec)
    return response.obj(serialize(rec))
