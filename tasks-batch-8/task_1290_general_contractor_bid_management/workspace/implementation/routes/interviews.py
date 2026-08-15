from flask import Blueprint

import errors
from db import DB, CLOCK, new_id, stamp_new, touch, parse_iso, format_ts
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_string,
)
from response import success_object

bp = Blueprint("interviews", __name__)


def serialize_interview(iv):
    return {
        "id": iv["id"],
        "bid_id": iv["bid_id"],
        "interview_room": iv["interview_room"],
        "scheduled_start": iv["scheduled_start"],
        "scheduled_end": iv["scheduled_end"],
        "outcome_notes": iv["outcome_notes"],
        "status": iv["status"],
        "created_at": iv["created_at"],
        "updated_at": iv["updated_at"],
        "version": iv["version"],
    }


@bp.post("/post-bid-interviews")
def create_interview():
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    body = get_json_body()
    reject_unexpected(body, {"bid_id", "interview_room", "scheduled_start", "scheduled_end"})
    require_fields(body, ["bid_id", "interview_room", "scheduled_start", "scheduled_end"])
    bid_id = body["bid_id"]
    if not isinstance(bid_id, str):
        raise errors.err_invalid_request("bid_id must be a string")
    bid = DB.bids.get(bid_id)
    if bid is None:
        raise errors.err_bid_not_found()
    pkg = DB.bid_packages.get(bid["bid_package_id"])
    if pkg is None or pkg["status"] not in ("TABULATED", "RECOMMENDATION_PENDING"):
        raise errors.err_package_invalid_state(
            "Interviews require the package in TABULATED or RECOMMENDATION_PENDING")
    if bid["status"] != "SUBMITTED":
        raise errors.err_bid_invalid_state()
    room = require_string(body, "interview_room")
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if not isinstance(start_raw, str) or start_dt is None:
        raise errors.err_invalid_request("scheduled_start must be a valid ISO 8601 timestamp")
    if not isinstance(end_raw, str) or end_dt is None:
        raise errors.err_invalid_request("scheduled_end must be a valid ISO 8601 timestamp")
    if start_dt >= end_dt:
        raise errors.err_invalid_time_range()
    # Half-open [start, end) overlap against other SCHEDULED interviews in the same room.
    for iv in DB.interviews.values():
        if iv["interview_room"] != room or iv["status"] != "SCHEDULED":
            continue
        if start_dt < iv["_end_dt"] and iv["_start_dt"] < end_dt:
            raise errors.err_room_overlap()
    iv = {
        "id": new_id(),
        "bid_id": bid_id,
        "interview_room": room,
        "scheduled_start": format_ts(start_dt),
        "scheduled_end": format_ts(end_dt),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "outcome_notes": None,
        "status": "SCHEDULED",
    }
    stamp_new(iv)
    iv["_created_at_dt"] = CLOCK.now()
    DB.interviews[iv["id"]] = iv
    return success_object(serialize_interview(iv), 201)


@bp.post("/post-bid-interviews/<iv_id>/complete")
def complete_interview(iv_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    iv = DB.interviews.get(iv_id)
    if iv is None:
        raise errors.err_resource_not_found()
    body = get_json_body()
    reject_unexpected(body, {"outcome_notes"})
    require_fields(body, ["outcome_notes"])
    notes = require_string(body, "outcome_notes")
    if iv["status"] != "SCHEDULED":
        raise errors.err_invalid_resource_state("Complete requires SCHEDULED")
    iv["status"] = "HELD"
    iv["outcome_notes"] = notes
    touch(iv)
    return success_object(serialize_interview(iv))
