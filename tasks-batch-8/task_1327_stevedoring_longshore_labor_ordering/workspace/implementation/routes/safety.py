"""SafetyIncident endpoints (PRD §3.6)."""
from flask import Blueprint, request

import errors
import services
from db import get, new_resource, pub, save, touch
from middleware import list_response, req_enum, req_field, req_str, require_roles
from response import get_body, ok

bp = Blueprint("safety", __name__)

READ_ROLES = ("StevedoreAdmin", "StevedoreSuperintendent", "GangForeman")
SCOPES = ("GANG", "VESSEL", "TERMINAL")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


@bp.post("/api/safety-incidents")
def create_incident():
    require_roles("StevedoreSuperintendent", "GangForeman")
    body = get_body()
    # existence (3)
    vessel_call_id = req_field(body, "vessel_call_id")
    vessel = get("vessel_calls", vessel_call_id)
    if vessel is None:
        raise errors.not_found("Vessel call not found")
    gang_order_id = body.get("gang_order_id")
    if gang_order_id is not None and get("gang_orders", gang_order_id) is None:
        raise errors.not_found("Gang order not found")
    # schema (4)
    scope = req_enum(body, "scope", SCOPES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    if scope == "GANG" and gang_order_id is None:
        raise errors.validation("gang_order_id is required when scope is GANG")
    rec = new_resource("safety_incidents")
    rec.update({
        "vessel_call_id": vessel_call_id,
        "gang_order_id": gang_order_id,
        "scope": scope,
        "severity": severity,
        "description": description,
        "status": "REPORTED",
    })
    save("safety_incidents", rec)
    # posture derivation re-runs on creation; entering FULL_STOPPAGE cascades
    services.recompute_posture(vessel)
    return ok(pub(rec), 201)


@bp.get("/api/safety-incidents")
def list_incidents():
    require_roles(*READ_ROLES)
    return list_response("safety_incidents", {
        "vessel_call_id": request.args.get("vessel_call_id"),
        "gang_order_id": request.args.get("gang_order_id"),
        "status": request.args.get("status"),
    })


def _get_incident(iid):
    i = get("safety_incidents", iid)
    if i is None:
        raise errors.not_found("Safety incident not found")
    return i


@bp.get("/api/safety-incidents/<iid>")
def get_incident(iid):
    require_roles(*READ_ROLES)
    return ok(pub(_get_incident(iid)))


@bp.post("/api/safety-incidents/<iid>/clear")
def clear_incident(iid):
    require_roles("StevedoreSuperintendent")
    i = _get_incident(iid)
    if i["status"] != "REPORTED":
        raise errors.invalid_state("Only a REPORTED incident can be cleared")
    i["status"] = "CLEARED"
    touch(i)
    vessel = get("vessel_calls", i["vessel_call_id"])
    if vessel is not None:
        # posture recomputes; SUSPENDED gang orders remain suspended until resumed
        services.recompute_posture(vessel)
    return ok(pub(i))
