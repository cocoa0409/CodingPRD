"""Listing endpoints: create, get, valuation, activation (PRD 3.2)."""
from flask import Blueprint

import db as dbmod
from errors import (
    ERR_INVALID_STATE,
    ERR_LISTING_NOT_FOUND,
    ERR_VALUATION_REQUIRED,
    raise_error,
)
from middleware import ALL_ROLES, require_roles
from response import success_object
from services.core import new_record, serialize, touch
from services.valuation import run_valuation
from validate import body, req_enum, req_int, req_money, req_str

bp = Blueprint("listings", __name__)


def _get_listing(listing_id):
    rec = dbmod.db["listings"].get(listing_id)
    if rec is None:
        raise_error(ERR_LISTING_NOT_FOUND, "listing id does not exist")
    return rec


@bp.post("/api/listings")
@require_roles(["ListingAgent"])
def create_listing():
    b = body()
    rec = new_record(
        "listings",
        {
            "tail_number": req_str(b, "tail_number"),
            "make": req_str(b, "make"),
            "model": req_str(b, "model"),
            "year": req_int(b, "year"),
            "total_time_hours": req_int(b, "total_time_hours", min_value=0),
            "asking_price_usd": req_money(b, "asking_price_usd"),
            "seller_name": req_str(b, "seller_name"),
            "market_value_estimate_usd": None,
            "valuation_status": "NONE",
            "status": "DRAFT",
        },
    )
    return success_object(serialize("listings", rec), 201)


@bp.get("/api/listings/<listing_id>")
@require_roles(ALL_ROLES)
def get_listing(listing_id):
    return success_object(serialize("listings", _get_listing(listing_id)))


@bp.post("/api/listings/<listing_id>/valuation")
@require_roles(["ListingAgent"])
def valuation(listing_id):
    listing = _get_listing(listing_id)
    b = body()
    variant = req_enum(b, "variant", ["PROVISIONAL", "FINAL"])
    value = run_valuation(listing, variant, dbmod.db["comps"].values())
    listing["market_value_estimate_usd"] = value
    listing["valuation_status"] = variant
    touch(listing)
    return success_object(serialize("listings", listing))


@bp.post("/api/listings/<listing_id>/activate")
@require_roles(["ListingAgent"])
def activate(listing_id):
    listing = _get_listing(listing_id)
    if listing["status"] != "DRAFT":
        raise_error(
            ERR_INVALID_STATE,
            "only a DRAFT listing can be activated",
        )
    if listing["valuation_status"] != "FINAL":
        raise_error(
            ERR_VALUATION_REQUIRED,
            "activation requires a FINAL-variant valuation",
        )
    listing["status"] = "ACTIVE"
    touch(listing)
    return success_object(serialize("listings", listing))
