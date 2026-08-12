"""RentalOffer routes (PRD 3.9) — OCC on the production, negotiation cycle,
renter ownership, segregation of duties on settle."""

from flask import Blueprint

from db import store
from errors import (ApiError, ERR_INVALID_STATE, ERR_OFFER_NOT_ACTIONABLE,
                    ERR_PARTNER_KIND, ERR_RENTER_OWNERSHIP, ERR_ROUND_LIMIT,
                    ERR_SOD, ERR_STALE_VERSION, ERR_STANDING_NOT_GOOD,
                    ERR_TIME_RANGE, ERR_WINDOW_NOT_ENDED, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import MAX_NEGOTIATION_ROUNDS, compute_fee_schedule
from util import (json_body, new_record, parse_dt, req_int, req_str, to_public,
                  touch)

bp = Blueprint("rental_offers", __name__)


def _not_actionable(offer, action):
    return conflict(ERR_OFFER_NOT_ACTIONABLE,
                    f"Cannot {action} an offer in {offer['status']}")


@bp.post("/opera/rental-offers")
def create_offer():
    uid, _ = require_roles("ProductionManager")
    body = json_body()
    production_id = req_str(body, "production_id")
    renter_company_id = req_str(body, "renter_company_id")
    window_start = parse_dt(body.get("window_start"), "window_start")
    window_end = parse_dt(body.get("window_end"), "window_end")
    performances_count = req_int(body, "performances_count", min_value=1)
    per_fee = req_int(body, "per_performance_fee_cents", min_value=1)
    # OCC field is non-optional (PRD 2.7); missing or non-integer is a shape error.
    expected = req_int(body, "expected_production_version")
    # Pipeline step 5: time range.
    if window_end <= window_start:
        raise ApiError(ERR_TIME_RANGE, 400,
                       "window_end must be strictly after window_start")
    # Pipeline step 6: existence, declared input order.
    prod = get_or_404(store.productions, production_id, "Production")
    renter = get_or_404(store.partner_companies, renter_company_id, "PartnerCompany")
    # Pipeline step 7: optimistic concurrency on the production.
    if expected != prod["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_production_version does not match the "
                       "production's current version")
    # Pipeline step 10: renter kind.
    if renter["partner_kind"] != "RENTER":
        raise ApiError(ERR_PARTNER_KIND, 422,
                       "Rental offer requires a RENTER partner company")
    # Side effect: supersede any prior open offer to the same renter.
    for o in store.rental_offers.values():
        if (o["production_id"] == prod["id"]
                and o["renter_company_id"] == renter["id"]
                and o["status"] in ("SENT", "COUNTERED")):
            o["status"] = "SUPERSEDED"
            touch(o)
    rec = new_record(
        production_id=prod["id"],
        renter_company_id=renter["id"],
        window_start=window_start,
        window_end=window_end,
        performances_count=performances_count,
        per_performance_fee_cents=per_fee,
        fee_base_cents=None,
        surcharge_pct=None,
        total_fee_cents=None,
        countered_fee_cents=None,
        final_settlement_cents=None,
        negotiation_rounds=0,
        created_by_user_id=uid,
        status="DRAFT",
    )
    store.rental_offers[rec["id"]] = rec
    # Side effect (PRD 2.4): creating an offer bumps Production.version.
    touch(prod)
    return ok_object(to_public(rec), 201)


@bp.get("/opera/rental-offers")
def list_offers():
    require_roles("Any")
    return list_response(
        store.rental_offers.values(),
        [("production_id", "production_id"),
         ("renter_company_id", "renter_company_id"), ("status", "status")],
    )


@bp.get("/opera/rental-offers/<oid>")
def get_offer(oid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.rental_offers, oid, "RentalOffer")))


# --- ProductionManager actions ------------------------------------------------

@bp.post("/opera/rental-offers/<oid>/send")
def send_offer(oid):
    require_roles("ProductionManager")
    offer = get_or_404(store.rental_offers, oid, "RentalOffer")
    if offer["status"] != "DRAFT":
        raise _not_actionable(offer, "send")
    compute_fee_schedule(offer)
    offer["status"] = "SENT"
    touch(offer)
    return ok_object(to_public(offer))


