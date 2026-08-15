"""RenewalOffer endpoints (PRD 3.10)."""
from flask import Blueprint

import clock
import db
from errors import ApiError, invalid_state
from middleware import auth, require_roles, require_vendor_owner
from response import success
from services import calc
from services.core import (
    arg,
    as_dt,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    get_vendor,
    list_response,
    required,
    serialize,
    touch,
)
from routes.assignments import build_assignment

bp = Blueprint("renewal", __name__)

MO = ("MarketOperator",)
VENDOR = ("VendorRole",)
GET_ROLES = ("MarketOperator", "VendorRole")


def _resolve(marketId, offerId):
    get_market(marketId)
    return get_child("renewal_offers", offerId, marketId)


@bp.post("/markets/<marketId>/renewal_offers")
def create_renewal_offer(marketId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    data = body()
    vendor_id = as_str(required(data, "vendor_id"), "vendor_id")
    vendor = get_vendor(vendor_id)
    prior_assignment_id = as_str(required(data, "prior_assignment_id"), "prior_assignment_id")
    # the prior assignment belongs to the PRIOR season's market: global lookup
    prior = db.STORES["assignments"].get(prior_assignment_id)
    if prior is None:
        from errors import not_found

        raise not_found("prior assignment not found")
    offered_booth_id = as_str(required(data, "offered_booth_id"), "offered_booth_id")
    get_child("booths", offered_booth_id, marketId)
    offer_expires_at = as_dt(required(data, "offer_expires_at"), "offer_expires_at")
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "vendor_id": vendor_id,
            "prior_assignment_id": prior_assignment_id,
            "offered_booth_id": offered_booth_id,
            "offer_expires_at": offer_expires_at,
            "discount_pct": calc.compute_discount_pct(vendor["renewal_score"]),
            "status": "EXTENDED",
        }
    )
    db.STORES["renewal_offers"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/renewal_offers/<offerId>")
def get_renewal_offer(marketId, offerId):
    user = auth()
    require_roles(user, GET_ROLES)
    return success(serialize(_resolve(marketId, offerId)))


@bp.get("/markets/<marketId>/renewal_offers")
def list_renewal_offers(marketId):
    user = auth()
    require_roles(user, GET_ROLES)
    get_market(marketId)
    status = arg("status")
    vendor_id = arg("vendor_id")
    records = []
    for r in db.STORES["renewal_offers"].values():
        if r["market_id"] != marketId:
            continue
        if status is not None and r["status"] != status:
            continue
        if vendor_id is not None and r["vendor_id"] != vendor_id:
            continue
        records.append(r)
    return list_response(records)


@bp.post("/markets/<marketId>/renewal_offers/<offerId>/accept")
def accept_renewal_offer(marketId, offerId):
    user = auth()
    require_roles(user, VENDOR)
    market = get_market(marketId)
    offer = get_child("renewal_offers", offerId, marketId)
    require_vendor_owner(user, offer["vendor_id"])
    if offer["status"] != "EXTENDED":
        raise invalid_state("only an EXTENDED renewal offer can be accepted")
    if not clock.now() < offer["offer_expires_at"]:
        raise invalid_state("the renewal offer has passed offer_expires_at")
    booth = db.STORES["booths"].get(offer["offered_booth_id"])
    if booth is None or booth["status"] != "AVAILABLE":
        raise ApiError(
            "ERR_BOOTH_NO_LONGER_AVAILABLE",
            "the offered booth has been reserved or occupied since the offer was extended",
            409,
        )
    offer["status"] = "ACCEPTED"
    touch(offer)
    # auto-create ACCEPTED VendorApplication (skips jury) in the new market
    vendor_id = offer["vendor_id"]
    app = base_record()
    app.update(
        {
            "market_id": marketId,
            "vendor_id": vendor_id,
            "requested_booth_type": booth["booth_type"],
            "requested_pos": False,
            "heating_requested": False,
            "status": "ACCEPTED",
            "jury_scores": [],
            "jury_average": None,
            "decided_at": clock.now(),
        }
    )
    db.STORES["applications"][app["id"]] = app
    vendor = db.STORES["vendors"].get(vendor_id)
    if vendor is not None and vendor["status"] == "PROSPECT":
        vendor["status"] = "APPROVED"
        touch(vendor)
    # auto-create PENDING_PAYMENT BoothAssignment for (new application, booth)
    assignment = build_assignment(market, booth, app)
    booth["status"] = "RESERVED"
    booth["_reserved_for_assignment_id"] = assignment["id"]
    touch(booth)
    return success(serialize(offer))


@bp.post("/markets/<marketId>/renewal_offers/<offerId>/decline")
def decline_renewal_offer(marketId, offerId):
    user = auth()
    require_roles(user, VENDOR)
    offer = _resolve(marketId, offerId)
    require_vendor_owner(user, offer["vendor_id"])
    if offer["status"] != "EXTENDED":
        raise invalid_state("only an EXTENDED renewal offer can be declined")
    offer["status"] = "DECLINED"
    touch(offer)
    return success(serialize(offer))
