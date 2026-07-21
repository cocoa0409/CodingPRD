"""Promotional codes (PRD §3.3)."""
from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import lookup, serializers

bp = Blueprint("promo_codes", __name__)


@bp.route("/api/promo-codes", methods=["POST"])
def create_promo_code():
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    event_id = middleware.req_string(payload, "event_id")
    code = middleware.req_string(payload, "code")
    kind = middleware.req_enum(payload, "kind", C.PROMO_KINDS)
    percent_bp = middleware.opt_int(payload, "percent_bp", 0, minimum=0, maximum=10000)
    amount_cents = middleware.opt_int(payload, "amount_cents", 0, minimum=0)
    max_uses = middleware.req_int(payload, "max_uses", minimum=1)
    valid_from = middleware.req_datetime(payload, "valid_from")
    valid_until = middleware.req_datetime(payload, "valid_until")

    event = lookup.event(event_id)
    lookup.require_organizer_owns_event(actor, event)

    for existing in db.store.promo_codes.values():
        if existing["event_id"] == event["id"] and existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_PROMO_CODE", "That code already exists on this event.")

    record = db.base_record()
    record.update(
        {
            "event_id": event["id"],
            "code": code,
            "kind": kind,
            "percent_bp": percent_bp,
            "amount_cents": amount_cents,
            "max_uses": max_uses,
            "valid_from": db.iso(valid_from),
            "valid_until": db.iso(valid_until),
        }
    )
    db.store.promo_codes[record["id"]] = record
    return object_response(serializers.promo_code(record), 201)


@bp.route("/api/promo-codes/<promo_code_id>", methods=["GET"])
def read_promo_code(promo_code_id):
    actor = middleware.authenticate(["Organizer", "PlatformAdmin"])
    record = lookup.promo_code(promo_code_id)
    event = lookup.event(record["event_id"])
    lookup.require_organizer_owns_event(actor, event)
    return object_response(serializers.promo_code(record))


@bp.route("/api/promo-codes", methods=["GET"])
def list_promo_codes():
    middleware.authenticate(["Organizer", "PlatformAdmin"])
    event_id = request.args.get("event_id")
    code = request.args.get("code")
    records = [
        p
        for p in db.store.promo_codes.values()
        if (event_id is None or p["event_id"] == event_id)
        and (code is None or p["code"] == code)
    ]
    return paginate(db.ordered(records), serializers.promo_code)
