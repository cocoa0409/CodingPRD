"""Safety incident endpoints: report (recomputes posture, may cascade into
SUSPENDED), get, resolve (recomputes posture, may resume)."""

from flask import Blueprint

import domain
from db import STORE, new_entity, public
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import auth_context, require_role, ALL_ROLES
from response import ok
from validate import body, req_str, req_enum

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")


@bp.route("/transload/incidents", methods=["POST"])
def create_incident():
    _, role = auth_context()
    require_role(role, ["SafetyOfficer"])
    data = body()
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description")
    inc = new_entity(STORE.incidents, {
        "severity": severity,
        "description": description,
        "status": "OPEN",
    }, common=False)
    domain.recompute_posture()
    return ok(public(inc), status=201)


@bp.route("/transload/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    inc = STORE.incidents.get(iid)
    if inc is None:
        raise_err(ERR_NOT_FOUND, "incident id does not exist")
    return ok(public(inc))


@bp.route("/transload/incidents/<iid>/resolve", methods=["POST"])
def resolve_incident(iid):
    _, role = auth_context()
    require_role(role, ["SafetyOfficer"])
    inc = STORE.incidents.get(iid)
    if inc is None:
        raise_err(ERR_NOT_FOUND, "incident id does not exist")
    if inc["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "incident is not OPEN")
    inc["status"] = "RESOLVED"
    domain.recompute_posture()
    return ok(public(inc))
