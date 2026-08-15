"""Incident investigation endpoints (PRD §3.4)."""
from flask import Blueprint

from db import STORE, now_iso
from errors import (raise_error, ERR_DUPLICATE, ERR_INVALID_STATE,
                    ERR_NOT_INVESTIGATION_LEAD)
from middleware import get_auth, require_roles, ALL_ROLES
from response import success_object
from services.core import (get_body, req_str, req_enum, base_fields, bump,
                           serialize, lookup)

bp = Blueprint("investigations", __name__)

ROOT_CAUSES = ("HUMAN_FACTOR", "EQUIPMENT", "PROCESS", "ENVIRONMENT",
               "TRAINING", "INDETERMINATE")


@bp.post("/safety/investigations")
def create_investigation():
    auth = get_auth()
    require_roles(auth, ("SafetyOfficer",))
    data = get_body()
    case_id = req_str(data, "case_id")
    lead_supervisor_id = req_str(data, "lead_supervisor_id", non_empty=True)
    lookup(STORE.cases, case_id)
    if any(i["case_id"] == case_id for i in STORE.investigations.values()):
        raise_error(ERR_DUPLICATE,
                    "An investigation already exists for this case")
    inv = base_fields()
    inv.update({
        "case_id": case_id,
        "lead_supervisor_id": lead_supervisor_id,
        "opened_at": now_iso(),
        "root_cause": None,
        "contributing_factors": None,
        "status": "OPEN",
        "closed_at": None,
    })
    STORE.investigations[inv["id"]] = inv
    return success_object(serialize(inv), status=201)


@bp.get("/safety/investigations/<investigationId>")
def get_investigation(investigationId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    inv = lookup(STORE.investigations, investigationId)
    return success_object(serialize(inv))


@bp.post("/safety/investigations/<investigationId>/submit-root-cause")
def submit_root_cause(investigationId):
    auth = get_auth()
    require_roles(auth, ("InvestigatingSupervisor",))
    inv = lookup(STORE.investigations, investigationId)
    data = get_body()
    root_cause = req_enum(data, "root_cause", ROOT_CAUSES)
    contributing = req_str(data, "contributing_factors", non_empty=True)
    if inv["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if auth.user_id != inv["lead_supervisor_id"]:
        raise_error(ERR_NOT_INVESTIGATION_LEAD,
                    "Only the recorded lead supervisor may submit the root "
                    "cause")
    inv["root_cause"] = root_cause
    inv["contributing_factors"] = contributing
    inv["status"] = "ROOT_CAUSE_SUBMITTED"
    bump(inv)
    return success_object(serialize(inv))


@bp.post("/safety/investigations/<investigationId>/reopen")
def reopen_investigation(investigationId):
    auth = get_auth()
    require_roles(auth, ("InvestigatingSupervisor",))
    inv = lookup(STORE.investigations, investigationId)
    if inv["status"] != "ROOT_CAUSE_SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if auth.user_id != inv["lead_supervisor_id"]:
        raise_error(ERR_NOT_INVESTIGATION_LEAD,
                    "Only the recorded lead supervisor may reopen the "
                    "investigation")
    # root_cause and contributing_factors are retained on reopen.
    inv["status"] = "OPEN"
    bump(inv)
    return success_object(serialize(inv))


@bp.post("/safety/investigations/<investigationId>/close")
def close_investigation(investigationId):
    auth = get_auth()
    require_roles(auth, ("SafetyOfficer",))
    inv = lookup(STORE.investigations, investigationId)
    if inv["status"] != "ROOT_CAUSE_SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    case = STORE.cases.get(inv["case_id"])
    if (inv["root_cause"] == "INDETERMINATE"
            and (case is None or case["classification"] != "DEATH")):
        raise_error(ERR_INVALID_STATE,
                    "Only a fatality investigation may close on an "
                    "INDETERMINATE root cause")
    inv["status"] = "CLOSED"
    inv["closed_at"] = now_iso()
    bump(inv)
    return success_object(serialize(inv))
