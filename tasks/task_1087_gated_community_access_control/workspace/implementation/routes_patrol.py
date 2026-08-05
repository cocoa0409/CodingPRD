from flask import Blueprint, request

from core import (
    db, base_entity, touch, serialize, ok_object, ok_array, paginate,
    auth, forbid, lookup, get_body, require_str, opt_str, require_enum,
    require_dt, ApiError,
)
from logic import patrol_conflict

bp = Blueprint("patrol", __name__)

PATROL_STATES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
INCIDENT_TYPES = {"TRESPASS", "NOISE", "SPEEDING", "VANDALISM", "UNAUTHORIZED_ACCESS", "OTHER"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH"}
INCIDENT_STATES = {"REPORTED", "INVESTIGATING", "RESOLVED", "CLOSED"}


# ---------------------------------------------------------------------------
# Patrols (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.route("/access/patrols", methods=["POST"])
def create_patrol():
    auth({"SecurityOfficer", "CommunityAdmin"})
    body = get_body()
    community_id = require_str(body, "community_id")
    officer_id = require_str(body, "officer_id")
    start_at = require_dt(body, "start_at")
    end_at = require_dt(body, "end_at")
    route = opt_str(body, "route", None)
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")

    if patrol_conflict(community_id, officer_id, start_at, end_at):
        raise ApiError("ERR_PATROL_OVERLAP", 422, "Officer shift within buffer")

    obj = base_entity()
    obj.update({
        "community_id": community_id,
        "officer_id": officer_id,
        "route": route,
        "start_at": start_at,
        "end_at": end_at,
        "status": "SCHEDULED",
    })
    db.patrols[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/patrols/<patrol_id>", methods=["GET"])
def get_patrol(patrol_id):
    auth({"CommunityAdmin", "SecurityOfficer"})
    obj = lookup(db.patrols, patrol_id, "ERR_PATROL_NOT_FOUND")
    return ok_object(serialize(obj))


@bp.route("/access/patrols", methods=["GET"])
def list_patrols():
    auth({"CommunityAdmin", "SecurityOfficer"})
    args = request.args
    rows = list(db.patrols.values())
    if args.get("community_id"):
        rows = [r for r in rows if r["community_id"] == args["community_id"]]
    if args.get("officer_id"):
        rows = [r for r in rows if r["officer_id"] == args["officer_id"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/patrols/<patrol_id>/transition", methods=["POST"])
def transition_patrol(patrol_id):
    auth({"SecurityOfficer", "CommunityAdmin"})
    patrol = lookup(db.patrols, patrol_id, "ERR_PATROL_NOT_FOUND")
    body = get_body()
    to_status = require_enum(body, "to_status", PATROL_STATES)
    allowed = {
        "SCHEDULED": {"IN_PROGRESS", "CANCELLED"},
        "IN_PROGRESS": {"COMPLETED"},
    }
    if to_status not in allowed.get(patrol["status"], set()):
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not permitted")
    patrol["status"] = to_status
    touch(patrol)
    return ok_object(serialize(patrol))


# ---------------------------------------------------------------------------
# Incidents (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.route("/access/incidents", methods=["POST"])
def create_incident():
    auth({"SecurityOfficer", "CommunityAdmin"})
    body = get_body()
    community_id = require_str(body, "community_id")
    incident_type = require_enum(body, "incident_type", INCIDENT_TYPES)
    severity = require_enum(body, "severity", SEVERITIES)
    description = require_str(body, "description")
    patrol_id = opt_str(body, "patrol_id", None)
    location = opt_str(body, "location", None)
    related_resident_id = opt_str(body, "related_resident_id", None)
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")
    if patrol_id is not None:
        lookup(db.patrols, patrol_id, "ERR_PATROL_NOT_FOUND")

    obj = base_entity()
    obj.update({
        "community_id": community_id,
        "patrol_id": patrol_id,
        "incident_type": incident_type,
        "severity": severity,
        "location": location,
        "description": description,
        "related_resident_id": related_resident_id,
        "status": "REPORTED",
    })
    db.incidents[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    auth({"CommunityAdmin", "SecurityOfficer"})
    obj = lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    return ok_object(serialize(obj))


@bp.route("/access/incidents", methods=["GET"])
def list_incidents():
    auth({"CommunityAdmin", "SecurityOfficer"})
    args = request.args
    rows = list(db.incidents.values())
    if args.get("community_id"):
        rows = [r for r in rows if r["community_id"] == args["community_id"]]
    if args.get("patrol_id"):
        rows = [r for r in rows if r["patrol_id"] == args["patrol_id"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    if args.get("severity"):
        rows = [r for r in rows if r["severity"] == args["severity"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/incidents/<incident_id>/transition", methods=["POST"])
def transition_incident(incident_id):
    uid, role = auth({"SecurityOfficer", "CommunityAdmin"})
    incident = lookup(db.incidents, incident_id, "ERR_INCIDENT_NOT_FOUND")
    body = get_body()
    to_status = require_enum(body, "to_status", INCIDENT_STATES)
    if to_status == "CLOSED" and role != "CommunityAdmin":
        forbid("Only CommunityAdmin may close an incident")
    allowed = {
        "REPORTED": {"INVESTIGATING"},
        "INVESTIGATING": {"RESOLVED"},
        "RESOLVED": {"CLOSED"},
    }
    if to_status not in allowed.get(incident["status"], set()):
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not permitted")
    incident["status"] = to_status
    touch(incident)
    return ok_object(serialize(incident))
