"""Interview endpoints (PRD 3.5): scheduling with the 15-minute buffer rule
and conclusion outcomes."""
from datetime import timedelta

from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    CONCLUDE_OUTCOMES,
    INTERVIEWEE_ROLES,
    bump,
    case_posture,
    get_case,
    get_interview,
    interview_view,
    paginate,
)
from util import as_str, body, opt_str, pagination_args, req, req_dt, req_enum, req_str

bp = Blueprint("interviews", __name__)

BUFFER = timedelta(minutes=15)


@bp.post("/hotline/interviews")
def create_interview():
    user_id, _ = auth(["Investigator"])
    data = body()
    case_id = req(data, "case_id")
    if not isinstance(case_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field case_id must be a string")
    case = get_case(case_id)
    # Actor-resource binding (priority 4): caller must be the assigned investigator.
    if case["assigned_investigator_id"] != user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_INVESTIGATOR",
            403,
            "Caller is not the case's assigned investigator",
        )
    interviewee_role = req_enum(data, "interviewee_role", INTERVIEWEE_ROLES)
    interviewee_identifier = req_str(data, "interviewee_identifier")
    scheduled_start = req_dt(data, "scheduled_start")
    scheduled_end = req_dt(data, "scheduled_end")
    if scheduled_end <= scheduled_start:
        raise ApiError(
            "ERR_INVALID_INTERVAL",
            400,
            "scheduled_end must be strictly later than scheduled_start",
        )
    if case["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_CASE_NOT_UNDER_INVESTIGATION",
            409,
            "Interview scheduling requires case UNDER_INVESTIGATION",
        )
    if case_posture(case) != "NORMAL":
        raise ApiError(
            "ERR_LEGAL_HOLD_FREEZE", 409, "Case is FROZEN by an ACTIVE legal hold"
        )
    # 15-minute buffer against every other SCHEDULED/CONDUCTED interview of this
    # investigator (half-open intervals).
    for other in DB["interviews"].values():
        if other["investigator_id"] != user_id:
            continue
        if other["status"] not in ("SCHEDULED", "CONDUCTED"):
            continue
        if scheduled_start < other["scheduled_end"] + BUFFER and other[
            "scheduled_start"
        ] < scheduled_end + BUFFER:
            raise ApiError(
                "ERR_INTERVIEW_OVERLAP",
                409,
                "Interview violates the 15-minute buffer for this investigator",
            )

    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "investigator_id": user_id,
        "interviewee_role": interviewee_role,
        "interviewee_identifier": interviewee_identifier,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "summary": None,
        "conducted_at": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["interviews"][rec["id"]] = rec
    return ok(interview_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/interviews")
def list_interviews(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [i for i in DB["interviews"].values() if i["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([interview_view(i) for i in page], total, limit, offset)


@bp.post("/hotline/interviews/<iid>/conclude")
def conclude_interview(iid):
    user_id, role = auth(["Investigator", "ComplianceOfficer"])
    interview = get_interview(iid)
    data = body()
    outcome = req_enum(data, "outcome", CONCLUDE_OUTCOMES)
    # Binding (priority 4): CONDUCTED/NO_SHOW are owner-only; CANCELLED is the
    # owning investigator or any ComplianceOfficer.
    if outcome in ("CONDUCTED", "NO_SHOW"):
        if user_id != interview["investigator_id"]:
            raise ApiError(
                "ERR_NOT_ASSIGNED_INVESTIGATOR",
                403,
                "Caller is not the interview's owning investigator",
            )
    else:  # CANCELLED
        if role == "Investigator" and user_id != interview["investigator_id"]:
            raise ApiError(
                "ERR_NOT_ASSIGNED_INVESTIGATOR",
                403,
                "Caller is not the interview's owning investigator",
            )
    summary = opt_str(data, "summary")
    if outcome == "CONDUCTED":
        if summary is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "summary is required when concluding with outcome CONDUCTED",
            )
        summary = as_str(summary, "summary", min_len=50)
    if interview["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INTERVIEW_NOT_SCHEDULED", 409, "Conclude requires interview SCHEDULED"
        )

    interview["status"] = outcome
    if outcome == "CONDUCTED":
        interview["conducted_at"] = now_dt()
    if summary is not None:
        interview["summary"] = summary
    bump(interview)
    return ok(interview_view(interview))
