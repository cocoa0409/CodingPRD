"""Market offers: drafting, submission, clearing, revision and withdrawal
(PRD 3.3 and 3.4)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from numeric import D, rnd, f
from services import calc, core

bp = Blueprint("bids", __name__)

MARKET_TYPES = ("DAY_AHEAD", "REAL_TIME")
PRODUCTS = ("ENERGY", "REG_UP", "REG_DOWN", "SPIN")
DIRECTIONS = ("DISCHARGE", "CHARGE")
STATUSES = ("DRAFT", "SUBMITTED", "CLEARED", "UNCLEARED", "WITHDRAWN")
OUTCOMES = ("CLEARED", "UNCLEARED")

MAX_BID_REVISIONS = 3
RAMP_BUFFER = timedelta(minutes=15)
HALF_RATING_PRODUCTS = ("REG_UP", "REG_DOWN", "SPIN")


def _quarter_hour(dt, field):
    if dt.minute % 15 != 0 or dt.second != 0 or dt.microsecond != 0:
        raise errors.bad_request(
            "Field '%s' must fall on a whole quarter-hour." % field)


def _check_offer_mw(asset, product, offer_mw):
    """Validation 25 — the rating ceiling and the bidirectional ceiling."""
    ceiling = min(D(asset["power_rating_mw"]), D(asset["poi_mw_limit"]))
    if D(offer_mw) > ceiling:
        raise ApiError(errors.ERR_OFFER_MW_EXCEEDS_RATING, 422,
                       "offer_mw exceeds the asset's power rating or "
                       "interconnection limit.")
    if product in HALF_RATING_PRODUCTS:
        half = D(asset["power_rating_mw"]) / Decimal("2")
        if D(offer_mw) > half:
            raise ApiError(errors.ERR_OFFER_MW_EXCEEDS_RATING, 422,
                           "offer_mw exceeds half of the asset's power rating "
                           "for a regulation or reserve product.")


def _price_bid(bid, asset):
    start = db.parse_dt(bid["delivery_start"])
    end = db.parse_dt(bid["delivery_end"])
    bid["expected_energy_mwh"] = calc.expected_energy(bid["offer_mw"], start, end)
    bid["cycle_debit_efc"] = calc.cycle_debit(bid["expected_energy_mwh"],
                                              asset["available_energy_mwh"])
    bid["offer_price_usd_per_mwh"] = calc.offer_price(
        asset, bid["product"], bid["direction"], bid["price_adder_usd_per_mwh"])


@bp.post("/market-bids")
def draft_bid():
    middleware.authorize("MarketTrader")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    reservation_id = v.ident(body, "reservation_id")
    market_type = v.enum(body, "market_type", MARKET_TYPES)
    product = v.enum(body, "product", PRODUCTS)
    direction = v.enum(body, "direction", DIRECTIONS)
    start_raw, start = v.timestamp(body, "delivery_start")
    end_raw, end = v.timestamp(body, "delivery_end")
    offer_mw = v.num(body, "offer_mw", gt=0)
    price_adder = v.num(body, "price_adder_usd_per_mwh", required=False,
                        default=0.0, ge=0)
    if not end > start:
        raise errors.bad_request(
            "Field 'delivery_end' must be strictly later than 'delivery_start'.")
    _quarter_hour(start, "delivery_start")
    _quarter_hour(end, "delivery_end")

    asset = core.get_asset(asset_id)
    reservation = core.get_reservation(reservation_id)
    if reservation["asset_id"] != asset_id:
        raise ApiError(errors.ERR_ASSET_SCOPE_MISMATCH, 409,
                       "The reservation belongs to a different asset.")
    if reservation["status"] != "HELD":
        raise ApiError(errors.ERR_RESERVATION_NOT_HELD, 409,
                       "The backing reservation is not HELD.")
    core.gate_lockout(asset)
    core.gate_market_available(asset)
    _check_offer_mw(asset, product, offer_mw)

    bid = db.new_row()
    bid.update({
        "asset_id": asset_id,
        "reservation_id": reservation_id,
        "market_type": market_type,
        "product": product,
        "direction": direction,
        "delivery_start": start_raw,
        "delivery_end": end_raw,
        "offer_mw": offer_mw,
        "price_adder_usd_per_mwh": price_adder,
        "offer_price_usd_per_mwh": 0.0,
        "expected_energy_mwh": 0.0,
        "cycle_debit_efc": 0.0,
        "status": "DRAFT",
        "revision_count": 0,
        "cleared_price_usd_per_mwh": None,
        "cleared_mw": None,
        "withdrawn_reason": None,
        "submitted_by_user_id": None,
    })
    _price_bid(bid, asset)
    db.bids[bid["id"]] = bid
    return response.created(db.serialize(bid))


@bp.get("/market-bids/<bid_id>")
def read_bid(bid_id):
    middleware.any_role()
    return response.ok(db.serialize(core.get_bid(bid_id)))


@bp.get("/market-bids")
def list_bids():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    reservation_id = v.query_str("reservation_id")
    status = v.query_enum("status", STATUSES)
    market_type = v.query_enum("market_type", MARKET_TYPES)
    product = v.query_enum("product", PRODUCTS)

    rows = list(db.bids.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if reservation_id is not None:
        rows = [r for r in rows if r["reservation_id"] == reservation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if market_type is not None:
        rows = [r for r in rows if r["market_type"] == market_type]
    if product is not None:
        rows = [r for r in rows if r["product"] == product]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/market-bids/<bid_id>/submit")
def submit_bid(bid_id):
    user_id, _role = middleware.authorize("MarketTrader")
    bid = core.get_bid(bid_id)
    asset = core.get_asset(bid["asset_id"])
    reservation = core.reservation_of_bid(bid)

    if bid["status"] != "DRAFT":
        raise ApiError(errors.ERR_BID_NOT_DRAFT, 409, "The offer is not a DRAFT.")
    if reservation is None or reservation["status"] != "HELD":
        raise ApiError(errors.ERR_RESERVATION_NOT_HELD, 409,
                       "The backing reservation is not HELD.")

    core.gate_lockout(asset)
    core.gate_market_available(asset)
    core.gate_derate(asset, bid["offer_mw"])

    delivery_start = db.parse_dt(bid["delivery_start"])
    delivery_end = db.parse_dt(bid["delivery_end"])
    window_start = db.parse_dt(reservation["window_start"])
    window_end = db.parse_dt(reservation["window_end"])
    if not (window_start <= delivery_start and window_end > delivery_end):
        raise ApiError(errors.ERR_RESERVATION_WINDOW_MISMATCH, 422,
                       "The reservation window does not cover the delivery "
                       "interval.")

    # validation 21 — window exclusivity under the ramp buffer
    buffered_start = delivery_start - RAMP_BUFFER
    buffered_end = delivery_end + RAMP_BUFFER
    for other in core.bids_of_asset(asset["id"]):
        if other["id"] == bid["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "CLEARED"):
            continue
        if other["market_type"] != bid["market_type"]:
            continue
        other_start = db.parse_dt(other["delivery_start"])
        other_end = db.parse_dt(other["delivery_end"])
        if buffered_start <= other_end and other_start <= buffered_end:
            raise ApiError(errors.ERR_BID_WINDOW_CONFLICT, 409,
                           "Another live offer already occupies this delivery "
                           "window under the ramp buffer.")

    # validation 31 — the annual equivalent-full-cycle ceiling
    debit = calc.cycle_debit(bid["expected_energy_mwh"],
                            asset["available_energy_mwh"])
    projected_cycles = rnd(D(asset["equivalent_full_cycles_ytd"]) + D(debit), 4)
    if projected_cycles > D(asset["cycle_limit_per_year"]):
        raise ApiError(errors.ERR_CYCLE_LIMIT_EXCEEDED, 409,
                       "Submitting the offer would breach the annual "
                       "equivalent-full-cycle ceiling.")

    # validation 32 — the lifetime warranty throughput ceiling
    projected_throughput = rnd(D(asset["cumulative_throughput_mwh"])
                               + D(bid["expected_energy_mwh"]), 3)
    if projected_throughput > D(asset["warranty_throughput_limit_mwh"]):
        raise ApiError(errors.ERR_THROUGHPUT_LIMIT_EXCEEDED, 409,
                       "Submitting the offer would breach the lifetime "
                       "warranty throughput ceiling.")

    bid["status"] = "SUBMITTED"
    bid["submitted_by_user_id"] = user_id
    db.touch(bid)
    return response.ok(db.serialize(bid))


@bp.post("/market-bids/<bid_id>/clearing-result")
def clearing_result(bid_id):
    middleware.authorize("MarketOperator")
    body = v.json_body()
    outcome = v.enum(body, "outcome", OUTCOMES)
    if outcome == "CLEARED":
        cleared_price = v.num(body, "cleared_price_usd_per_mwh", ge=0)
        cleared_mw = v.num(body, "cleared_mw", gt=0)
    else:
        if v.present(body, "cleared_price_usd_per_mwh") or v.present(body, "cleared_mw"):
            raise errors.bad_request(
                "An UNCLEARED outcome must not carry cleared_price_usd_per_mwh "
                "or cleared_mw.")
        cleared_price = None
        cleared_mw = None

    bid = core.get_bid(bid_id)
    asset = core.get_asset(bid["asset_id"])

    if outcome == "CLEARED" and D(cleared_mw) > D(bid["offer_mw"]):
        raise errors.bad_request("cleared_mw must not exceed offer_mw.")

    if bid["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_BID_NOT_SUBMITTED, 409,
                       "The offer is not SUBMITTED.")
    core.gate_market_available(asset)

    if outcome == "CLEARED":
        if D(cleared_price) < D(bid["offer_price_usd_per_mwh"]):
            raise ApiError(errors.ERR_CLEARING_PRICE_BELOW_FLOOR, 422,
                           "The clearing price is below the offer's floor.")
        bid["cleared_price_usd_per_mwh"] = cleared_price
        bid["cleared_mw"] = cleared_mw
        bid["status"] = "CLEARED"
    else:
        bid["status"] = "UNCLEARED"
    db.touch(bid)
    return response.ok(db.serialize(bid))


@bp.post("/market-bids/<bid_id>/revise")
def revise_bid(bid_id):
    middleware.authorize("MarketTrader")
    body = v.json_body()
    new_offer_mw = v.num(body, "offer_mw", required=False, default=None, gt=0)
    new_adder = v.num(body, "price_adder_usd_per_mwh", required=False,
                      default=None, ge=0)
    if new_offer_mw is None and new_adder is None:
        raise errors.bad_request(
            "A revision must supply offer_mw or price_adder_usd_per_mwh.")

    bid = core.get_bid(bid_id)
    asset = core.get_asset(bid["asset_id"])
    reservation = core.reservation_of_bid(bid)

    if bid["status"] != "UNCLEARED":
        raise ApiError(errors.ERR_BID_NOT_SUBMITTED, 409,
                       "Only an UNCLEARED offer may be revised.")
    if reservation is None or reservation["status"] != "HELD":
        raise ApiError(errors.ERR_RESERVATION_NOT_HELD, 409,
                       "The backing reservation is not HELD.")
    core.gate_lockout(asset)
    core.gate_market_available(asset)

    effective_mw = bid["offer_mw"] if new_offer_mw is None else new_offer_mw
    _check_offer_mw(asset, bid["product"], effective_mw)

    if bid["revision_count"] >= MAX_BID_REVISIONS:
        raise ApiError(errors.ERR_REVISION_LIMIT_REACHED, 409,
                       "The offer has exhausted its revision allowance.")

    if new_offer_mw is not None:
        bid["offer_mw"] = new_offer_mw
    if new_adder is not None:
        bid["price_adder_usd_per_mwh"] = new_adder
    bid["revision_count"] = bid["revision_count"] + 1
    bid["submitted_by_user_id"] = None
    bid["status"] = "DRAFT"
    _price_bid(bid, asset)
    db.touch(bid)
    return response.ok(db.serialize(bid))


@bp.post("/market-bids/<bid_id>/withdraw")
def withdraw_bid(bid_id):
    middleware.authorize("MarketTrader")
    bid = core.get_bid(bid_id)
    asset = core.get_asset(bid["asset_id"])

    if bid["status"] not in ("DRAFT", "SUBMITTED", "CLEARED"):
        raise ApiError(errors.ERR_BID_NOT_DRAFT, 409,
                       "The offer cannot be withdrawn from its current status.")
    if bid["status"] == "SUBMITTED":
        core.gate_lockout(asset)

    instructions = core.dispatches_of_bid(bid["id"])
    if bid["status"] == "CLEARED":
        taken_up = [d for d in instructions
                    if d["execution_status"] in ("ACCEPTED", "EXECUTING", "COMPLETED")]
        if taken_up:
            raise ApiError(errors.ERR_DISPATCH_NOT_PENDING, 409,
                           "The delivery has already been taken up by the "
                           "control room.")

    was_cleared = bid["status"] == "CLEARED"
    bid["status"] = "WITHDRAWN"
    bid["withdrawn_reason"] = "TRADER_WITHDRAWAL"
    db.touch(bid)

    released = False
    reservation = core.reservation_of_bid(bid)
    if reservation is not None and reservation["status"] == "HELD":
        reservation["status"] = "RELEASED"
        reservation["released_reason"] = "BID_WITHDRAWN"
        db.touch(reservation)
        released = True

    if was_cleared:
        pending = [d for d in instructions if d["execution_status"] == "PENDING"]
        for instruction in core.by_setpoint_start(pending):
            instruction["execution_status"] = "FAILED"
            instruction["failure_reason"] = "DELIVERY_VOIDED"
            db.touch(instruction)

    if released:
        core.recompute_pool(asset)
        db.touch(asset)
    return response.ok(db.serialize(bid))
