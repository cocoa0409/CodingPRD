"""Ticket tiers (PRD §3.3) and the organiser-run waitlist sweep (§3.7)."""
import datetime

from flask import Blueprint, request

import db
import middleware
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, serializers

bp = Blueprint("ticket_types", __name__)


@bp.route("/api/ticket-types", methods=["POST"])
def create_ticket_type():
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    event_id = middleware.req_string(payload, "event_id")
    name = middleware.req_string(payload, "name")
    tier_rank = middleware.req_int(payload, "tier_rank", minimum=1)
    price_cents = middleware.req_int(payload, "price_cents", minimum=0)
    quantity_total = middleware.req_int(payload, "quantity_total", minimum=1)
    seating_mode = middleware.opt_enum(payload, "seating_mode", C.SEATING_MODES, "GA")

    event = lookup.event(event_id)
    lookup.require_organizer_owns_event(actor, event)

    record = db.base_record()
    record.update(
        {
            "event_id": event["id"],
            "name": name,
            "tier_rank": tier_rank,
            "price_cents": price_cents,
            "quantity_total": quantity_total,
            "seating_mode": seating_mode,
        }
    )
    db.store.ticket_types[record["id"]] = record
    db.touch(event)
    return object_response(serializers.ticket_type(record), 201)


@bp.route("/api/ticket-types/<ticket_type_id>", methods=["GET"])
def read_ticket_type(ticket_type_id):
    middleware.authenticate(
        ["Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous"]
    )
    record = lookup.ticket_type(ticket_type_id)
    return object_response(serializers.ticket_type(record))


@bp.route("/api/ticket-types", methods=["GET"])
def list_ticket_types():
    middleware.authenticate(
        ["Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous"]
    )
    event_id = request.args.get("event_id")
    seating_mode = middleware.query_enum("seating_mode", C.SEATING_MODES)
    records = [
        t
        for t in db.store.ticket_types.values()
        if (event_id is None or t["event_id"] == event_id)
        and (seating_mode is None or t["seating_mode"] == seating_mode)
    ]
    return paginate(db.ordered(records), serializers.ticket_type)


@bp.route("/api/ticket-types/<ticket_type_id>", methods=["PATCH"])
def patch_ticket_type(ticket_type_id):
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    price_cents = middleware.opt_int(payload, "price_cents", minimum=0)
    quantity_total = middleware.opt_int(payload, "quantity_total", minimum=1)

    record = lookup.ticket_type(ticket_type_id)
    event = lookup.event(record["event_id"])
    lookup.require_organizer_owns_event(actor, event)

    if price_cents is not None:
        record["price_cents"] = price_cents
    if quantity_total is not None:
        record["quantity_total"] = quantity_total
    db.touch(record)
    db.touch(event)
    return object_response(serializers.ticket_type(record))


@bp.route("/api/ticket-types/<ticket_type_id>/waitlist-sweep", methods=["POST"])
def waitlist_sweep(ticket_type_id):
    actor = middleware.authenticate(["Organizer"])
    middleware.body()
    tier = lookup.ticket_type(ticket_type_id)
    event = lookup.event(tier["event_id"])
    lookup.require_organizer_owns_event(actor, event)

    now = db.now()
    entries = [
        w for w in db.store.waitlist_entries.values() if w["ticket_type_id"] == tier["id"]
    ]

    # 1. retire stale offers first
    expired_ids = []
    for entry in db.ordered(entries):
        if entry["status"] != "OFFERED":
            continue
        deadline = db.parse_iso(entry["offer_expires_at"])
        if deadline is not None and now >= deadline:
            entry["status"] = "EXPIRED"
            db.touch(entry)
            expired_ids.append(entry["id"])

    # 2. only then compute the now-current available capacity
    remaining = derive.tier_available(tier)

    candidates = sorted(
        [w for w in entries if w["status"] == "WAITING"],
        key=lambda w: (w["created_at"], w["requested_quantity"], w["_seq"]),
    )

    offered_ids = []
    offer_expires_at = db.iso(now + datetime.timedelta(hours=C.WAITLIST_OFFER_TTL_HOURS))
    for entry in candidates:
        if entry["requested_quantity"] <= remaining:
            entry["status"] = "OFFERED"
            entry["offered_at"] = db.now_iso()
            entry["offer_expires_at"] = offer_expires_at
            db.touch(entry)
            remaining -= entry["requested_quantity"]
            offered_ids.append(entry["id"])

    return object_response(
        {
            "ticket_type_id": tier["id"],
            "expired_entry_ids": expired_ids,
            "offered_entry_ids": offered_ids,
            "offered_count": len(offered_ids),
            "remaining_available": remaining,
        }
    )
