"""Outreach events and registrations (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CLIENT_NOT_ACTIVE,
    ERR_EVENT_FULL, ERR_EVENT_PAST, ERR_EVENT_NOT_COMPLETED, ERR_ALREADY_REGISTERED,
    ERR_REGISTRATION_NOT_ACTIONABLE,
)
from middleware import authenticate, authorize, check_client_scope
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public, recompute_event
from util import CLOCK, parse_datetime
from validate import (
    get_body, req_int, req_str, opt_str, req_enum, opt_bool, req_datetime,
    require_path_resource, require_body_ref,
)

bp = Blueprint("events", __name__)

STIGMA_THEMES = ["NORMALIZATION", "PEER_LED", "FACULTY_TRAINING", "RESOURCE_FAIR"]
EVENT_READ_ROLES = ["Anonymous", "Client", "IntakeCoordinator", "PantryStaff",
                    "BenefitsCounselor", "GrantReviewer", "ShelterCoordinator", "HubAdmin"]
REGISTRATION_ROLES = ["Client", "IntakeCoordinator", "HubAdmin"]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bp.post("/outreach-events")
def create_event():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    body = get_body()
    title = req_str(body, "title")
    event_date = req_datetime(body, "event_date")
    capacity = req_int(body, "capacity", minimum=1)
    stigma_theme = req_enum(body, "stigma_theme", STIGMA_THEMES)
    anonymous_allowed = opt_bool(body, "anonymous_attendance_allowed", True)
    rec = new_record("outreach_events", {
        "title": title,
        "event_date": event_date,
        "capacity": capacity,
        "stigma_theme": stigma_theme,
        "anonymous_attendance_allowed": anonymous_allowed,
        "registered_count": 0,
        "attended_count": 0,
        "status": "PLANNED",
    })
    return success_object(public(rec), status=201)


@bp.get("/outreach-events")
def list_events():
    caller = authenticate()
    authorize(caller, EVENT_READ_ROLES)
    filters = {"status": request.args.get("status")}
    return list_response("outreach_events", filters)


@bp.post("/outreach-events/<eid>/open")
def open_event(eid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    event = require_path_resource("outreach_events", eid, "outreach event")
    if event["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, "only a PLANNED event can be opened")
    event["status"] = "OPEN"
    touch(event)
    return success_object(public(event))


@bp.post("/outreach-events/<eid>/complete")
def complete_event(eid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    event = require_path_resource("outreach_events", eid, "outreach event")
    if event["status"] not in ("OPEN", "FULL"):
        raise_error(ERR_INVALID_STATE, "only an OPEN or FULL event can be completed")
    event["status"] = "COMPLETED"
    touch(event)
    return success_object(public(event))


@bp.post("/outreach-events/<eid>/cancel")
def cancel_event(eid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    event = require_path_resource("outreach_events", eid, "outreach event")
    if event["status"] not in ("PLANNED", "OPEN", "FULL"):
        raise_error(ERR_INVALID_STATE, "only a PLANNED, OPEN, or FULL event can be cancelled")
    event["status"] = "CANCELLED"
    touch(event)
    # Cascade: every REGISTERED registration -> CANCELLED; counts recomputed
    for reg in list(db["event_registrations"].values()):
        if reg["event_id"] == event["id"] and reg["status"] == "REGISTERED":
            reg["status"] = "CANCELLED"
            touch(reg)
    recompute_event(event)
    return success_object(public(event))


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

@bp.post("/outreach-events/<eid>/registrations")
def register(eid):
    caller = authenticate()
    authorize(caller, REGISTRATION_ROLES)
    event = require_path_resource("outreach_events", eid, "outreach event")
    body = get_body()
    client_id = req_str(body, "client_id")
    display_alias = opt_str(body, "display_alias")
    if caller.role == "Client" and caller.user_id != client_id:
        from errors import ERR_FORBIDDEN_OWNERSHIP
        raise_error(ERR_FORBIDDEN_OWNERSHIP, "clients may only register themselves")
    client = require_body_ref("clients", client_id, "client_id")
    # Admission: event OPEN, strictly before event_date, client ACTIVE
    if event["status"] == "FULL":
        raise_error(ERR_EVENT_FULL, "event is at capacity")
    if event["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "event is not open for registration")
    if CLOCK.now() >= parse_datetime(event["event_date"]):
        raise_error(ERR_EVENT_PAST, "registration is only possible before event_date")
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "registration requires an ACTIVE client")
    # Uniqueness per (event, client) among non-CANCELLED rows; a cancelled row reactivates
    existing = None
    for reg in db["event_registrations"].values():
        if reg["event_id"] == event["id"] and reg["client_id"] == client["id"]:
            if reg["status"] != "CANCELLED":
                raise_error(ERR_ALREADY_REGISTERED, "a live registration already exists for this pair")
            existing = reg
    if existing is not None:
        existing["status"] = "REGISTERED"
        existing["display_alias"] = display_alias if display_alias is not None else client["alias_name"]
        touch(existing)
        rec = existing
    else:
        rec = new_record("event_registrations", {
            "event_id": event["id"],
            "client_id": client["id"],
            "display_alias": display_alias if display_alias is not None else client["alias_name"],
            "status": "REGISTERED",
        })
    recompute_event(event)  # count += 1; may flip OPEN -> FULL at capacity
    return success_object(public(rec), status=201)


@bp.get("/event-registrations")
def list_registrations():
    caller = authenticate()
    authorize(caller, REGISTRATION_ROLES)
    filters = {
        "event_id": request.args.get("event_id"),
        "client_id": request.args.get("client_id"),
        "status": request.args.get("status"),
    }
    scope = None
    if caller.role == "Client":
        scope = lambda rec: rec["client_id"] == caller.user_id
    return list_response("event_registrations", filters, scope_fn=scope)


@bp.get("/event-registrations/<rid>")
def get_registration(rid):
    caller = authenticate()
    authorize(caller, REGISTRATION_ROLES)
    reg = require_path_resource("event_registrations", rid, "event registration")
    check_client_scope(caller, reg["client_id"])
    return success_object(public(reg))


@bp.post("/event-registrations/<rid>/cancel")
def cancel_registration(rid):
    caller = authenticate()
    authorize(caller, REGISTRATION_ROLES)
    reg = require_path_resource("event_registrations", rid, "event registration")
    check_client_scope(caller, reg["client_id"])
    if reg["status"] != "REGISTERED":
        raise_error(ERR_REGISTRATION_NOT_ACTIONABLE, "only a REGISTERED registration can be cancelled")
    reg["status"] = "CANCELLED"
    touch(reg)
    event = db["outreach_events"].get(reg["event_id"])
    if event is not None:
        recompute_event(event)  # count -= 1; may flip FULL -> OPEN
    return success_object(public(reg))


@bp.post("/event-registrations/<rid>/mark-attended")
def mark_attended(rid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    reg = require_path_resource("event_registrations", rid, "event registration")
    if reg["status"] != "REGISTERED":
        raise_error(ERR_REGISTRATION_NOT_ACTIONABLE, "only a REGISTERED registration can be marked attended")
    event = db["outreach_events"].get(reg["event_id"])
    if event is None or event["status"] != "COMPLETED":
        raise_error(ERR_EVENT_NOT_COMPLETED, "event must be COMPLETED before attendance is marked")
    reg["status"] = "ATTENDED"
    touch(reg)
    recompute_event(event)  # attended_count += 1
    return success_object(public(reg))
