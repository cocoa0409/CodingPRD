"""Backdrop, Photographer, and CaptureSlot routes (scheduling + overlap rules)."""
from flask import Blueprint, request

import db
import store
from common import (
    PHOTOGRAPHER_BUFFER_MIN,
    get_body,
    optional_bool,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response

bp = Blueprint("scheduling", __name__)

ALL_OPERATORS = ["SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk"]


# ---------------------------------------------------------------------------
# Backdrops
# ---------------------------------------------------------------------------
@bp.route("/api/backdrops", methods=["POST"])
def create_backdrop():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()
    require_fields(body, ["picture_day_session_id", "label"])
    sid = require_str(body, "picture_day_session_id")
    label = require_str(body, "label")
    active = optional_bool(body, "active", True)
    with db.LOCK:
        store.get_session(sid)
        row = store.new_row("backdrop", {
            "picture_day_session_id": sid,
            "label": label,
            "active": active,
        })
        db.backdrops[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/backdrops", methods=["GET"])
def list_backdrops():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    rows = list(db.backdrops.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/backdrops/<rid>", methods=["GET"])
def get_backdrop(rid):
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    return object_response(store.serialize(store.get_backdrop(rid)))


# ---------------------------------------------------------------------------
# Photographers
# ---------------------------------------------------------------------------
@bp.route("/api/photographers", methods=["POST"])
def create_photographer():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()
    require_fields(body, ["picture_day_session_id", "full_name"])
    sid = require_str(body, "picture_day_session_id")
    full_name = require_str(body, "full_name")
    with db.LOCK:
        store.get_session(sid)
        row = store.new_row("photographer", {
            "picture_day_session_id": sid,
            "full_name": full_name,
        })
        db.photographers[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/photographers", methods=["GET"])
def list_photographers():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    rows = list(db.photographers.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/photographers/<rid>", methods=["GET"])
def get_photographer(rid):
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    return object_response(store.serialize(store.get_photographer(rid)))


# ---------------------------------------------------------------------------
# Capture slots
# ---------------------------------------------------------------------------
@bp.route("/api/capture-slots", methods=["POST"])
def create_capture_slot():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()
    require_fields(body, [
        "picture_day_session_id", "backdrop_id", "photographer_id",
        "homeroom", "start_minute", "end_minute",
    ])
    sid = require_str(body, "picture_day_session_id")
    backdrop_id = require_str(body, "backdrop_id")
    photographer_id = require_str(body, "photographer_id")
    homeroom = require_str(body, "homeroom")
    start_minute = require_int(body, "start_minute")
    end_minute = require_int(body, "end_minute")

    if start_minute < 0 or end_minute < 0:
        raise err("ERR_INVALID_REQUEST", "minutes must be >= 0")
    if end_minute <= start_minute:
        raise err("ERR_INVALID_REQUEST", "end_minute must be greater than start_minute")

    with db.LOCK:
        # FK existence (priority 5).
        store.get_session(sid)
        store.get_backdrop(backdrop_id)
        store.get_photographer(photographer_id)

        scheduled = [
            s for s in db.capture_slots.values()
            if s["picture_day_session_id"] == sid and s["status"] == "SCHEDULED"
        ]
        # Backdrop check first: half-open overlap, adjacency allowed.
        for s in scheduled:
            if s["backdrop_id"] != backdrop_id:
                continue
            if start_minute < s["end_minute"] and s["start_minute"] < end_minute:
                raise err("ERR_BACKDROP_DOUBLE_BOOKED", "Backdrop is double-booked")
        # Photographer check second: buffer-inflated overlap, adjacency conflicts.
        buf = PHOTOGRAPHER_BUFFER_MIN
        for s in scheduled:
            if s["photographer_id"] != photographer_id:
                continue
            if start_minute < s["end_minute"] + buf and s["start_minute"] < end_minute + buf:
                raise err("ERR_PHOTOGRAPHER_DOUBLE_BOOKED", "Photographer is double-booked")

        row = store.new_row("slot", {
            "picture_day_session_id": sid,
            "backdrop_id": backdrop_id,
            "photographer_id": photographer_id,
            "homeroom": homeroom,
            "start_minute": start_minute,
            "end_minute": end_minute,
            "status": "SCHEDULED",
        })
        db.capture_slots[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/capture-slots", methods=["GET"])
def list_capture_slots():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    backdrop_id = request.args.get("backdrop_id")
    photographer_id = request.args.get("photographer_id")
    status = request.args.get("status")
    rows = list(db.capture_slots.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    if backdrop_id is not None:
        rows = [r for r in rows if r["backdrop_id"] == backdrop_id]
    if photographer_id is not None:
        rows = [r for r in rows if r["photographer_id"] == photographer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/capture-slots/<rid>", methods=["GET"])
def get_capture_slot(rid):
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    return object_response(store.serialize(store.get_slot(rid)))


@bp.route("/api/capture-slots/<rid>/complete", methods=["POST"])
def complete_slot(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        slot = store.get_slot(rid)
        session = store.get_session(slot["picture_day_session_id"])
        if session["status"] != "CAPTURE_OPEN":
            raise err("ERR_SESSION_NOT_CAPTURING", "Session is not capturing")
        if slot["status"] != "SCHEDULED":
            raise err("ERR_SLOT_NOT_SCHEDULED", "Slot is not SCHEDULED")
        slot["status"] = "COMPLETED"
        store.touch(slot)
    return object_response(store.serialize(slot))


@bp.route("/api/capture-slots/<rid>/cancel", methods=["POST"])
def cancel_slot(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        slot = store.get_slot(rid)
        if slot["status"] != "SCHEDULED":
            raise err("ERR_SLOT_NOT_CANCELLABLE", "Slot is not SCHEDULED")
        slot["status"] = "CANCELLED"
        store.touch(slot)
    return object_response(store.serialize(slot))
