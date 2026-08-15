"""RateCard endpoints (price book with non-overlapping closed windows)."""
from flask import Blueprint, request

from db import store, new_record
from errors import ApiError, err_not_found, err_validation
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import wall_now
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("rate_cards", __name__)

ROLES = ["OpsAdmin", "Dispatcher", "BillingClerk"]


@bp.route("/roadside/rate-cards", methods=["POST"])
def create_rate_card():
    auth(["OpsAdmin"])
    vals = validate_body(request.get_json(silent=True), [
        Field("name", "string", required=True),
        Field("labor_rate_standard_cents", "int", required=True, min_val=0),
        Field("labor_rate_master_cents", "int", required=True, min_val=0),
        Field("after_hours_multiplier_bp", "int", required=True, min_val=0),
        Field("travel_free_miles", "int", required=True, min_val=0),
        Field("travel_per_mile_cents", "int", required=True, min_val=0),
        Field("travel_time_per_minute_cents", "int", required=True, min_val=0),
        Field("emergency_callout_fee_cents", "int", required=True, min_val=0),
        Field("parts_tax_rate_bp", "int", required=True, min_val=0),
        Field("effective_from", "datetime", required=True),
        Field("effective_to", "datetime", required=True),
    ])
    if vals["effective_to"] < vals["effective_from"]:
        raise err_validation("effective_to must be >= effective_from")
    # closed-closed windows: touching endpoints count as overlap
    for c in store.rate_cards.values():
        if (vals["effective_from"] <= c["effective_to"]
                and c["effective_from"] <= vals["effective_to"]):
            raise ApiError("ERR_RATE_CARD_WINDOW_OVERLAP",
                           "Rate card window overlaps an existing card", 409)
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "name": vals["name"],
        "labor_rate_standard_cents": vals["labor_rate_standard_cents"],
        "labor_rate_master_cents": vals["labor_rate_master_cents"],
        "after_hours_multiplier_bp": vals["after_hours_multiplier_bp"],
        "travel_free_miles": vals["travel_free_miles"],
        "travel_per_mile_cents": vals["travel_per_mile_cents"],
        "travel_time_per_minute_cents": vals["travel_time_per_minute_cents"],
        "emergency_callout_fee_cents": vals["emergency_callout_fee_cents"],
        "parts_tax_rate_bp": vals["parts_tax_rate_bp"],
        "effective_from": vals["effective_from"],
        "effective_to": vals["effective_to"],
    })
    store.rate_cards[rec["id"]] = rec
    return success(serialize("rate_card", rec), status=201)


@bp.route("/roadside/rate-cards/<rateCardId>", methods=["GET"])
def get_rate_card(rateCardId):
    auth(ROLES)
    rec = store.rate_cards.get(rateCardId)
    if rec is None:
        raise err_not_found("RateCard not found")
    return success(serialize("rate_card", rec))


@bp.route("/roadside/rate-cards", methods=["GET"])
def list_rate_cards():
    auth(ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(store.rate_cards.values(), key=lambda r: r["_seq"])
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("rate_card", c) for c in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})
