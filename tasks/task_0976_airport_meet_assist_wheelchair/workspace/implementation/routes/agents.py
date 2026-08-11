"""Agents and wheelchairs."""
from flask import Blueprint, request as _req

import db
from errors import bad_request, invalid_state, temporal_conflict, chair_in_use
from middleware import require_roles
from response import success_object
from routes.util import (get_or_404, json_body, list_response,
                         parse_datetime_field, require_enum, require_fields,
                         serialize_agent, serialize_assignment, serialize_wheelchair)
from services import cascades

bp = Blueprint("agents", __name__)

AGENT_LIST_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "BillingClerk")
AGENT_GET_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "Agent",
                   "Confirmer", "BillingClerk")
CHAIR_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "BillingClerk")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

@bp.post("/maa/airports/<aid>/agents")
def create_agent(aid):
    require_roles("PlatformAdmin")
    airport = get_or_404(db.airports, aid, "Airport")
    body = json_body()
    require_fields(body, ["display_name", "tsa_cleared_until", "ummr_certified",
                          "senior_trained", "wc_certified",
                          "shift_start_utc", "shift_end_utc"])
    if not isinstance(body["display_name"], str) or not body["display_name"].strip():
        raise bad_request("display_name must be a non-empty string")
    tsa = parse_datetime_field(body["tsa_cleared_until"], "tsa_cleared_until")
    shift_start = parse_datetime_field(body["shift_start_utc"], "shift_start_utc")
    shift_end = parse_datetime_field(body["shift_end_utc"], "shift_end_utc")
    if not (shift_start < shift_end):
        raise temporal_conflict("shift_start_utc must be strictly before shift_end_utc")
    if (shift_end - shift_start).total_seconds() > 12 * 3600:
        raise temporal_conflict("shift length may not exceed 12 hours")
    for flag in ("ummr_certified", "senior_trained", "wc_certified"):
        if not isinstance(body[flag], bool):
            raise bad_request(f"{flag} must be a boolean")
    agent = db.common_fields()
    agent.update({
        "airport_id": airport["id"],
        "display_name": body["display_name"],
        "tsa_cleared_until": tsa,
        "ummr_certified": body["ummr_certified"],
        "senior_trained": body["senior_trained"],
        "wc_certified": body["wc_certified"],
        "shift_start_utc": shift_start,
        "shift_end_utc": shift_end,
        "status": "ACTIVE",
        "active_assignment_count": 0,
        "cumulative_delay_minutes": 0,
    })
    db.agents[agent["id"]] = agent
    return success_object(serialize_agent(agent), status=201)


@bp.get("/maa/airports/<aid>/agents")
def list_agents(aid):
    require_roles(*AGENT_LIST_ROLES)
    airport = get_or_404(db.airports, aid, "Airport")
    items = [a for a in db.agents.values() if a["airport_id"] == airport["id"]]
    status = _req.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return list_response(items, serialize_agent)


@bp.get("/maa/agents/<aid>")
def get_agent(aid):
    require_roles(*AGENT_GET_ROLES)
    agent = get_or_404(db.agents, aid, "Agent")
    return success_object(serialize_agent(agent))


@bp.get("/maa/agents/<aid>/assignments")
def list_agent_assignments(aid):
    require_roles(*AGENT_LIST_ROLES)
    agent = get_or_404(db.agents, aid, "Agent")
    items = [a for a in db.assignments.values() if a["agent_id"] == agent["id"]]
    return list_response(items, serialize_assignment)


@bp.post("/maa/agents/<aid>/events")
def agent_event(aid):
    require_roles("OpsManager")
    agent = get_or_404(db.agents, aid, "Agent")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(body["event_type"], {"SUSPEND", "REINSTATE"}, "event_type")
    if event_type == "SUSPEND":
        if agent["status"] != "ACTIVE":
            raise invalid_state("Agent must be ACTIVE to suspend")
        agent["status"] = "SUSPENDED"
        db.touch(agent)
        for asg in list(db.assignments.values()):
            if asg["agent_id"] == agent["id"]:
                cascades.cancel_assignment_for_agent_suspend(asg)
    else:  # REINSTATE
        if agent["status"] != "SUSPENDED":
            raise invalid_state("Agent must be SUSPENDED to reinstate")
        agent["status"] = "ACTIVE"
        db.touch(agent)
    return success_object(serialize_agent(agent))


