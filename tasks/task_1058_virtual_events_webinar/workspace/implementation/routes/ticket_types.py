"""Ticket types and seat availability (PRD 3.2)."""

from flask import Blueprint

import db
from auth import authorize, own_event
from db import S
from response import ok, ok_list
from validate import (
    body, get_event, get_ticket_type, pagination, paginate, qs, req_enum,
    req_int, req_str,
)

bp = Blueprint("ticket_types", __name__)

TIERS = ("GENERAL", "VIP", "SPONSOR", "SPEAKER")
GATING_LEVELS = ("LIVE_ONLY", "ON_DEMAND", "BOTH")


@bp.route("/api/events/<event_id>/ticket-types", methods=["POST"])
def create_ticket_type(event_id):
    authorize("Organizer")
    event = get_event(event_id)
    own_event(event)
    b = body()
    name = req_str(b, "name")
    tier = req_enum(b, "tier", TIERS)
    price_cents = req_int(b, "price_cents", minimum=0)
    quota = req_int(b, "quota", minimum=1)
    gating_level = req_enum(b, "gating_level", GATING_LEVELS)

    row = db.new_row({
        "event_id": event["id"],
        "name": name,
        "tier": tier,
        "price_cents": price_cents,
        "quota": quota,
        "gating_level": gating_level,
        "sold_count": 0,
        "availability_status": "AVAILABLE",
    })
    S.ticket_types[row["id"]] = row
    db.touch(event)
    return ok(db.serialize(row), 201)


@bp.route("/api/events/<event_id>/ticket-types", methods=["GET"])
def list_event_ticket_types(event_id):
    authorize("Organizer", "PlatformAdmin", "Attendee", "FinanceAdmin")
    event = get_event(event_id)
    limit, offset = pagination()
    rows = [t for t in S.ticket_types.values() if t.get("event_id") == event["id"]]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/ticket-types", methods=["GET"])
def list_ticket_types():
    authorize("Organizer", "PlatformAdmin", "Attendee", "FinanceAdmin")
    limit, offset = pagination()
    event_id = qs("event_id")
    tier = qs("tier")
    availability_status = qs("availability_status")
    rows = [
        t for t in S.ticket_types.values()
        if (event_id is None or t.get("event_id") == event_id)
        and (tier is None or t.get("tier") == tier)
        and (availability_status is None or t.get("availability_status") == availability_status)
    ]
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/api/ticket-types/<ticket_type_id>", methods=["GET"])
def read_ticket_type(ticket_type_id):
    authorize("Organizer", "PlatformAdmin", "Attendee", "FinanceAdmin")
    row = get_ticket_type(ticket_type_id)
    return ok(db.serialize(row))
