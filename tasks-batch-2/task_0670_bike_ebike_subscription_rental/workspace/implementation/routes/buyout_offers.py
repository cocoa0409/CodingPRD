from flask import Blueprint, request

from db import db
from clock import clock, parse_clock_field
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_INVALID_REQUEST, ERR_OFFER_EXPIRED, ERR_INVALID_STATE
from services.common import (
    stamp_create, touch, get_json_body, require_fields, parse_pagination, paginate,
)
from services.lookups import get_rental, get_offer, check_rental_ownership
from services.reconcile import recompute_model_counts, recompute_active_rental_count
from services.serialize import buyout_offer_view
from services import calculations as calc

buyout_offers_bp = Blueprint("buyout_offers", __name__)

VIEW_ROLES = {"OpsAdmin", "Subscriber", "FleetManager"}
HOLDER_ROLES = {"Subscriber", "FleetManager"}


@buyout_offers_bp.route("/rentals/<rental_id>/buyout-offers", methods=["POST"])
def quote_buyout(rental_id):
    user_id, role = require_role(HOLDER_ROLES)
    body = get_json_body()
    require_fields(body, ["expires_at_clock"])
    with db.lock:
        rental = get_rental(rental_id)
        check_rental_ownership(rental, user_id, role)
        try:
            expires_at = parse_clock_field(body["expires_at_clock"])
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "expires_at_clock must be an ISO-8601 instant.")
        # expires_at must be strictly after current logical clock at creation.
        if not (expires_at > clock.now()):
            raise err(ERR_OFFER_EXPIRED, "expires_at_clock must be after the current clock.")

        model = db.bike_models[rental["model_id"]]
        quoted, equity = calc.buyout_price(model, rental)
        offer = {
            "rental_id": rental["id"],
            "quoted_price_cents": quoted,
            "equity_credit_cents": equity,
            "status": "QUOTED",
            "expires_at_clock": body["expires_at_clock"],
        }
        stamp_create(offer)
        db.buyout_offers[offer["id"]] = offer
    return object_response(buyout_offer_view(offer), 201)


@buyout_offers_bp.route("/buyout-offers/<offer_id>", methods=["GET"])
def fetch_offer(offer_id):
    require_role(VIEW_ROLES)
    offer = get_offer(offer_id)
    return object_response(buyout_offer_view(offer), 200)


@buyout_offers_bp.route("/rentals/<rental_id>/buyout-offers", methods=["GET"])
def list_offers(rental_id):
    require_role(VIEW_ROLES)
    get_rental(rental_id)
    limit, offset = parse_pagination()
    records = [o for o in db.buyout_offers.values() if o["rental_id"] == rental_id]
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([buyout_offer_view(r) for r in page], limit, offset, total)


@buyout_offers_bp.route("/buyout-offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    user_id, role = require_role(HOLDER_ROLES)
    with db.lock:
        offer = get_offer(offer_id)
        rental = db.rentals[offer["rental_id"]]
        check_rental_ownership(rental, user_id, role)

        # Accept requires rental ACTIVE, offer QUOTED, and not expired.
        if rental["lifecycle_status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Rental must be ACTIVE to accept buyout.")
        if offer["status"] != "QUOTED":
            raise err(ERR_INVALID_STATE, "Offer must be QUOTED to accept.")
        expires_at = parse_clock_field(offer["expires_at_clock"])
        if not (expires_at > clock.now()):
            raise err(ERR_OFFER_EXPIRED, "Offer has expired.")

        offer["status"] = "ACCEPTED"
        touch(offer)

        # Two-hop cascade: bike OUT->RETIRED, recompute model counts.
        bike = db.bikes.get(rental["bike_id"])
        if bike is not None:
            bike["bike_status"] = "RETIRED"
            bike["current_rental_id"] = None
            touch(bike)
            recompute_model_counts(bike["model_id"])

        rental["lifecycle_status"] = "BOUGHT_OUT"
        rental["billing_status"] = "SETTLED"
        touch(rental)

        # Refund full deposit to wallet (unit sold).
        account = db.accounts[rental["account_id"]]
        account["wallet_credit_cents"] += rental["deposit_cents"]
        touch(account)
        recompute_active_rental_count(rental["account_id"])

    return object_response(buyout_offer_view(offer), 200)
