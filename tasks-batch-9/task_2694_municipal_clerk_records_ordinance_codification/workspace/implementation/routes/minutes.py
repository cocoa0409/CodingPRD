"""Minutes drafting, submission and the correction cycle."""
from flask import Blueprint

import domain
from core import (ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK, STAFF_ROLES, ApiError,
                  authorize, body_dict, db, fetch, listing, occ, ok, q,
                  req_str, touch)

bp = Blueprint("minutes", __name__)


@bp.route("/clerk/meetings/<meeting_id>/minutes", methods=["GET"])
def list_minutes_of_meeting(meeting_id):
    authorize(STAFF_ROLES)
    fetch(db.meetings, meeting_id, "ERR_MEETING_NOT_FOUND")
    return listing(domain.minutes_of(meeting_id))


@bp.route("/clerk/minutes/<minutes_id>", methods=["GET"])
def get_minutes(minutes_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.minutes, minutes_id, "ERR_MINUTES_NOT_FOUND"))


@bp.route("/clerk/minutes", methods=["GET"])
def list_minutes():
    authorize(STAFF_ROLES)
    return listing(list(db.minutes.values()),
                   {"meeting_id": q("meeting_id"), "status": q("status")})


@bp.route("/clerk/minutes/<minutes_id>", methods=["PUT"])
def write_minutes(minutes_id):
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    minutes = fetch(db.minutes, minutes_id, "ERR_MINUTES_NOT_FOUND")
    body = body_dict()
    text_body = req_str(body, "text_body", allow_empty=True)
    if minutes["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_MINUTES_STATE", 409)
    minutes["text_body"] = text_body
    touch(minutes)
    return ok(minutes)


@bp.route("/clerk/minutes/<minutes_id>/submit", methods=["POST"])
def submit_minutes(minutes_id):
    authorize((ROLE_CITY_CLERK,))
    minutes = fetch(db.minutes, minutes_id, "ERR_MINUTES_NOT_FOUND")
    if minutes["status"] != "DRAFT" or minutes["text_body"] == "":
        raise ApiError("ERR_INVALID_MINUTES_STATE", 409)
    meeting = db.meetings.get(minutes["meeting_id"])
    if meeting is None or meeting["status"] != "ADJOURNED":
        raise ApiError("ERR_INVALID_MEETING_STATE", 409)
    minutes["status"] = "SUBMITTED"
    touch(minutes)
    return ok(minutes)


@bp.route("/clerk/minutes/<minutes_id>/corrections", methods=["POST"])
def open_correction(minutes_id):
    authorize((ROLE_CITY_CLERK, ROLE_DEPUTY_CLERK))
    minutes = fetch(db.minutes, minutes_id, "ERR_MINUTES_NOT_FOUND")
    body = body_dict()
    corrected = req_str(body, "corrected_text_body")
    occ(body, "expected_minutes_version", minutes, "ERR_STALE_MINUTES_VERSION")
    if minutes["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_MINUTES_STATE", 409)
    minutes["status"] = "CORRECTION_PENDING"
    minutes["pending_correction_text"] = corrected
    minutes["correction_count"] = minutes["correction_count"] + 1
    touch(minutes)
    return ok(minutes)
