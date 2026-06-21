"""Hearing endpoints + state machine + courtroom double-booking (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_COURTROOM_DOUBLE_BOOKED,
)
from middleware import require_auth, get_json_body, paginate_params, slice_page
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    assert_case_not_terminal,
    require,
)

bp = Blueprint("hearings", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


@bp.post("/api/hearings")
def create_hearing():
    require_auth(["Clerk"])()
    body = get_json_body()

    case_id = body.get("case_id")
    case = get_case(case_id)
    assert_case_not_terminal(case)

    courtroom_code = body.get("courtroom_code")
    if not isinstance(courtroom_code, str) or courtroom_code == "":
        raise APIError(ERR_INVALID_REQUEST, 422, "courtroom_code is required")

    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    try:
        start = db.parse_iso_dt(start_raw)
        end = db.parse_iso_dt(end_raw)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_start/scheduled_end must be ISO 8601")
    if start is None or end is None:
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_start/scheduled_end are required")
    if not (end > start):
        raise APIError(ERR_INVALID_REQUEST, 422, "scheduled_end must be after scheduled_start")

    # Courtroom double-booking: half-open intervals [start,end) vs existing
    # SCHEDULED hearings in the same courtroom; back-to-back is allowed (§3.8).
    for h in db.hearings.values():
        if h["courtroom_code"] != courtroom_code:
            continue
        if h["status"] != "SCHEDULED":
            continue
        h_start = db.parse_iso_dt(h["scheduled_start"])
        h_end = db.parse_iso_dt(h["scheduled_end"])
        # half-open overlap: start < h_end AND h_start < end
        if start < h_end and h_start < end:
            raise APIError(ERR_COURTROOM_DOUBLE_BOOKED, 409, "Courtroom double-booked")

    hearing = {
        "case_id": case_id,
        "courtroom_code": courtroom_code,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
    }
    db.stamp_common(hearing)
    db.hearings[hearing["id"]] = hearing
    return ok_object(serialize(hearing), 201)


@bp.get("/api/hearings/<rid>")
def get_hearing(rid):
    require_auth(READ_ROLES)()
    h = require(db.hearings, rid, "Hearing")
    return ok_object(serialize(h), 200)


@bp.get("/api/hearings")
def list_hearings():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.hearings.values()))
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [h for h in items if h["case_id"] == case_id]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/api/hearings/<rid>/hold")
def hold_hearing(rid):
    require_auth(["Judge"])()
    h = require(db.hearings, rid, "Hearing")
    if h["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Hold requires SCHEDULED")
    h["status"] = "HELD"
    db.bump(h)
    return ok_object(serialize(h), 200)


@bp.post("/api/hearings/<rid>/cancel")
def cancel_hearing(rid):
    require_auth(["Clerk"])()
    h = require(db.hearings, rid, "Hearing")
    if h["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Cancel requires SCHEDULED")
    h["status"] = "CANCELLED"
    db.bump(h)
    return ok_object(serialize(h), 200)
