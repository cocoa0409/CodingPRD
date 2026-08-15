"""Incident reports, risk scoring, and the automatic HIGH-tier shutdown (PRD 3.8)."""

from flask import Blueprint, request

import db
from clock import CLOCK, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("incident_reports", __name__)

_KINDS = ("NEAR_MISS", "FIRST_AID", "INJURY", "PROPERTY_DAMAGE")


@bp.route("/incident-reports", methods=["POST"])
def create_incident():
    auth(ALL_ROLES)
    body = core.body_json()
    machine_id = core.req_str(body, "machine_id")
    kind = core.req_enum(body, "kind", _KINDS)
    occurred_at = core.req_dt(body, "occurred_at")
    severity = core.req_int(body, "severity", min_v=1, max_v=5)
    session_id = core.opt_str(body, "session_id")
    description = core.opt_str(body, "description")
    m = core.get_or_404("machines", machine_id, "Machine")
    if session_id is not None:
        s = core.get_or_404("lockout_sessions", session_id, "LockoutSession")
        if s["machine_id"] != m["id"]:
            raise ApiError("ERR_NOT_FOUND", 404,
                           "Session belongs to a different machine")
    i = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "session_id": session_id,
        "kind": kind,
        "occurred_at": fmt(occurred_at),
        "severity": severity,
        "description": description,
        "linked_at": None,
        "status": "REPORTED",
    })
    db.DB["incident_reports"][i["id"]] = i
    return ok(core.incident_view(i), 201)


@bp.route("/incident-reports", methods=["GET"])
def list_incidents():
    auth(ALL_ROLES)
    machine_id = request.args.get("machine_id")
    session_id = request.args.get("session_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    items = list(db.DB["incident_reports"].values())
    if machine_id is not None:
        items = [i for i in items if i["machine_id"] == machine_id]
    if session_id is not None:
        items = [i for i in items if i["session_id"] == session_id]
    if kind is not None:
        items = [i for i in items if i["kind"] == kind]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.incident_view(i) for i in page], total, limit, offset)


@bp.route("/incident-reports/<iid>", methods=["GET"])
def get_incident(iid):
    auth(ALL_ROLES)
    i = core.get_or_404("incident_reports", iid, "IncidentReport")
    return ok(core.incident_view(i))


@bp.route("/incident-reports/<iid>/link", methods=["POST"])
def link_incident(iid):
    auth(["EHSManager"])
    i = core.get_or_404("incident_reports", iid, "IncidentReport")
    if i["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REPORTED incident can be linked")
    m = db.DB["machines"][i["machine_id"]]
    tier_before = core.risk_tier(m)
    i["status"] = "LINKED"
    i["linked_at"] = fmt(CLOCK.now())
    core.touch(i)
    tier_after = core.risk_tier(m)
    # Conditional cascade: fires only on crossing INTO HIGH, never when the
    # machine is already there (PRD 3.8). Same cascades as the manual path.
    if tier_before != "HIGH" and tier_after == "HIGH" and m["status"] == "IN_SERVICE":
        core.machine_out_of_service(m)
    return ok(core.incident_view(i))


@bp.route("/incident-reports/<iid>/dismiss", methods=["POST"])
def dismiss_incident(iid):
    auth(["EHSManager"])
    i = core.get_or_404("incident_reports", iid, "IncidentReport")
    if i["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REPORTED incident can be dismissed")
    i["status"] = "DISMISSED"
    core.touch(i)
    return ok(core.incident_view(i))
