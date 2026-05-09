from flask import Blueprint, request
from db import db
from envelope import success
from errors import APIError, ERR_DUPLICATE_PAYMENT_EVENT, ERR_NOT_FOUND
from validation import need_body, require_str, require_enum, require_decimal, require_timestamp
from serializers import serialize_payment_event
from common import to_money, new_id
from clock import clock

bp = Blueprint("payment_events", __name__)

VALID_EVENT_TYPES = {"PAYMENT_CONFIRMED", "PAYMENT_FAILED", "REFUND_CONFIRMED"}


@bp.post("/payment-events")
def receive_payment_event():
    body = need_body(request.get_json(silent=True))

    idempotency_key = require_str(body, "idempotency_key")
    if idempotency_key in db.payment_event_keys:
        raise APIError(ERR_DUPLICATE_PAYMENT_EVENT, 409, "Duplicate idempotency_key")

    event_type = require_enum(body, "event_type", VALID_EVENT_TYPES)
    rental_id = require_str(body, "rental_id")
    amount = to_money(require_decimal(body, "amount"))
    occurred_at = require_timestamp(body, "occurred_at")

    if rental_id not in db.rentals:
        raise APIError(ERR_NOT_FOUND, 404, "Rental not found")

    event = {
        "id": new_id(),
        "created_at": clock.now(),
        "idempotency_key": idempotency_key,
        "event_type": event_type,
        "rental_id": rental_id,
        "amount": amount,
        "occurred_at": occurred_at,
    }
    db.payment_events[event["id"]] = event
    db.payment_event_keys[idempotency_key] = event["id"]
    return success(serialize_payment_event(event))