# ---------------------------------------------------------------------------
# Wheelchairs
# ---------------------------------------------------------------------------

@bp.post("/maa/airports/<aid>/wheelchairs")
def create_wheelchair(aid):
    require_roles("PlatformAdmin")
    airport = get_or_404(db.airports, aid, "Airport")
    body = json_body()
    require_fields(body, ["asset_tag", "chair_class", "is_wchc_rated"])
    asset_tag = body["asset_tag"]
    if not isinstance(asset_tag, str) or not asset_tag.strip():
        raise bad_request("asset_tag must be a non-empty string")
    for w in db.wheelchairs.values():
        if w["airport_id"] == airport["id"] and w["asset_tag"] == asset_tag:
            raise bad_request("asset_tag must be unique within the airport")
    chair_class = require_enum(body["chair_class"], {"MANUAL", "POWER", "BARIATRIC"}, "chair_class")
    if not isinstance(body["is_wchc_rated"], bool):
        raise bad_request("is_wchc_rated must be a boolean")
    chair = db.common_fields()
    chair.update({
        "airport_id": airport["id"],
        "asset_tag": asset_tag,
        "chair_class": chair_class,
        "is_wchc_rated": body["is_wchc_rated"],
        "status": "AVAILABLE",
        "last_maintenance_utc": None,
        "usage_count": 0,
    })
    db.wheelchairs[chair["id"]] = chair
    return success_object(serialize_wheelchair(chair), status=201)


@bp.get("/maa/airports/<aid>/wheelchairs")
def list_wheelchairs(aid):
    require_roles(*CHAIR_ROLES)
    airport = get_or_404(db.airports, aid, "Airport")
    items = [w for w in db.wheelchairs.values() if w["airport_id"] == airport["id"]]
    status = _req.args.get("status")
    chair_class = _req.args.get("chair_class")
    if status:
        items = [w for w in items if w["status"] == status]
    if chair_class:
        items = [w for w in items if w["chair_class"] == chair_class]
    return list_response(items, serialize_wheelchair)


@bp.get("/maa/wheelchairs/<wid>")
def get_wheelchair(wid):
    require_roles(*CHAIR_ROLES)
    chair = get_or_404(db.wheelchairs, wid, "WheelchairAsset")
    return success_object(serialize_wheelchair(chair))


@bp.get("/maa/wheelchairs/<wid>/assignments")
def list_wheelchair_assignments(wid):
    require_roles(*CHAIR_ROLES)
    chair = get_or_404(db.wheelchairs, wid, "WheelchairAsset")
    items = [a for a in db.assignments.values() if a.get("wheelchair_asset_id") == chair["id"]]
    return list_response(items, serialize_assignment)


@bp.post("/maa/wheelchairs/<wid>/events")
def wheelchair_event(wid):
    require_roles("OpsManager")
    chair = get_or_404(db.wheelchairs, wid, "WheelchairAsset")
    body = json_body()
    require_fields(body, ["event_type"])
    event_type = require_enum(
        body["event_type"],
        {"SCHEDULE_MAINTENANCE", "COMPLETE_MAINTENANCE", "RETIRE"},
        "event_type")
    if event_type == "SCHEDULE_MAINTENANCE":
        if chair["status"] != "AVAILABLE":
            raise invalid_state("Chair must be AVAILABLE to schedule maintenance")
        chair["status"] = "MAINTENANCE"
        db.touch(chair)
    elif event_type == "COMPLETE_MAINTENANCE":
        if chair["status"] != "MAINTENANCE":
            raise invalid_state("Chair must be MAINTENANCE to complete maintenance")
        chair["status"] = "AVAILABLE"
        chair["usage_count"] = 0
        chair["last_maintenance_utc"] = db.now()
        db.touch(chair)
    else:  # RETIRE
        # PRD §3.1: "attempting retirement while such a reference exists is
        # rejected with ERR_CHAIR_IN_USE (HTTP 409)" — the in-flight-reference
        # rule is checked before the from-state gate.
        for asg in db.assignments.values():
            if (asg.get("wheelchair_asset_id") == chair["id"]
                    and asg["status"] in {"DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE"}):
                raise chair_in_use("Chair referenced by in-flight assignment")
        if chair["status"] != "MAINTENANCE":
            raise invalid_state("Chair must be MAINTENANCE to retire")
        chair["status"] = "RETIRED"
        db.touch(chair)
    return success_object(serialize_wheelchair(chair))
