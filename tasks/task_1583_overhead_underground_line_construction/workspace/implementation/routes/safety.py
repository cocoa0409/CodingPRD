"""Safety event endpoints (PRD 3.8, 2.10): logging an INCIDENT of severity
OSHA_RECORDABLE or FATAL suspends the contract with the stop-work cascade;
review transitions remain available while the contract is SUSPENDED."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active
from services.core import new_record, touch, contract_of_work_package
from validate import (
    get_body, req_str, req_enum, require_path_resource, require_body_ref,
)

bp = Blueprint("safety", __name__)

SUSPENDING_SEVERITIES = {"OSHA_RECORDABLE", "FATAL"}


@bp.post("/work-packages/<work_package_id>/safety-events")
def create_safety_event(work_package_id):
    authorized(["SAFETY_OFFICER"])
    body = get_body()
    kind = req_enum(body, "kind", {"OBSERVATION", "INCIDENT"})
    severity = req_enum(body, "severity",
                        {"POSITIVE", "AT_RISK", "OSHA_RECORDABLE", "FATAL"})
    description = req_str(body, "description")
    crew_id = body.get("crew_id")
    if crew_id is not None and not isinstance(crew_id, str):
        raise_error(ERR_INVALID_REQUEST, "crew_id must be a string")
    wp = require_path_resource("work_packages", work_package_id)
    if crew_id is not None:
        require_body_ref("crews", crew_id, "crew_id")
    contract = contract_of_work_package(wp)
    require_contract_active(contract)  # creation is an operational write
    rec = new_record("safety_events", {
        "work_package_id": wp["id"],
        "crew_id": crew_id,
        "kind": kind,
        "severity": severity,
        "description": description,
        "status": "OPEN",
    })
    if kind == "INCIDENT" and severity in SUSPENDING_SEVERITIES:
        _suspend_contract(contract)
    return success_object(serialize("safety_events", rec), status=201)


def _suspend_contract(contract):
    """ACTIVE -> SUSPENDED with the full stop-work cascade: every assignment
    of every work package of the contract in PLANNED/ACTIVE -> CANCELLED;
    every outage request in REQUESTED/APPROVED/CHANGE_REQUESTED -> CANCELLED."""
    if contract["status"] != "ACTIVE":
        return
    contract["status"] = "SUSPENDED"
    touch(contract)
    wp_ids = {w["id"] for w in db["work_packages"].values()
              if w["contract_id"] == contract["id"]}
    for a in db["assignments"].values():
        if a["work_package_id"] in wp_ids and a["status"] in ("PLANNED", "ACTIVE"):
            a["status"] = "CANCELLED"
            touch(a)
    for o in db["outage_requests"].values():
        if (o["work_package_id"] in wp_ids
                and o["status"] in ("REQUESTED", "APPROVED", "CHANGE_REQUESTED")):
            o["status"] = "CANCELLED"
            touch(o)


@bp.post("/safety-events/<safety_event_id>/transition")
def transition_safety_event(safety_event_id):
    # Review flow is exempt from the contract-activity gate (PRD 2.10), so
    # incidents that caused a stop-work can be reviewed and closed.
    authorized(["SAFETY_OFFICER"])
    body = get_body()
    to = req_enum(body, "to", {"UNDER_REVIEW", "CLOSED"})
    event = require_path_resource("safety_events", safety_event_id)
    cur = event["status"]
    if not ((cur == "OPEN" and to == "UNDER_REVIEW")
            or (cur == "UNDER_REVIEW" and to == "CLOSED")):
        raise_error(ERR_INVALID_STATE,
                    f"cannot transition safety event from {cur} to {to}")
    event["status"] = to
    touch(event)
    return success_object(serialize("safety_events", event))


@bp.get("/safety-events")
def list_safety_events():
    filters = {
        "work_package_id": request.args.get("work_package_id"),
        "crew_id": request.args.get("crew_id"),
        "kind": request.args.get("kind"),
        "status": request.args.get("status"),
    }
    return list_response("safety_events", filters)


@bp.get("/safety-events/<safety_event_id>")
def get_safety_event(safety_event_id):
    return get_one("safety_events", safety_event_id)
