"""ToolingJob advance endpoint."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_TOOLING_JOB_NOT_FOUND,
    ERR_PLATING_BATH_NOT_FOUND, ERR_TOOLING_JOB_INVALID_STATE,
)
from middleware import get_auth, require_role
from response import success_object
from services import scheduling

bp = Blueprint("tooling", __name__)

EVENTS = {"START_CUT", "CUT_DONE", "START_PLATING", "PLATING_DONE", "MARK_FAILED"}


@bp.route("/tooling-jobs/<jid>/advance", methods=["POST"])
def advance_tooling_job(jid):
    _, role = get_auth()
    require_role(role, ["PressOperator"])
    job = db.tooling_jobs.get(jid)
    if not job:
        raise ApiError(ERR_TOOLING_JOB_NOT_FOUND, "Tooling job id does not exist", 404)

    body = request.get_json(silent=True) or {}
    event = body.get("event")
    if event not in EVENTS:
        raise ApiError(ERR_INVALID_REQUEST, "invalid tooling advance event", 400)

    if event == "START_CUT":
        if job["status"] != "QUEUED":
            raise ApiError(ERR_TOOLING_JOB_INVALID_STATE, "START_CUT requires QUEUED", 409)
        job["status"] = "CUTTING"

    elif event == "CUT_DONE":
        if job["status"] != "CUTTING":
            raise ApiError(ERR_TOOLING_JOB_INVALID_STATE, "CUT_DONE requires CUTTING", 409)
        job["status"] = "AWAITING_BATH"

    elif event == "START_PLATING":
        if job["status"] != "AWAITING_BATH":
            raise ApiError(ERR_TOOLING_JOB_INVALID_STATE, "START_PLATING requires AWAITING_BATH", 409)
        bath_id = body.get("plating_bath_id")
        start = body.get("plating_start")
        end = body.get("plating_end")
        if not isinstance(bath_id, str) or not bath_id:
            raise ApiError(ERR_INVALID_REQUEST, "plating_bath_id is required", 400)
        bath = db.plating_baths.get(bath_id)
        if not bath:
            raise ApiError(ERR_PLATING_BATH_NOT_FOUND, "plating_bath_id does not exist", 404)
        if (not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 0 or end < start):
            raise ApiError(ERR_INVALID_REQUEST, "plating_start/plating_end must be valid closed-interval hours", 400)
        scheduling.check_bath_booking(bath, start, end, exclude_job_id=job["id"])
        job["plating_bath_id"] = bath_id
        job["plating_start"] = start
        job["plating_end"] = end
        job["status"] = "PLATING"

    elif event == "PLATING_DONE":
        if job["status"] != "PLATING":
            raise ApiError(ERR_TOOLING_JOB_INVALID_STATE, "PLATING_DONE requires PLATING", 409)
        job["status"] = "STAMPER_READY"

    elif event == "MARK_FAILED":
        if job["status"] not in ("CUTTING", "PLATING"):
            raise ApiError(ERR_TOOLING_JOB_INVALID_STATE, "MARK_FAILED requires CUTTING or PLATING", 409)
        job["attempt_count"] += 1
        job["defect_note"] = body.get("defect_note")
        if job["status"] == "PLATING":
            # release the bath booking
            job["plating_bath_id"] = None
            job["plating_start"] = None
            job["plating_end"] = None
        job["status"] = "FAILED"
        if job["attempt_count"] < 3:
            # auto-requeue
            job["status"] = "QUEUED"

    job["version"] += 1
    job["updated_at"] = db.timestamp_now()
    return success_object(serializers.tooling_job(job))
