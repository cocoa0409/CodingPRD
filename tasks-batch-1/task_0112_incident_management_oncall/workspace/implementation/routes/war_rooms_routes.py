"""WarRoom open/get/close + WarRoomMessage append-only log."""
from flask import Blueprint

import response
from db import db, new_id, next_seq
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services.common import require_str, optional_str, stamp_create, touch
from services.lookups import get_incident, get_war_room
from services.serializers import war_room_out, war_room_message_out

bp = Blueprint("war_rooms", __name__)

ALL_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}


@bp.route("/war-rooms", methods=["POST"])
def create_war_room():
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    body = get_json_body()
    incident_id = require_str(body, "incident_id")
    with db.lock:
        get_incident(incident_id)  # FK existence (priority 3)
        bridge_url = optional_str(body, "bridge_url")
        # uniqueness (priority 13): at most one war room per incident
        for wr in db.war_rooms.values():
            if wr["incident_id"] == incident_id:
                raise ApiError("ERR_WAR_ROOM_EXISTS", "A war room already exists for this incident.")
        rec = stamp_create({
            "incident_id": incident_id,
            "status": "OPEN",
            "bridge_url": bridge_url,
        })
        db.war_rooms[rec["id"]] = rec
    return response.success(war_room_out(rec), 201)


@bp.route("/war-rooms/<wid>", methods=["GET"])
def get_one_war_room(wid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        wr = get_war_room(wid)
        return response.success(war_room_out(wr), 200)


@bp.route("/incidents/<iid>/war-rooms", methods=["GET"])
def list_incident_war_rooms(iid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        get_incident(iid)
        rows = [wr for wr in db.war_rooms.values() if wr["incident_id"] == iid]
        return response.list_response(rows, limit, offset, war_room_out)


@bp.route("/war-rooms/<wid>/close", methods=["POST"])
def close_war_room(wid):
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    with db.lock:
        wr = get_war_room(wid)
        # state (priority 6): must be OPEN
        if wr["status"] != "OPEN":
            raise ApiError("ERR_WAR_ROOM_NOT_OPEN", "War room is not OPEN.")
        # cross-entity dependency (priority 7): parent incident RESOLVED
        inc = db.incidents.get(wr["incident_id"])
        if inc is None or inc["lifecycle_status"] != "RESOLVED":
            raise ApiError("ERR_INCIDENT_NOT_RESOLVED", "Parent incident is not RESOLVED.")
        wr["status"] = "CLOSED"
        touch(wr)
        return response.success(war_room_out(wr), 200)


@bp.route("/war-rooms/<wid>/messages", methods=["POST"])
def post_message(wid):
    user_id, role = require_user_context()
    require_role(role, ALL_ROLES)
    body = get_json_body()
    with db.lock:
        get_war_room(wid)
        message_body = require_str(body, "body")
        m_id = new_id()
        rec = {
            "id": m_id,
            "created_at": db.clock.now(),
            "_seq": next_seq(),
            "war_room_id": wid,
            "author_role": role,
            "author_id": user_id,
            "body": message_body,
        }
        db.war_room_messages[m_id] = rec
    return response.success(war_room_message_out(rec), 201)


@bp.route("/war-rooms/<wid>/messages", methods=["GET"])
def list_messages(wid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        get_war_room(wid)
        rows = [m for m in db.war_room_messages.values() if m["war_room_id"] == wid]
        return response.list_response(rows, limit, offset, war_room_message_out)
