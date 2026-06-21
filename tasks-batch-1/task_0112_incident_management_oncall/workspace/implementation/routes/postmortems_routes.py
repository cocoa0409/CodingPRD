"""Postmortem create/read + workflow (submit/return/publish)."""
from flask import Blueprint

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services.common import require_str, stamp_create, touch
from services.lookups import get_incident, get_postmortem
from services.serializers import postmortem_out, action_item_out, _open_action_item_count

bp = Blueprint("postmortems", __name__)

ALL_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}


@bp.route("/postmortems", methods=["POST"])
def create_postmortem():
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    body = get_json_body()
    incident_id = require_str(body, "incident_id")
    with db.lock:
        inc = get_incident(incident_id)  # FK existence (priority 3)
        summary = require_str(body, "summary")
        # cross-entity dependency (priority 7): incident must be RESOLVED
        if inc["lifecycle_status"] != "RESOLVED":
            raise ApiError("ERR_INCIDENT_NOT_RESOLVED", "Incident must be RESOLVED to author a postmortem.")
        # uniqueness (priority 13): at most one postmortem per incident
        for pm in db.postmortems.values():
            if pm["incident_id"] == incident_id:
                raise ApiError("ERR_POSTMORTEM_EXISTS", "A postmortem already exists for this incident.")
        rec = stamp_create({
            "incident_id": incident_id,
            "status": "DRAFT",
            "summary": summary,
            "open_action_item_count": 0,
        })
        db.postmortems[rec["id"]] = rec
    return response.success(postmortem_out(rec), 201)


@bp.route("/postmortems/<pid>", methods=["GET"])
def get_one_postmortem(pid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        pm = get_postmortem(pid)
        return response.success(postmortem_out(pm), 200)


@bp.route("/incidents/<iid>/postmortems", methods=["GET"])
def list_incident_postmortems(iid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        get_incident(iid)
        rows = [pm for pm in db.postmortems.values() if pm["incident_id"] == iid]
        return response.list_response(rows, limit, offset, postmortem_out)


@bp.route("/postmortems/<pid>/submit", methods=["POST"])
def submit_postmortem(pid):
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    with db.lock:
        pm = get_postmortem(pid)
        if pm["status"] != "DRAFT":
            raise ApiError("ERR_POSTMORTEM_NOT_DRAFT", "Postmortem is not DRAFT.")
        pm["status"] = "IN_REVIEW"
        touch(pm)
        return response.success(postmortem_out(pm), 200)


@bp.route("/postmortems/<pid>/return", methods=["POST"])
def return_postmortem(pid):
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    with db.lock:
        pm = get_postmortem(pid)
        if pm["status"] != "IN_REVIEW":
            raise ApiError("ERR_POSTMORTEM_NOT_IN_REVIEW", "Postmortem is not IN_REVIEW.")
        pm["status"] = "DRAFT"
        touch(pm)
        return response.success(postmortem_out(pm), 200)


@bp.route("/postmortems/<pid>/publish", methods=["POST"])
def publish_postmortem(pid):
    _, role = require_user_context()
    require_role(role, {"IncidentCommander"})
    with db.lock:
        pm = get_postmortem(pid)
        # state (priority 6): must be IN_REVIEW
        if pm["status"] != "IN_REVIEW":
            raise ApiError("ERR_POSTMORTEM_NOT_IN_REVIEW", "Postmortem is not IN_REVIEW.")
        # business safety (priority 12): no open action items
        if _open_action_item_count(pid) != 0:
            raise ApiError("ERR_OPEN_ACTION_ITEMS", "Postmortem has open action items.")
        pm["status"] = "PUBLISHED"
        touch(pm)
        return response.success(postmortem_out(pm), 200)