@bp.post("/opera/rental-offers/<oid>/revise")
def revise_offer(oid):
    require_roles("ProductionManager")
    body = json_body()
    per_fee = req_int(body, "per_performance_fee_cents", min_value=1)
    offer = get_or_404(store.rental_offers, oid, "RentalOffer")
    if offer["status"] != "COUNTERED":
        raise _not_actionable(offer, "revise")
    offer["per_performance_fee_cents"] = per_fee
    offer["negotiation_rounds"] += 1
    compute_fee_schedule(offer)
    offer["status"] = "SENT"
    touch(offer)
    return ok_object(to_public(offer))


@bp.post("/opera/rental-offers/<oid>/withdraw")
def withdraw_offer(oid):
    require_roles("ProductionManager")
    offer = get_or_404(store.rental_offers, oid, "RentalOffer")
    if offer["status"] not in ("DRAFT", "SENT", "COUNTERED"):
        raise _not_actionable(offer, "withdraw")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return ok_object(to_public(offer))


@bp.post("/opera/rental-offers/<oid>/settle")
def settle_offer(oid):
    uid, _ = require_roles("ProductionManager")
    offer = get_or_404(store.rental_offers, oid, "RentalOffer")
    if offer["status"] != "ACCEPTED":
        raise _not_actionable(offer, "settle")
    # State-family gate (pipeline step 8) before the SoD rule (step 9).
    if not (store.clock >= offer["window_end"]):
        raise conflict(ERR_WINDOW_NOT_ENDED,
                       "The logical clock must have reached the offer's window_end")
    if uid == offer["created_by_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "Settle caller must differ from the offer creator")
    offer["final_settlement_cents"] = (
        offer["countered_fee_cents"] if offer["negotiation_rounds"] > 0
        else offer["total_fee_cents"])
    offer["status"] = "SETTLED"
    touch(offer)
    return ok_object(to_public(offer))


# --- PartnerRepresentative actions (entity-backed ownership, step 3) ---------

def _load_offer_and_check_ownership(oid, uid):
    offer = get_or_404(store.rental_offers, oid, "RentalOffer")
    if uid != offer["renter_company_id"]:
        raise ApiError(ERR_RENTER_OWNERSHIP, 403,
                       "X-User-ID must equal the offer's renter_company_id")
    return offer


@bp.post("/opera/rental-offers/<oid>/counter")
def counter_offer(oid):
    uid, _ = require_roles("PartnerRepresentative")
    offer = _load_offer_and_check_ownership(oid, uid)
    body = json_body()
    countered = req_int(body, "countered_fee_cents", min_value=1)
    if offer["status"] != "SENT":
        raise _not_actionable(offer, "counter")
    if offer["negotiation_rounds"] >= MAX_NEGOTIATION_ROUNDS:
        raise ApiError(ERR_ROUND_LIMIT, 422,
                       "Negotiation round limit reached")
    offer["countered_fee_cents"] = countered
    offer["status"] = "COUNTERED"
    touch(offer)
    return ok_object(to_public(offer))


@bp.post("/opera/rental-offers/<oid>/accept")
def accept_offer(oid):
    uid, _ = require_roles("PartnerRepresentative")
    offer = _load_offer_and_check_ownership(oid, uid)
    if offer["status"] != "SENT":
        raise _not_actionable(offer, "accept")
    renter = store.partner_companies[offer["renter_company_id"]]
    if renter["standing"] != "GOOD":
        raise conflict(ERR_STANDING_NOT_GOOD,
                       "Renter standing must be GOOD to accept an offer")
    offer["status"] = "ACCEPTED"
    touch(offer)
    return ok_object(to_public(offer))


@bp.post("/opera/rental-offers/<oid>/decline")
def decline_offer(oid):
    uid, _ = require_roles("PartnerRepresentative")
    offer = _load_offer_and_check_ownership(oid, uid)
    if offer["status"] not in ("SENT", "COUNTERED"):
        raise _not_actionable(offer, "decline")
    offer["status"] = "DECLINED"
    touch(offer)
    return ok_object(to_public(offer))
