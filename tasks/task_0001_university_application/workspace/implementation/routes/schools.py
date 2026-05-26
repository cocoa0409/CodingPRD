"""School endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import auth_required
from response import ok_object, ok_array
from routes._helpers import parse_pagination, paginate, get_body, require_fields, order_by_created_at
from services.common import new_common_fields

bp = Blueprint("schools", __name__)

TRACK_VALS = {"EARLY_DECISION", "EARLY_ACTION", "REGULAR", "ROLLING"}


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@bp.post("/schools")
def create_school():
    auth_required({"PlatformAdmin"})()
    body = get_body()
    require_fields(body, [
        "name", "state_code", "admission_track", "deadline_iso",
        "decision_release_iso", "target_class_size", "assumed_yield_rate",
        "in_state_tuition_cents", "out_of_state_tuition_cents", "international_tuition_cents",
    ])
    if not isinstance(body["name"], str) or not body["name"]:
        raise APIError(ERR_INVALID_REQUEST, 400, "name must be non-empty string")
    for s in db.schools.values():
        if s["name"] == body["name"]:
            raise APIError(ERR_INVALID_REQUEST, 400, "School name already exists")
    state_code = body["state_code"]
    if not isinstance(state_code, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "state_code must be string")
    track = body["admission_track"]
    if track not in TRACK_VALS:
        raise APIError(ERR_INVALID_REQUEST, 400, "admission_track invalid")
    deadline = body["deadline_iso"]
    decision_release = body["decision_release_iso"]
    if not isinstance(deadline, str) or not isinstance(decision_release, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "deadline_iso/decision_release_iso must be strings")
    if not decision_release > deadline:
        raise APIError(ERR_INVALID_REQUEST, 400, "decision_release_iso must be > deadline_iso")
    tcs = body["target_class_size"]
    if not _is_int(tcs) or tcs < 1 or tcs > 10000:
        raise APIError(ERR_INVALID_REQUEST, 400, "target_class_size out of range")
    yr = body["assumed_yield_rate"]
    if not isinstance(yr, (int, float)) or isinstance(yr, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, "assumed_yield_rate must be number")
    yr = float(yr)
    if yr < 0.05 or yr > 1.00:
        raise APIError(ERR_INVALID_REQUEST, 400, "assumed_yield_rate out of range")
    in_t = body["in_state_tuition_cents"]
    out_t = body["out_of_state_tuition_cents"]
    intl_t = body["international_tuition_cents"]
    for label, v in [("in_state", in_t), ("out_of_state", out_t), ("international", intl_t)]:
        if not _is_int(v) or v < 0:
            raise APIError(ERR_INVALID_REQUEST, 400, f"{label}_tuition_cents must be non-negative integer")
    if not (in_t <= out_t <= intl_t):
        raise APIError(ERR_INVALID_REQUEST, 400, "tuition tiers must satisfy in_state <= out_of_state <= international")

    common = new_common_fields()
    school = {
        **common,
        "name": body["name"],
        "state_code": state_code,
        "admission_track": track,
        "deadline_iso": deadline,
        "decision_release_iso": decision_release,
        "target_class_size": tcs,
        "assumed_yield_rate": yr,
        "in_state_tuition_cents": in_t,
        "out_of_state_tuition_cents": out_t,
        "international_tuition_cents": intl_t,
        "admitted_count": 0,
        "enrolled_count": 0,
        "declined_count": 0,
        "denied_count": 0,
        "yield_posture": "OPEN",
    }
    db.schools[school["id"]] = school
    return ok_object(school, http_status=201)


@bp.get("/schools/<sid>")
def read_school(sid):
    auth_required({"Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"})()
    s = db.schools.get(sid)
    if s is None:
        raise APIError(ERR_NOT_FOUND, 404, "School not found")
    return ok_object(s)


@bp.get("/schools")
def list_schools():
    auth_required({"Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"})()
    track = request.args.get("admission_track")
    limit, offset = parse_pagination()
    items = [s for s in db.schools.values()
             if track is None or s["admission_track"] == track]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(page, limit, offset, total)
