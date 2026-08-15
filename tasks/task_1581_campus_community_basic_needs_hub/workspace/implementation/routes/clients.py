"""Client registration, roster reads, and standing management (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_CLIENT_NOT_ACTIVE, ERR_INVALID_REQUEST
from middleware import authenticate, authorize, check_client_scope
from response import success_object
from routes.helpers import list_response
from services.core import (
    new_record, touch, serialize_client, recompute_agency, recompute_event, void_visit,
)
from util import CLOCK, parse_datetime
from validate import get_body, opt_int, req_enum, req_str, require_path_resource

bp = Blueprint("clients", __name__)

CONTACT_CHANNELS = ["EMAIL", "SMS", "PHONE", "NONE"]
POPULATION_TYPES = ["ENROLLED_STUDENT", "COMMUNITY_RESIDENT", "FACULTY_STAFF"]
STAFF_READ_ROLES = ["IntakeCoordinator", "PantryStaff", "BenefitsCounselor",
                    "GrantReviewer", "ShelterCoordinator", "HubAdmin"]


@bp.post("/clients")
def create_client():
    caller = authenticate()
    authorize(caller, ["Anonymous", "IntakeCoordinator", "HubAdmin"])
    body = get_body()
    alias_name = req_str(body, "alias_name")
    contact_channel = req_enum(body, "contact_channel", CONTACT_CHANNELS)
    population_type = req_enum(body, "population_type", POPULATION_TYPES)
    enrolled_credits = opt_int(body, "enrolled_credits", 0, minimum=0)
    if population_type == "ENROLLED_STUDENT" and enrolled_credits < 6:
        raise_error(ERR_INVALID_REQUEST, "ENROLLED_STUDENT requires enrolled_credits >= 6")
    rec = new_record("clients", {
        "alias_name": alias_name,
        "contact_channel": contact_channel,
        "population_type": population_type,
        "enrolled_credits": enrolled_credits,
        "status": "INTAKE_PENDING",
    })
    return success_object(serialize_client(rec), status=201)


@bp.get("/clients")
def list_clients():
    caller = authenticate()
    authorize(caller, STAFF_READ_ROLES)
    filters = {
        "status": request.args.get("status"),
        "population_type": request.args.get("population_type"),
        "risk_tier": request.args.get("risk_tier"),
    }
    return list_response("clients", filters, serializer=serialize_client)


@bp.get("/clients/<cid>")
def get_client(cid):
    caller = authenticate()
    authorize(caller, ["Client"] + STAFF_READ_ROLES)
    client = require_path_resource("clients", cid, "client")
    check_client_scope(caller, client["id"])
    return success_object(serialize_client(client))


@bp.post("/clients/<cid>/suspend")
def suspend_client(cid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    client = require_path_resource("clients", cid, "client")
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "suspend requires an ACTIVE client")
    # Protective cascade: auto-void the open pantry visit, if any.
    for v in list(db["pantry_visits"].values()):
        if v["client_id"] == client["id"] and v["status"] == "CHECKED_IN":
            void_visit(v)
    client["status"] = "SUSPENDED"
    touch(client)
    return success_object(serialize_client(client))


@bp.post("/clients/<cid>/reinstate")
def reinstate_client(cid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    client = require_path_resource("clients", cid, "client")
    if client["status"] != "SUSPENDED":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "reinstate requires a SUSPENDED client")
    client["status"] = "ACTIVE"
    touch(client)
    return success_object(serialize_client(client))


@bp.post("/clients/<cid>/exit")
def exit_client(cid):
    caller = authenticate()
    authorize(caller, ["IntakeCoordinator", "HubAdmin"])
    client = require_path_resource("clients", cid, "client")
    if client["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_CLIENT_NOT_ACTIVE, "exit requires an ACTIVE or SUSPENDED client")
    _exit_unwind(client)
    client["status"] = "EXITED"
    touch(client)
    return success_object(serialize_client(client))


def _exit_unwind(client):
    """Atomic unwind of every open engagement (PRD 3.1)."""
    now = CLOCK.now()
    cid = client["id"]
    # Future RESERVED shelter stays -> CANCELLED (frees bed intervals)
    for s in list(db["shelter_stays"].values()):
        if s["client_id"] == cid and s["status"] == "RESERVED":
            s["status"] = "CANCELLED"
            touch(s)
    # INITIATED/SENT referrals -> WITHDRAWN; SENT withdrawal frees agency capacity
    for r in list(db["referrals"].values()):
        if r["client_id"] == cid and r["status"] in ("INITIATED", "SENT"):
            was_sent = r["status"] == "SENT"
            r["status"] = "WITHDRAWN"
            touch(r)
            if was_sent:
                agency = db["partner_agencies"].get(r["agency_id"])
                if agency is not None:
                    recompute_agency(agency)
    # REGISTERED registrations for future events -> CANCELLED
    for reg in list(db["event_registrations"].values()):
        if reg["client_id"] == cid and reg["status"] == "REGISTERED":
            event = db["outreach_events"].get(reg["event_id"])
            if event is not None and parse_datetime(event["event_date"]) > now:
                reg["status"] = "CANCELLED"
                touch(reg)
                recompute_event(event)  # count recompute; may flip FULL -> OPEN
    # Open pantry visit -> VOIDED
    for v in list(db["pantry_visits"].values()):
        if v["client_id"] == cid and v["status"] == "CHECKED_IN":
            void_visit(v)
    # DRAFT assessments -> DISCARDED
    for a in list(db["assessments"].values()):
        if a["client_id"] == cid and a["status"] == "DRAFT":
            a["status"] = "DISCARDED"
            touch(a)
