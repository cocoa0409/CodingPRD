"""Fault-incident takeover/resolve and read endpoints."""
from __future__ import annotations

from flask import Blueprint, request, g

from db import db
from errors import raise_error
from middleware import require_roles
from response import success
from services.audit import write_audit
from services.lookup import get_fleet_or_404, get_incident_or_404
from services.serialize import fault_incident_to_dict
from services.transitions import bump

fault_bp = Blueprint("fault", __name__)


@fault_bp.route("/fleets/<fleet_id>/fault_incidents/<incident_id>", methods=["GET"])
def read_incident(fleet_id, incident_id):
    require_roles(["Operator", "FleetAdmin", "WMS"])
    get_fleet_or_404(fleet_id)
    incident = get_incident_or_404(fleet_id, incident_id)
    return success(fault_incident_to_dict(incident))


@fault_bp.route("/fleets/<fleet_id>/fault_incidents/<incident_id>:takeover", methods=["POST"])
def takeover(fleet_id, incident_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    incident = get_incident_or_404(fleet_id, incident_id)
    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] != incident["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    if incident["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "Incident must be OPEN to take over")
    robot = db.robots.get(incident["robot_id"])
    incident["status"] = "TAKEOVER"
    incident["takeover_started_at"] = fleet["clock_now"]
    bump(incident, fleet)
    if robot:
        prev = robot["operational_state"]
        robot["operational_state"] = "UNDER_MANUAL_CONTROL"
        bump(robot, fleet)
        write_audit(fleet, "FAULT", "Robot", robot["id"], prev, "UNDER_MANUAL_CONTROL", g.user_role)
    write_audit(fleet, "FAULT", "FaultIncident", incident_id, "OPEN", "TAKEOVER", g.user_role)
    return success(fault_incident_to_dict(incident))


@fault_bp.route("/fleets/<fleet_id>/fault_incidents/<incident_id>:resolve", methods=["POST"])
def resolve(fleet_id, incident_id):
    require_roles(["Operator"])
    fleet = get_fleet_or_404(fleet_id)
    incident = get_incident_or_404(fleet_id, incident_id)
    body = request.get_json(silent=True) or {}
    if "version" in body and body["version"] != incident["version"]:
        raise_error("ERR_INVALID_STATE", "Version mismatch")
    if incident["status"] != "TAKEOVER":
        raise_error("ERR_INVALID_STATE", "Incident must be in TAKEOVER")
    incident["status"] = "RESOLVED"
    incident["resolved_at"] = fleet["clock_now"]
    bump(incident, fleet)
    # Lift isolation
    for nid in incident.get("isolation_node_ids") or []:
        node = db.map_nodes.get(nid)
        if node and node["status"] == "BLOCKED":
            node["status"] = "OPEN"
            node["blocked_reason"] = None
            bump(node, fleet)
    robot = db.robots.get(incident["robot_id"])
    if robot:
        prev = robot["operational_state"]
        robot["operational_state"] = "IDLE"
        robot["fault_state"] = "OK"
        bump(robot, fleet)
        write_audit(fleet, "FAULT", "Robot", robot["id"], prev, "IDLE", g.user_role)
    write_audit(fleet, "FAULT", "FaultIncident", incident_id, "TAKEOVER", "RESOLVED", g.user_role)
    return success(fault_incident_to_dict(incident))
