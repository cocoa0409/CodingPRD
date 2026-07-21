"""Seat blocks on RESERVED tiers (PRD §3.3)."""
from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import lookup, serializers

bp = Blueprint("seat_blocks", __name__)


@bp.route("/api/seat-blocks", methods=["POST"])
def create_seat_block():
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    ticket_type_id = middleware.req_string(payload, "ticket_type_id")
    row_label = middleware.req_string(payload, "row_label")
    seat_from = middleware.req_int(payload, "seat_from", minimum=1)
    seat_to = middleware.req_int(payload, "seat_to", minimum=1)

    tier = lookup.ticket_type(ticket_type_id)
    event = lookup.event(tier["event_id"])
    lookup.require_organizer_owns_event(actor, event)

    for existing in db.store.seat_blocks.values():
        if existing["ticket_type_id"] == tier["id"] and existing["row_label"] == row_label:
            raise ApiError(
                "ERR_DUPLICATE_PROMO_CODE", "row_label is already used on this tier."
            )

    if seat_to < seat_from:
        raise ApiError("ERR_SEAT_RANGE_INVALID", "seat_to must be at least seat_from.")

    record = db.base_record()
    record.update(
        {
            "ticket_type_id": tier["id"],
            "row_label": row_label,
            "seat_from": seat_from,
            "seat_to": seat_to,
        }
    )
    db.store.seat_blocks[record["id"]] = record
    return object_response(serializers.seat_block(record), 201)


@bp.route("/api/seat-blocks/<seat_block_id>", methods=["GET"])
def read_seat_block(seat_block_id):
    middleware.authenticate(
        ["Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous"]
    )
    record = lookup.seat_block(seat_block_id)
    return object_response(serializers.seat_block(record))


@bp.route("/api/seat-blocks", methods=["GET"])
def list_seat_blocks():
    middleware.authenticate(
        ["Organizer", "Buyer", "GateStaff", "FinanceOfficer", "PlatformAdmin", "Anonymous"]
    )
    ticket_type_id = request.args.get("ticket_type_id")
    records = [
        b
        for b in db.store.seat_blocks.values()
        if ticket_type_id is None or b["ticket_type_id"] == ticket_type_id
    ]
    return paginate(db.ordered(records), serializers.seat_block)
