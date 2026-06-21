"""Board panel and hearing endpoints (PRD §3.7)."""
from datetime import datetime, timedelta

from flask import Blueprint

import db
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services.common import (
    get_body, require_fields, lookup, parse_pagination, paginate, is_int,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("hearings", __name__)


def _parse_dt(value):
    s = str(value)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---- Board panels ----------------------------------------------------------

@bp.post("/board-panels")
def create_panel():
    require_roles(["Assessor"])
    body = get_body()
    require_fields(body, ["name"])
    name = body["name"]
    if not isinstance(name, str):
        raise err("ERR_INVALID_REQUEST", "name must be a string")
    setup_buffer_minutes = body.get("setup_buffer_minutes", 15)
    if not is_int(setup_buffer_minutes) or setup_buffer_minutes < 0:
        raise err("ERR_INVALID_REQUEST", "setup_buffer_minutes must be a non-negative integer")

    record = {"name": name, "setup_buffer_minutes": setup_buffer_minutes}
    db.init_common(record)
    with db.LOCK:
        db.board_panels[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/board-panels/<panel_id>")
def get_panel(panel_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer"])
    return object_response(serialize(lookup(db.board_panels, panel_id)), 200)


@bp.get("/board-panels/<panel_id>/hearings")
def list_panel_hearings(panel_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer"])
    lookup(db.board_panels, panel_id)
    limit, offset = parse_pagination()
    items = [h for h in db.hearings.values() if h["board_panel_id"] == panel_id]
    window, total = paginate(items, limit, offset)
    return array_response(serialize_list(window), limit, offset, total, 200)


# ---- Hearings --------------------------------------------------------------

@bp.post("/hearings")
def schedule_hearing():
    require_roles(["HearingOfficer"])
    body = get_body()
    require_fields(body, ["appeal_id", "board_panel_id",
                          "hearing_officer_role_user_id", "starts_at", "ends_at"])
    appeal_id = body["appeal_id"]
    board_panel_id = body["board_panel_id"]
    officer_id = body["hearing_officer_role_user_id"]
    starts_at_raw = body["starts_at"]
    ends_at_raw = body["ends_at"]

    if not isinstance(appeal_id, str) or not isinstance(board_panel_id, str) \
            or not isinstance(officer_id, str):
        raise err("ERR_INVALID_REQUEST", "appeal_id/board_panel_id/officer id must be strings")

    starts_at = _parse_dt(starts_at_raw)
    ends_at = _parse_dt(ends_at_raw)
    if starts_at is None or ends_at is None:
        raise err("ERR_INVALID_REQUEST", "starts_at/ends_at must be ISO datetimes")
    if not (ends_at > starts_at):
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")

    with db.LOCK:
        lookup(db.appeals, appeal_id)
        panel = lookup(db.board_panels, board_panel_id)
        buffer = timedelta(minutes=panel["setup_buffer_minutes"])

        # Overlap + buffer conflict (PRD §3.7). Each existing SCHEDULED/HELD
        # hearing on this panel occupies [starts_at, ends_at + buffer); reject a
        # proposed [starts_at, ends_at) that intrudes on any such interval.
        for h in db.hearings.values():
            if h["board_panel_id"] != board_panel_id:
                continue
            if h["status"] not in ("SCHEDULED", "HELD"):
                continue
            ex_start = _parse_dt(h["starts_at"])
            ex_end = _parse_dt(h["ends_at"]) + buffer
            if starts_at < ex_end and ex_start < ends_at:
                raise err("ERR_PANEL_SLOT_CONFLICT",
                          "Hearing slot overlaps an existing slot plus buffer")

        record = {
            "appeal_id": appeal_id,
            "board_panel_id": board_panel_id,
            "hearing_officer_role_user_id": officer_id,
            "starts_at": starts_at_raw,
            "ends_at": ends_at_raw,
            "status": "SCHEDULED",
        }
        db.init_common(record)
        db.hearings[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/hearings/<hearing_id>")
def get_hearing(hearing_id):
    require_roles(["Assessor", "Reviewer", "HearingOfficer", "Taxpayer"])
    return object_response(serialize(lookup(db.hearings, hearing_id)), 200)


@bp.post("/hearings/<hearing_id>/hold")
def hold_hearing(hearing_id):
    user_id, _role = require_roles(["HearingOfficer"])
    with db.LOCK:
        h = lookup(db.hearings, hearing_id)
        if user_id != h["hearing_officer_role_user_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the assigned officer may hold")
        if h["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Hearing is not SCHEDULED")
        ap = db.appeals[h["appeal_id"]]
        if ap["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Parent appeal is not UNDER_REVIEW")
        h["status"] = "HELD"
        db.touch(h)
    return object_response(serialize(h), 200)


@bp.post("/hearings/<hearing_id>/cancel")
def cancel_hearing(hearing_id):
    require_roles(["HearingOfficer"])
    with db.LOCK:
        h = lookup(db.hearings, hearing_id)
        if h["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Hearing is not SCHEDULED")
        h["status"] = "CANCELLED"
        db.touch(h)
    return object_response(serialize(h), 200)
