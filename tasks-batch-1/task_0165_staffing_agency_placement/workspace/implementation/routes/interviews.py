"""Interview routes (PRD 3.3)."""

from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, ownership

bp = Blueprint("interviews", __name__)


@bp.route("/staffing/submissions/<sid>/interviews", methods=["POST"])
def create_interview(sid):
    user_id, role = get_user_context()
    require_role(role, {"Client"})
    # Existence: parent submission first (left-to-right).
    sub = common.get_or_404(db.submissions, sid, errors.ERR_SUBMISSION_NOT_FOUND)
    ownership.client_owns(user_id, ownership.submission_client(sub))

    body = get_json_body()
    scheduled_start = common.require_str(body, "scheduled_start")
    scheduled_end = common.require_str(body, "scheduled_end")
    start_dt = common._parse_dt(scheduled_start)
    end_dt = common._parse_dt(scheduled_end)
    if not (end_dt > start_dt):
        raise ApiError(errors.ERR_VALIDATION, 422, "scheduled_end must be after scheduled_start.")

    # State (priority 5): submission must be CLIENT_REVIEW; job order OPEN.
    if sub["status"] != "CLIENT_REVIEW":
        raise ApiError(errors.ERR_SUBMISSION_BAD_STATE, 409, "Submission is not CLIENT_REVIEW.")
    jo = db.job_orders.get(sub["job_order_id"])
    if jo is None or jo["status"] != "OPEN":
        raise ApiError(errors.ERR_JOB_ORDER_NOT_OPEN, 409, "Job order is not OPEN.")

    rec = common.init_mutable({
        "submission_id": sub["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "outcome": "PENDING",
    })
    db.interviews[rec["id"]] = rec

    # Side effect: submission CLIENT_REVIEW -> INTERVIEWING.
    sub["status"] = "INTERVIEWING"
    common.touch(sub)

    return object_response(serialize.interview(rec), 201)


@bp.route("/staffing/submissions/<sid>/interviews", methods=["GET"])
def list_interviews(sid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client"})
    sub = common.get_or_404(db.submissions, sid, errors.ERR_SUBMISSION_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, ownership.submission_client(sub))
    limit, offset = parse_pagination()

    rows = [iv for iv in db.interviews.values() if iv["submission_id"] == sub["id"]]
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.interview(r) for r in page], limit, offset, total)


@bp.route("/staffing/interviews/<iid>", methods=["PATCH"])
def patch_interview(iid):
    user_id, role = get_user_context()
    require_role(role, {"Client"})
    rec = common.get_or_404(db.interviews, iid, errors.ERR_INTERVIEW_NOT_FOUND)
    ownership.client_owns(user_id, ownership.interview_client(rec))

    body = get_json_body()
    outcome = common.require_enum(body, "outcome", {"PASSED", "FAILED"})

    # State (priority 6): record-outcome requires outcome == PENDING.
    if rec["outcome"] != "PENDING":
        raise ApiError(errors.ERR_INTERVIEW_BAD_STATE, 409, "Interview outcome is already recorded.")

    rec["outcome"] = outcome
    common.touch(rec)
    return object_response(serialize.interview(rec), 200)
