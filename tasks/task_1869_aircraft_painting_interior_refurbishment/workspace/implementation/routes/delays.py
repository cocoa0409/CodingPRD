"""DelayEvent endpoints (REPORTED -> CONFIRMED / DISPUTED)."""
from flask import Blueprint, request

from db import STORE
from domain import (new_entity, bump, bump_program, regen_draft_invoices,
                    get_or_404, by_created, serialize_delay_event)
from errors import ApiError, ref_integrity, invalid_state, ERR_FORBIDDEN_OWNERSHIP
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("delays", __name__)

CATEGORIES = ("CUSTOMER_CAUSED", "CENTER_CAUSED", "FORCE_MAJEURE")


@bp.post("/delay-events")
def create_delay_event():
    auth("ProgramManager")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    category = field(data, "category", "str", enum=CATEGORIES)
    impact_days = field(data, "impact_days", "int")
    reason = field(data, "reason", "str")
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] in ("DELIVERED", "CANCELLED"):
        raise invalid_state("Cannot report a delay event for a terminal program")
    seqs = [e["event_seq"] for e in STORE.delay_events.values()
            if e["program_id"] == program_id]
    event = new_entity()
    event.update({
        "program_id": program_id,
        "category": category,
        "impact_days": impact_days,
        "reason": reason,
        "source": "MANUAL",
        "status": "REPORTED",
        "event_seq": (max(seqs) + 1) if seqs else 1,
    })
    STORE.delay_events[event["id"]] = event
    return success(serialize_delay_event(event), status=201)


@bp.get("/delay-events/<did>")
def get_delay_event(did):
    auth()
    event = get_or_404(STORE.delay_events, did, "DelayEvent")
    return success(serialize_delay_event(event))


@bp.get("/delay-events")
def list_delay_events():
    auth()
    items = by_created(list(STORE.delay_events.values()))
    for key in ("program_id", "status", "category"):
        value = request.args.get(key)
        if value is not None:
            items = [e for e in items if e[key] == value]
    return paginate(items, serialize_delay_event)


@bp.post("/delay-events/<did>/confirm")
def confirm_delay_event(did):
    auth("CenterAdmin")
    event = get_or_404(STORE.delay_events, did, "DelayEvent")
    if event["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED delay event can be confirmed")
    event["status"] = "CONFIRMED"
    bump(event)
    prog = STORE.programs[event["program_id"]]
    bump_program(prog)
    # committed_delivery_date (derived) shifts for excusable categories;
    # projected penalty recomputes on read; DRAFT invoices regenerate lines.
    regen_draft_invoices(prog["id"])
    return success(serialize_delay_event(event))


@bp.post("/delay-events/<did>/dispute")
def dispute_delay_event(did):
    user_id, _ = auth("CustomerRep")
    event = get_or_404(STORE.delay_events, did, "DelayEvent")
    prog = STORE.programs[event["program_id"]]
    if user_id != prog["customer_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "X-User-ID does not match the program's customer_id")
    if event["status"] != "REPORTED":
        raise invalid_state("Only a REPORTED delay event can be disputed")
    event["status"] = "DISPUTED"
    bump(event)
    return success(serialize_delay_event(event))
