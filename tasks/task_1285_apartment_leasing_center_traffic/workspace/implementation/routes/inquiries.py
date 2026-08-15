"""Inquiry endpoints (guest cards: create, claim, respond, mark-lost)."""
from flask import Blueprint

from db import DB, clock_now, new_id
from errors import ApiError
from middleware import AGENT, PM, auth
from response import ok, ok_list
from services import (
    INQUIRY_SOURCES,
    cancel_scheduled_tours,
    get_floorplan,
    get_inquiry,
    get_property,
    response_met_target,
    ser_inquiry,
    sorted_created,
    stamp,
    touch,
)
from util import (
    apply_filters,
    as_enum,
    as_str,
    body,
    opt,
    pagination,
    required,
)

bp = Blueprint("inquiries", __name__)

STAFF = [PM, AGENT]


@bp.post("/leasing/inquiries")
def create_inquiry():
    auth(STAFF)
    data = body()
    property_id = as_str(required(data, "property_id"), "property_id")
    floorplan_id = opt(data, "floorplan_id")
    if floorplan_id is not None:
        as_str(floorplan_id, "floorplan_id")
    contact_name = as_str(required(data, "contact_name"), "contact_name")
    contact_email = as_str(required(data, "contact_email"), "contact_email")
    source = as_enum(required(data, "source"), "source", INQUIRY_SOURCES)

    get_property(property_id)
    if floorplan_id is not None:
        get_floorplan(floorplan_id)

    rec = {
        "id": new_id(),
        "property_id": property_id,
        "floorplan_id": floorplan_id,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "source": source,
        "assigned_agent_id": None,
        "first_responded_at": None,
        "response_met_target": None,
        "status": "NEW",
    }
    stamp(rec)
    DB["inquiries"][rec["id"]] = rec
    return ok(ser_inquiry(rec), status=201)


@bp.get("/leasing/inquiries")
def list_inquiries():
    auth(STAFF)
    limit, offset = pagination()
    items = apply_filters(
        DB["inquiries"].values(),
        [
            ("property_id", "property_id"),
            ("floorplan_id", "floorplan_id"),
            ("assigned_agent_id", "assigned_agent_id"),
            ("status", "status"),
            ("source", "source"),
        ],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_inquiry(i) for i in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/inquiries/<iid>")
def get_one_inquiry(iid):
    auth(STAFF)
    return ok(ser_inquiry(get_inquiry(iid)))


@bp.post("/leasing/inquiries/<iid>/claim")
def claim_inquiry(iid):
    user_id, role = auth([AGENT, PM])
    inq = get_inquiry(iid)
    if inq["status"] not in ("NEW", "CONTACTED", "TOUR_SCHEDULED"):
        raise ApiError(
            "ERR_INQUIRY_INVALID_STATE", 409, "A terminal inquiry cannot be claimed"
        )
    if inq["assigned_agent_id"] is not None:
        raise ApiError(
            "ERR_INQUIRY_INVALID_STATE", 409, "Inquiry is already assigned"
        )
    # Inactive agents cannot be assigned new inquiries (PRD §3.1).
    agent = DB["agents"].get(user_id)
    if agent is not None and not agent["active"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "An inactive agent cannot be assigned inquiries"
        )
    inq["assigned_agent_id"] = user_id
    touch(inq)
    return ok(ser_inquiry(inq))


@bp.post("/leasing/inquiries/<iid>/respond")
def respond_inquiry(iid):
    user_id, role = auth([AGENT, PM])
    inq = get_inquiry(iid)
    # Ownership: the assigned agent or a PropertyManager (priority 2).
    if role != PM and user_id != inq["assigned_agent_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_AGENT",
            403,
            "Caller is neither the assigned agent nor a PropertyManager",
        )
    # State checks (priority 4): terminal first, then repeat-response, then unassigned.
    if inq["status"] in ("LOST", "CONVERTED"):
        raise ApiError(
            "ERR_INQUIRY_INVALID_STATE", 409, "A terminal inquiry cannot be responded to"
        )
    if inq["status"] != "NEW":
        raise ApiError(
            "ERR_ALREADY_RESPONDED", 409, "Inquiry already has a first response"
        )
    if inq["assigned_agent_id"] is None:
        raise ApiError(
            "ERR_INQUIRY_INVALID_STATE", 409, "Inquiry must be assigned before responding"
        )
    now = clock_now()
    prop = DB["properties"][inq["property_id"]]
    inq["first_responded_at"] = now
    inq["response_met_target"] = response_met_target(inq, prop, now)
    inq["status"] = "CONTACTED"
    touch(inq)
    return ok(ser_inquiry(inq))


@bp.post("/leasing/inquiries/<iid>/mark-lost")
def mark_lost_inquiry(iid):
    user_id, role = auth([AGENT, PM])
    inq = get_inquiry(iid)
    if role != PM and user_id != inq["assigned_agent_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_AGENT",
            403,
            "Caller is neither the assigned agent nor a PropertyManager",
        )
    if inq["status"] not in ("NEW", "CONTACTED", "TOUR_SCHEDULED"):
        raise ApiError(
            "ERR_INQUIRY_INVALID_STATE",
            409,
            "Only NEW, CONTACTED, or TOUR_SCHEDULED inquiries can be marked lost",
        )
    inq["status"] = "LOST"
    touch(inq)
    cancel_scheduled_tours(inq)
    return ok(ser_inquiry(inq))
