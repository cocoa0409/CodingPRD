"""Escalation endpoints (PRD §3.9): manual raise + resolve."""
from flask import Blueprint

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response

bp = Blueprint("escalations", __name__)


@bp.route("/escalations", methods=["POST"])
def raise_escalation():
    p = authenticate()
    authorize(p, {"Dispatcher"})
    data = validate.body()
    request_id = validate.require_str(data, "request_id")
    if request_id not in db.service_requests:
        raise errors.not_found("Service request not found.")
    rec = {
        "request_id": request_id,
        "tier": "MANUAL",
        "reason": "manual dispatcher escalation",
        "status": "OPEN",
        "resolved_by_role": None,
    }
    db.stamp_audit(rec)
    db.escalations[rec["id"]] = rec
    return response.object_response(serialize.view("escalation", rec), 201)


@bp.route("/escalations/<eid>/resolve", methods=["POST"])
def resolve_escalation(eid):
    p = authenticate()
    authorize(p, {"Dispatcher", "Agent", "SystemAdmin"})
    esc = db.escalations.get(eid)
    if esc is None:
        raise errors.not_found("Escalation not found.")
    # priority 6: state.
    if esc["status"] != "OPEN":
        raise errors.invalid_state("Escalation is not OPEN.")

    # priority 16: TIER2 requires supervisor agent OR Dispatcher/SystemAdmin.
    if esc["tier"] == "TIER2":
        allowed = False
        if p.role in ("Dispatcher", "SystemAdmin"):
            allowed = True
        elif p.role == "Agent":
            agent = db.agents.get(p.user_id)
            if agent is not None and agent.get("is_supervisor"):
                allowed = True
        if not allowed:
            raise errors.tier2_requires_supervisor()

    esc["status"] = "RESOLVED"
    esc["resolved_by_role"] = p.role
    return response.object_response(serialize.view("escalation", esc))
