"""Retaliation flag endpoints (PRD 3.7): filing (reporter/officer channels),
dismissal, and the escalation cascade at score >= 4."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    ESCALATION_THRESHOLD,
    FLAG_WEIGHT,
    OFFICER_FLAG_CHANNELS,
    bump,
    escalate_retaliation,
    flag_view,
    get_case,
    get_flag,
    paginate,
    retaliation_risk_score,
)
from util import body, pagination_args, req_str

bp = Blueprint("retaliation", __name__)


@bp.post("/hotline/cases/<cid>/retaliation-flags")
def create_flag(cid):
    user_id, role = auth(["HotlineReporter", "ComplianceOfficer"])
    case = get_case(cid)
    # Reporter channel binds X-User-ID to the case's reporter_access_key.
    if role == "HotlineReporter" and user_id != case["reporter_access_key"]:
        raise ApiError(
            "ERR_REPORTER_ACCESS_DENIED", 403, "X-User-ID does not match the case access key"
        )
    data = body()
    description = req_str(data, "description", min_len=10)
    if role == "HotlineReporter":
        # The reporter channel forces REPORTER_CHECKIN.
        reported_via = "REPORTER_CHECKIN"
    else:
        reported_via = data.get("reported_via")
        if reported_via not in OFFICER_FLAG_CHANNELS:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "reported_via must be HR_SIGNAL or MANUAL for officer-filed flags",
            )
    # Completeness gate (priority 14): the case must be inside the monitoring window.
    if case["status"] != "MONITORING":
        raise ApiError(
            "ERR_MONITORING_WINDOW_INACTIVE",
            409,
            "Retaliation flags are only accepted while the case is MONITORING",
        )

    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "reported_via": reported_via,
        "description": description,
        "weight": FLAG_WEIGHT[reported_via],
        "flagged_at": now_dt(),
        "status": "OPEN",
        "dismissed_by_id": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["retaliation_flags"][rec["id"]] = rec

    # Escalation cascade: score (including the new flag) reaching >= 4 while the
    # case is MONITORING escalates contributing flags and reopens the case.
    if (
        retaliation_risk_score(case) >= ESCALATION_THRESHOLD
        and case["status"] == "MONITORING"
    ):
        escalate_retaliation(case, role, user_id)
    return ok(flag_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/retaliation-flags")
def list_flags(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [f for f in DB["retaliation_flags"].values() if f["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [f for f in records if f["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([flag_view(f) for f in page], total, limit, offset)


@bp.post("/hotline/retaliation-flags/<fid>/dismiss")
def dismiss_flag(fid):
    user_id, _ = auth(["ComplianceOfficer"])
    flag = get_flag(fid)
    if flag["status"] != "OPEN":
        raise ApiError("ERR_FLAG_NOT_OPEN", 409, "Dismiss requires flag OPEN")
    flag["status"] = "DISMISSED"
    flag["dismissed_by_id"] = user_id
    bump(flag)
    return ok(flag_view(flag))
