"""Waitlist entries (PRD §3.7)."""
from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, pricing, serializers, workflow

bp = Blueprint("waitlist", __name__)


@bp.route("/api/waitlist-entries", methods=["POST"])
def create_waitlist_entry():
    actor = middleware.authenticate(["Buyer"])
    payload = middleware.body()
    ticket_type_id = middleware.req_string(payload, "ticket_type_id")
    buyer_id = middleware.req_string(payload, "buyer_id")
    requested_quantity = middleware.req_int(
        payload, "requested_quantity", minimum=1, maximum=C.MAX_TICKETS_PER_BUYER_PER_EVENT
    )

    buyer = lookup.buyer(buyer_id)
    tier = lookup.ticket_type(ticket_type_id)
    lookup.require_buyer_is(actor, buyer["id"])

    if derive.tier_available(tier) > 0:
        raise ApiError("ERR_CAPACITY_AVAILABLE", "The tier still has capacity; buy instead.")

    record = db.base_record()
    record.update(
        {
            "ticket_type_id": tier["id"],
            "buyer_id": buyer["id"],
            "claimed_order_id": None,
            "requested_quantity": requested_quantity,
            "status": "WAITING",
            "offered_at": None,
            "offer_expires_at": None,
        }
    )
    db.store.waitlist_entries[record["id"]] = record
    return object_response(serializers.waitlist_entry(record), 201)


@bp.route("/api/waitlist-entries/<entry_id>", methods=["GET"])
def read_waitlist_entry(entry_id):
    actor = middleware.authenticate(["Buyer", "Organizer", "PlatformAdmin"])
    record = lookup.waitlist_entry(entry_id)
    lookup.require_buyer_is(actor, record["buyer_id"])
    tier = db.store.ticket_types.get(record["ticket_type_id"])
    if tier is not None:
        event = db.store.events.get(tier["event_id"])
        if event is not None:
            lookup.require_organizer_owns_event(actor, event)
    return object_response(serializers.waitlist_entry(record))


@bp.route("/api/waitlist-entries", methods=["GET"])
def list_waitlist_entries():
    middleware.authenticate(["Buyer", "Organizer", "PlatformAdmin"])
    ticket_type_id = request.args.get("ticket_type_id")
    buyer_id = request.args.get("buyer_id")
    claimed_order_id = request.args.get("claimed_order_id")
    status = middleware.query_enum("status", C.WAITLIST_STATUSES)
    records = [
        w
        for w in db.store.waitlist_entries.values()
        if (ticket_type_id is None or w["ticket_type_id"] == ticket_type_id)
        and (buyer_id is None or w["buyer_id"] == buyer_id)
        and (claimed_order_id is None or w["claimed_order_id"] == claimed_order_id)
        and (status is None or w["status"] == status)
    ]
    return paginate(db.ordered(records), serializers.waitlist_entry)


@bp.route("/api/waitlist-entries/<entry_id>/claim", methods=["POST"])
def claim_waitlist_entry(entry_id):
    actor = middleware.authenticate(["Buyer"])
    middleware.body()
    record = lookup.waitlist_entry(entry_id)
    tier = lookup.ticket_type(record["ticket_type_id"])
    event = lookup.event(tier["event_id"])
    buyer = lookup.buyer(record["buyer_id"])
    lookup.require_buyer_is(actor, record["buyer_id"])

    if event["status"] != "ONSALE":
        raise ApiError("ERR_EVENT_NOT_ONSALE", "The event is not on sale.")
    if record["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_WAITLIST_STATE", "The entry is not in OFFERED.")
    deadline = db.parse_iso(record["offer_expires_at"]) if record["offer_expires_at"] else None
    if deadline is None or db.now() >= deadline:
        raise ApiError("ERR_WAITLIST_OFFER_EXPIRED", "The waitlist offer has expired.")

    quantity = record["requested_quantity"]
    live = derive.buyer_live_ticket_count(buyer["id"], event["id"])
    if live + quantity > C.MAX_TICKETS_PER_BUYER_PER_EVENT:
        raise ApiError(
            "ERR_TICKET_LIMIT_EXCEEDED",
            "A buyer may hold at most %d live tickets per event."
            % C.MAX_TICKETS_PER_BUYER_PER_EVENT,
        )

    # The entry's own offer holds the capacity it is about to consume, so it is
    # excluded from the availability it is measured against.
    available = derive.tier_available(tier, exclude_waitlist_entry_id=record["id"])
    if available == 0:
        raise ApiError("ERR_SOLD_OUT", "The tier is sold out.")
    if available < quantity:
        raise ApiError("ERR_INSUFFICIENT_CAPACITY", "Not enough tickets remain on the tier.")

    line = pricing.line_amounts(tier["price_cents"], quantity)
    line.update(
        {
            "ticket_type_id": tier["id"],
            "seat_block_id": None,
            "quantity": quantity,
            "seat_numbers": [],
        }
    )
    order = workflow.create_order(event, buyer, [line])

    record["status"] = "CLAIMED"
    record["claimed_order_id"] = order["id"]
    db.touch(record)
    return object_response(serializers.waitlist_entry(record))


@bp.route("/api/waitlist-entries/<entry_id>/requeue", methods=["POST"])
def requeue_waitlist_entry(entry_id):
    actor = middleware.authenticate(["Buyer"])
    middleware.body()
    record = lookup.waitlist_entry(entry_id)
    tier = lookup.ticket_type(record["ticket_type_id"])
    event = lookup.event(tier["event_id"])
    lookup.require_buyer_is(actor, record["buyer_id"])

    if record["status"] != "EXPIRED":
        raise ApiError("ERR_INVALID_WAITLIST_STATE", "The entry is not in EXPIRED.")
    if event["status"] not in ("ONSALE", "PAUSED"):
        raise ApiError("ERR_EVENT_NOT_ONSALE", "The event is not accepting waitlist activity.")

    record["status"] = "WAITING"
    record["offered_at"] = None
    record["offer_expires_at"] = None
    db.touch(record)
    return object_response(serializers.waitlist_entry(record))
