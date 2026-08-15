"""RoadSegment + CoursePermit endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_PERMIT_WINDOW_CONFLICT, not_found
from middleware import require_roles
from response import success_object, success_list, paginate
from util import stamp_common, touch, require_fields, parse_dt

bp = Blueprint("segments", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")
BUFFER = timedelta(minutes=30)


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


def get_segment_or_404(seg_id):
    seg = db.road_segments.get(seg_id)
    if not seg:
        raise not_found("road segment not found")
    return seg


def get_permit_or_404(permit_id):
    p = db.course_permits.get(permit_id)
    if not p:
        raise not_found("permit not found")
    return p


@bp.post("/events/<event_id>/road-segments")
def create_segment(event_id):
    require_roles("PermitCoordinator")
    get_event_or_404(event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["name", "length_km", "closure_start", "closure_end"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError(ERR_VALIDATION, "name must be a non-empty string", 400)
    if isinstance(body["length_km"], bool) or not isinstance(body["length_km"], (int, float)):
        raise ApiError(ERR_VALIDATION, "length_km must be a number", 400)
    cs = parse_dt(body["closure_start"])
    ce = parse_dt(body["closure_end"])
    if ce <= cs:
        raise ApiError(ERR_VALIDATION, "closure_end must be later than closure_start", 400)
    seg = stamp_common({
        "event_id": event_id,
        "name": body["name"],
        "length_km": body["length_km"],
        "closure_start": body["closure_start"],
        "closure_end": body["closure_end"],
    })
    db.road_segments[seg["id"]] = seg
    return success_object(seg, status=201)


@bp.get("/events/<event_id>/road-segments")
def list_segments(event_id):
    require_roles(*ALL)
    get_event_or_404(event_id)
    items = [s for s in db.road_segments.values() if s["event_id"] == event_id]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/road-segments/<seg_id>")
def get_segment(seg_id):
    require_roles(*ALL)
    return success_object(get_segment_or_404(seg_id))


@bp.post("/road-segments/<seg_id>/permits")
def create_permit(seg_id):
    require_roles("PermitCoordinator")
    seg = get_segment_or_404(seg_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["authority_name", "requested_start", "requested_end"])
    if not isinstance(body["authority_name"], str) or not body["authority_name"]:
        raise ApiError(ERR_VALIDATION, "authority_name must be a non-empty string", 400)
    rs = parse_dt(body["requested_start"])
    re_ = parse_dt(body["requested_end"])
    if re_ <= rs:
        raise ApiError(ERR_VALIDATION, "requested_end must be later than requested_start", 400)
    p = stamp_common({
        "road_segment_id": seg["id"],
        "authority_name": body["authority_name"],
        "requested_start": body["requested_start"],
        "requested_end": body["requested_end"],
        "status": "DRAFT",
        "rejection_reason": None,
    })
    db.course_permits[p["id"]] = p
    return success_object(p, status=201)


@bp.get("/road-segments/<seg_id>/permits")
def list_permits(seg_id):
    require_roles(*ALL)
    seg = get_segment_or_404(seg_id)
    items = [p for p in db.course_permits.values() if p["road_segment_id"] == seg["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/permits/<permit_id>")
def get_permit(permit_id):
    require_roles(*ALL)
    return success_object(get_permit_or_404(permit_id))


@bp.post("/permits/<permit_id>/submit")
def submit_permit(permit_id):
    require_roles("PermitCoordinator")
    p = get_permit_or_404(permit_id)
    if p["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, f"cannot submit from {p['status']}", 409)
    p["status"] = "SUBMITTED"
    p["rejection_reason"] = None
    touch(p)
    return success_object(p)


@bp.post("/permits/<permit_id>/approve")
def approve_permit(permit_id):
    require_roles("PermitCoordinator")
    p = get_permit_or_404(permit_id)
    if p["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"cannot approve from {p['status']}", 409)
    my_start = parse_dt(p["requested_start"])
    my_end = parse_dt(p["requested_end"])
    for other in db.course_permits.values():
        if other["id"] == p["id"]:
            continue
        if other["road_segment_id"] != p["road_segment_id"] or other["status"] != "APPROVED":
            continue
        o_start = parse_dt(other["requested_start"])
        o_end = parse_dt(other["requested_end"])
        if my_start < o_end + BUFFER and o_start < my_end + BUFFER:
            raise ApiError(ERR_PERMIT_WINDOW_CONFLICT, "permit window conflict within 30-minute buffer", 409)
    p["status"] = "APPROVED"
    touch(p)
    return success_object(p)


@bp.post("/permits/<permit_id>/reject")
def reject_permit(permit_id):
    require_roles("PermitCoordinator")
    p = get_permit_or_404(permit_id)
    if p["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"cannot reject from {p['status']}", 409)
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ApiError(ERR_VALIDATION, "reason must be a string", 400)
    p["status"] = "REJECTED"
    p["rejection_reason"] = reason
    touch(p)
    return success_object(p)
