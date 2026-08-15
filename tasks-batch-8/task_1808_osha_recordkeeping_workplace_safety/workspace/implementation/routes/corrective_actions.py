"""Corrective action endpoints (PRD §3.5)."""
from flask import Blueprint

from db import STORE, now_dt, now_iso
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_LINKAGE_XOR, ERR_NOT_ASSIGNEE,
                    ERR_DUTY_SEGREGATION)
from middleware import get_auth, require_roles, ALL_ROLES
from response import success_object
from services.core import (get_body, req_str, opt_str, req_enum, req_date,
                           base_fields, bump, serialize, lookup,
                           recompute_posture, citation_establishment_id)

bp = Blueprint("corrective_actions", __name__)

PRIORITIES = ("LOW", "MEDIUM", "HIGH", "IMMINENT_DANGER")
SO = ("SafetyOfficer",)


@bp.post("/safety/corrective-actions")
def create_corrective_action():
    auth = get_auth()
    require_roles(auth, SO)
    data = get_body()
    establishment_id = req_str(data, "establishment_id")
    case_id = opt_str(data, "case_id")
    citation_id = opt_str(data, "citation_id")
    description = req_str(data, "description", non_empty=True)
    assigned_to = req_str(data, "assigned_to", non_empty=True)
    due_date = req_date(data, "due_date")
    priority = req_enum(data, "priority", PRIORITIES)

    lookup(STORE.establishments, establishment_id)
    case = None
    citation = None
    if case_id is not None:
        case = lookup(STORE.cases, case_id)
        if case["establishment_id"] != establishment_id:
            raise_error(ERR_NOT_FOUND,
                        "case_id does not belong to this establishment")
    if citation_id is not None:
        citation = lookup(STORE.citations, citation_id)
        if citation_establishment_id(citation) != establishment_id:
            raise_error(ERR_NOT_FOUND,
                        "citation_id does not belong to this establishment")
    if (case_id is None) == (citation_id is None):
        raise_error(ERR_LINKAGE_XOR,
                    "Exactly one of case_id / citation_id must be non-null")
    if due_date <= now_dt().date():
        raise_error(ERR_INVALID_REQUEST,
                    "due_date must fall strictly after the creation date")

    action = base_fields()
    action.update({
        "establishment_id": establishment_id,
        "case_id": case_id,
        "citation_id": citation_id,
        "description": description,
        "assigned_to": assigned_to,
        "due_date": due_date.isoformat(),
        "priority": priority,
        "status": "OPEN",
        "completed_at": None,
        "verified_by": None,
        "completed_by": None,
        "_abatement_satisfied": False,
    })
    STORE.corrective_actions[action["id"]] = action
    return success_object(serialize(action), status=201)


@bp.get("/safety/corrective-actions/<actionId>")
def get_corrective_action(actionId):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    action = lookup(STORE.corrective_actions, actionId)
    return success_object(serialize(action))


@bp.post("/safety/corrective-actions/<actionId>/complete")
def complete_corrective_action(actionId):
    auth = get_auth()
    require_roles(auth, SO)
    action = lookup(STORE.corrective_actions, actionId)
    data = get_body()
    completed_by = req_str(data, "completed_by", non_empty=True)
    if action["status"] not in ("OPEN", "REOPENED"):
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if completed_by != action["assigned_to"]:
        raise_error(ERR_NOT_ASSIGNEE,
                    "completed_by must match the action's assigned_to")
    action["status"] = "COMPLETED"
    action["completed_at"] = now_iso()
    action["completed_by"] = completed_by
    bump(action)
    return success_object(serialize(action))


@bp.post("/safety/corrective-actions/<actionId>/verify")
def verify_corrective_action(actionId):
    auth = get_auth()
    require_roles(auth, SO)
    action = lookup(STORE.corrective_actions, actionId)
    if action["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if auth.user_id == action["completed_by"]:
        raise_error(ERR_DUTY_SEGREGATION,
                    "Verifier must differ from the completing operator")
    if action.get("case_id"):
        inv = next((i for i in STORE.investigations.values()
                    if i["case_id"] == action["case_id"]), None)
        if inv and auth.user_id == inv["lead_supervisor_id"]:
            raise_error(ERR_DUTY_SEGREGATION,
                        "Verifier must differ from the linked case's "
                        "investigation lead")
    action["status"] = "VERIFIED"
    action["verified_by"] = auth.user_id
    bump(action)
    est = STORE.establishments.get(action["establishment_id"])
    if est:
        recompute_posture(est)
    return success_object(serialize(action))


@bp.post("/safety/corrective-actions/<actionId>/reject-verification")
def reject_verification(actionId):
    auth = get_auth()
    require_roles(auth, SO)
    action = lookup(STORE.corrective_actions, actionId)
    if action["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if auth.user_id == action["completed_by"]:
        raise_error(ERR_DUTY_SEGREGATION,
                    "Reviewer must differ from the completing operator")
    action["status"] = "REOPENED"
    action["completed_at"] = None
    action["completed_by"] = None
    bump(action)
    return success_object(serialize(action))


@bp.post("/safety/corrective-actions/<actionId>/cancel")
def cancel_corrective_action(actionId):
    auth = get_auth()
    require_roles(auth, SO)
    action = lookup(STORE.corrective_actions, actionId)
    if action["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    action["status"] = "CANCELLED"
    bump(action)
    est = STORE.establishments.get(action["establishment_id"])
    if est:
        recompute_posture(est)
    return success_object(serialize(action))
