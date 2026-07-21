"""Ticket transfers (PRD §3.6)."""
import datetime

from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import lookup, serializers

bp = Blueprint("transfer_requests", __name__)


def _event_of_attendee(attendee):
    return db.store.events.get(attendee["event_id"])


@bp.route("/api/transfer-requests", methods=["POST"])
def create_transfer_request():
    actor = middleware.authenticate(["Buyer"])
    payload = middleware.body()
    attendee_id = middleware.req_string(payload, "attendee_id")
    to_email = middleware.req_string(payload, "to_email")

    attendee = lookup.attendee(attendee_id)
    lookup.require_buyer_is(actor, attendee["buyer_id"])

    if attendee["status"] == "VOIDED":
        raise ApiError("ERR_TICKET_VOIDED", "The admission has been voided.")
    if attendee["status"] not in ("ISSUED", "TRANSFERRED"):
        raise ApiError("ERR_ATTENDEE_NOT_ISSUED", "The admission is not transferable.")

    record = db.base_record()
    record.update(
        {
            "attendee_id": attendee["id"],
            "from_buyer_id": attendee["buyer_id"],
            "to_buyer_id": None,
            "to_email": to_email,
            "status": "DRAFT",
            "offer_expires_at": None,
            "resend_count": 0,
        }
    )
    db.store.transfer_requests[record["id"]] = record
    return object_response(serializers.transfer_request(record), 201)


@bp.route("/api/transfer-requests/<transfer_id>", methods=["GET"])
def read_transfer_request(transfer_id):
    actor = middleware.authenticate(["Buyer", "Organizer", "PlatformAdmin"])
    record = lookup.transfer_request(transfer_id)
    if actor.role == "Buyer" and actor.user_id not in (
        record["from_buyer_id"],
        record["to_buyer_id"],
    ):
        lookup.unauthorized()
    if actor.role == "Organizer":
        attendee = db.store.attendees.get(record["attendee_id"])
        event = _event_of_attendee(attendee) if attendee else None
        if event is not None:
            lookup.require_organizer_owns_event(actor, event)
    return object_response(serializers.transfer_request(record))


@bp.route("/api/transfer-requests", methods=["GET"])
def list_transfer_requests():
    middleware.authenticate(["Buyer", "Organizer", "PlatformAdmin"])
    attendee_id = request.args.get("attendee_id")
    from_buyer_id = request.args.get("from_buyer_id")
    to_buyer_id = request.args.get("to_buyer_id")
    status = middleware.query_enum("status", C.TRANSFER_STATUSES)
    records = [
        t
        for t in db.store.transfer_requests.values()
        if (attendee_id is None or t["attendee_id"] == attendee_id)
        and (from_buyer_id is None or t["from_buyer_id"] == from_buyer_id)
        and (to_buyer_id is None or t["to_buyer_id"] == to_buyer_id)
        and (status is None or t["status"] == status)
    ]
    return paginate(db.ordered(records), serializers.transfer_request)


@bp.route("/api/transfer-requests/<transfer_id>/send", methods=["POST"])
def send_transfer_request(transfer_id):
    actor = middleware.authenticate(["Buyer"])
    middleware.body()
    record = lookup.transfer_request(transfer_id)
    attendee = lookup.attendee(record["attendee_id"])

    if actor.role == "Buyer" and actor.user_id not in (
        attendee["buyer_id"],
        record["from_buyer_id"],
    ):
        lookup.unauthorized()

    if record["status"] not in ("DRAFT", "DECLINED"):
        raise ApiError("ERR_INVALID_TRANSFER_STATE", "The offer cannot be sent from that status.")
    if attendee["status"] not in ("ISSUED", "TRANSFERRED"):
        raise ApiError("ERR_ATTENDEE_NOT_ISSUED", "The admission is not transferable.")
    event = lookup.event(attendee["event_id"])
    if event["status"] not in ("ONSALE", "PAUSED", "SALES_CLOSED"):
        raise ApiError("ERR_EVENT_NOT_ONSALE", "Transfers are closed for this event.")

    resend = record["status"] == "DECLINED"
    record["status"] = "SENT"
    record["offer_expires_at"] = db.iso(
        db.now() + datetime.timedelta(hours=C.TRANSFER_OFFER_TTL_HOURS)
    )
    if resend:
        record["resend_count"] += 1
    db.touch(record)
    return object_response(serializers.transfer_request(record))


def _respond_target(transfer_id):
    actor = middleware.authenticate(["Buyer"])
    payload = middleware.body()
    to_buyer_id = middleware.req_string(payload, "to_buyer_id")

    record = lookup.transfer_request(transfer_id)
    buyer = lookup.buyer(to_buyer_id)

    lookup.require_buyer_is(actor, buyer["id"])
    if buyer["email"] != record["to_email"]:
        lookup.unauthorized()

    if record["status"] != "SENT":
        raise ApiError("ERR_INVALID_TRANSFER_STATE", "The offer is not in SENT.")

    deadline = db.parse_iso(record["offer_expires_at"]) if record["offer_expires_at"] else None
    if deadline is not None and db.now() >= deadline:
        record["status"] = "EXPIRED"
        db.touch(record)
        raise ApiError("ERR_TRANSFER_TTL_EXPIRED", "The transfer offer has expired.")

    return record, buyer


@bp.route("/api/transfer-requests/<transfer_id>/accept", methods=["POST"])
def accept_transfer_request(transfer_id):
    record, buyer = _respond_target(transfer_id)
    attendee = lookup.attendee(record["attendee_id"])

    record["status"] = "ACCEPTED"
    record["to_buyer_id"] = buyer["id"]
    db.touch(record)

    attendee["buyer_id"] = buyer["id"]
    attendee["holder_email"] = buyer["email"]
    attendee["status"] = "TRANSFERRED"
    db.touch(attendee)

    return object_response(serializers.transfer_request(record))


@bp.route("/api/transfer-requests/<transfer_id>/decline", methods=["POST"])
def decline_transfer_request(transfer_id):
    record, _buyer = _respond_target(transfer_id)
    record["status"] = "DECLINED"
    record["offer_expires_at"] = None
    db.touch(record)
    return object_response(serializers.transfer_request(record))
