"""Organizers, venues and buyers (PRD §3.1) plus the reliability read (§3.9)."""
from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response
from services import lookup, reliability, serializers

bp = Blueprint("parties", __name__)


# ---------------------------------------------------------------- organizers
@bp.route("/api/organizers", methods=["POST"])
def create_organizer():
    middleware.authenticate(["PlatformAdmin"])
    payload = middleware.body()
    display_name = middleware.req_string(payload, "display_name")
    contact_email = middleware.req_string(payload, "contact_email")

    record = db.base_record()
    record.update(
        {
            "display_name": display_name,
            "contact_email": contact_email,
            "lifetime_gross_cents": 0,
            "lifetime_refunds_cents": 0,
        }
    )
    db.store.organizers[record["id"]] = record
    return object_response(serializers.organizer(record), 201)


@bp.route("/api/organizers/<organizer_id>", methods=["GET"])
def read_organizer(organizer_id):
    middleware.authenticate(["Organizer", "PlatformAdmin", "FinanceOfficer"])
    record = lookup.organizer(organizer_id)
    return object_response(serializers.organizer(record))


@bp.route("/api/organizers/<organizer_id>/reliability", methods=["GET"])
def read_reliability(organizer_id):
    middleware.authenticate(["Organizer", "PlatformAdmin", "FinanceOfficer"])
    variant = request.args.get("variant")
    if variant is None:
        variant = "LIFETIME"
    if variant not in ("LIFETIME", "TRAILING"):
        raise ApiError("ERR_INVALID_REQUEST", "variant must be LIFETIME or TRAILING.")
    record = lookup.organizer(organizer_id)
    value, counted = reliability.score(record["id"], variant)
    return object_response(
        {
            "organizer_id": record["id"],
            "variant": variant,
            "score": value,
            "events_counted": counted,
        }
    )


# -------------------------------------------------------------------- venues
@bp.route("/api/venues", methods=["POST"])
def create_venue():
    middleware.authenticate(["PlatformAdmin"])
    payload = middleware.body()
    name = middleware.req_string(payload, "name")
    city = middleware.req_string(payload, "city")
    seated_capacity = middleware.req_int(payload, "seated_capacity", minimum=1)

    record = db.base_record()
    record.update({"name": name, "city": city, "seated_capacity": seated_capacity})
    db.store.venues[record["id"]] = record
    return object_response(serializers.venue(record), 201)


@bp.route("/api/venues/<venue_id>", methods=["GET"])
def read_venue(venue_id):
    middleware.authenticate(["Organizer", "PlatformAdmin", "FinanceOfficer"])
    record = lookup.venue(venue_id)
    return object_response(serializers.venue(record))


# -------------------------------------------------------------------- buyers
@bp.route("/api/buyers", methods=["POST"])
def create_buyer():
    middleware.authenticate(["Anonymous", "PlatformAdmin"])
    payload = middleware.body()
    email = middleware.req_string(payload, "email")
    display_name = middleware.req_string(payload, "display_name")

    for existing in db.store.buyers.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_PROMO_CODE", "A buyer with that email already exists.")

    record = db.base_record()
    record.update({"email": email, "display_name": display_name})
    db.store.buyers[record["id"]] = record
    return object_response(serializers.buyer(record), 201)


@bp.route("/api/buyers/<buyer_id>", methods=["GET"])
def read_buyer(buyer_id):
    middleware.authenticate(["Buyer", "PlatformAdmin", "Organizer"])
    record = lookup.buyer(buyer_id)
    return object_response(serializers.buyer(record))
