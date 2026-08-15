from decimal import Decimal

from flask import Blueprint, request

from auth import parse_auth, require_role, check_ownership
from db import store
from envelope import ok, paginate
from errors import (not_found, conflict, ApiError, ERR_STALE_VERSION,
                    ERR_INVALID_STATE, ERR_MARKET_NOT_OPEN,
                    ERR_GENERATOR_NOT_AVAILABLE, ERR_PARTICIPANT_SUSPENDED,
                    ERR_DA_GATE_CLOSED, ERR_OFFER_MW_EXCEEDS,
                    ERR_CREDIT_HEADROOM)
from routes.operating_days import get_day
from routes.generators import get_generator
from util import (get_body, check_unknown, req_string, req_number, req_int,
                  new_record, serialize, sort_key, touch)
from services.credit import refresh_credit, offer_risk_cents

bp = Blueprint("offers", __name__)
TRADER = ["Trader"]


def get_offer(oid):
    o = store.offers.get(oid)
    if o is None:
        raise not_found("offer not found")
    return o


def _participant_of(offer):
    gen = store.generators[offer["generator_asset_id"]]
    return store.participants[gen["market_participant_id"]]


@bp.post("/market/operating-days/<operatingDayId>/offers")
def create_offer(operatingDayId):
    auth = parse_auth()
    require_role(auth, TRADER)
    body = get_body()
    check_unknown(body, {"generator_asset_id", "offered_mw",
                         "offer_price_cents_per_mwh", "expected_operating_day_version"})
    gen_id = req_string(body, "generator_asset_id")
    offered_mw = req_number(body, "offered_mw", minimum=Decimal(0), min_exclusive=True)
    price = req_int(body, "offer_price_cents_per_mwh")
    expected = req_int(body, "expected_operating_day_version")

    day = get_day(operatingDayId)
    gen = get_generator(gen_id)
    check_ownership(auth, gen["market_participant_id"])
    if expected != day["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_operating_day_version does not match the day version")
    if day["status"] != "DA_OPEN":
        raise conflict(ERR_MARKET_NOT_OPEN, "operating day is not DA_OPEN")
    if gen["status"] != "AVAILABLE":
        raise conflict(ERR_GENERATOR_NOT_AVAILABLE, "generator is not AVAILABLE")

    # supersede the incumbent live offer for this (generator, day) slot
    superseded_submitted = False
    for o in store.offers.values():
        if (o["generator_asset_id"] == gen["id"] and o["operating_day_id"] == day["id"]
                and o["status"] in ("DRAFT", "SUBMITTED")):
            if o["status"] == "SUBMITTED":
                superseded_submitted = True
            o["status"] = "SUPERSEDED"
            touch(o)

    rec = new_record()
    rec.update({
        "operating_day_id": day["id"],
        "generator_asset_id": gen["id"],
        "offered_mw": offered_mw,
        "offer_price_cents_per_mwh": price,
        "status": "DRAFT",
        "cleared_mw": Decimal(0),
        "da_lmp_cents_per_mwh": None,
    })
    store.offers[rec["id"]] = rec
    touch(day)  # offer creation bumps the day's version
    if superseded_submitted:
        refresh_credit(store.participants[gen["market_participant_id"]])
    return ok(serialize(rec), status=201)


@bp.post("/market/offers/<offerId>/submit")
def submit_offer(offerId):
    auth = parse_auth()
    require_role(auth, TRADER)
    offer = get_offer(offerId)
    gen = store.generators[offer["generator_asset_id"]]
    day = store.operating_days[offer["operating_day_id"]]
    participant = store.participants[gen["market_participant_id"]]
    check_ownership(auth, participant["id"])
    if offer["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE, "only a DRAFT offer can be submitted")
    if day["status"] != "DA_OPEN":
        raise conflict(ERR_MARKET_NOT_OPEN, "operating day is not DA_OPEN")
    if gen["status"] != "AVAILABLE":
        raise conflict(ERR_GENERATOR_NOT_AVAILABLE, "generator is not AVAILABLE")
    if participant["status"] == "SUSPENDED":
        raise conflict(ERR_PARTICIPANT_SUSPENDED, "owning participant is SUSPENDED")
    if store.clock_now > day["_gate_dt"]:  # exactly at gate close is accepted
        raise conflict(ERR_DA_GATE_CLOSED, "day-ahead gate has closed")
    if Decimal(offer["offered_mw"]) > Decimal(gen["availability_mw"]):
        raise conflict(ERR_OFFER_MW_EXCEEDS,
                       "offered_mw exceeds generator availability_mw")
    projected = participant["collateral_requirement_cents"] + offer_risk_cents(offer["offered_mw"])
    projected_effective = max(0, projected - participant["unsecured_allowance_cents"])
    if projected_effective > participant["posted_collateral_cents"]:
        raise conflict(ERR_CREDIT_HEADROOM,
                       "offer would push the effective requirement above posted collateral")
    offer["status"] = "SUBMITTED"
    touch(offer)
    refresh_credit(participant)
    return ok(serialize(offer))


@bp.post("/market/offers/<offerId>/withdraw")
def withdraw_offer(offerId):
    auth = parse_auth()
    require_role(auth, TRADER)
    offer = get_offer(offerId)
    gen = store.generators[offer["generator_asset_id"]]
    day = store.operating_days[offer["operating_day_id"]]
    participant = store.participants[gen["market_participant_id"]]
    check_ownership(auth, participant["id"])
    if offer["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE, "only a SUBMITTED offer can be withdrawn")
    if day["status"] != "DA_OPEN":
        raise conflict(ERR_MARKET_NOT_OPEN, "operating day is not DA_OPEN")
    offer["status"] = "DRAFT"
    touch(offer)
    refresh_credit(participant)
    return ok(serialize(offer))


@bp.get("/market/offers/<offerId>")
def get_one(offerId):
    parse_auth()
    return ok(serialize(get_offer(offerId)))


@bp.get("/market/offers")
def list_offers():
    parse_auth()
    rows = sorted(store.offers.values(), key=sort_key)
    day_id = request.args.get("operating_day_id")
    gen_id = request.args.get("generator_asset_id")
    status = request.args.get("status")
    if day_id is not None:
        rows = [r for r in rows if r["operating_day_id"] == day_id]
    if gen_id is not None:
        rows = [r for r in rows if r["generator_asset_id"] == gen_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])
