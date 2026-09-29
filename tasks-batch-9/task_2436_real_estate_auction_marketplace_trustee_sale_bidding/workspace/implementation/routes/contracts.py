"""Contract execution, settlement, escrow close, fallout and second chances."""

from flask import Blueprint

import calc
import db
import serial
import services
import validate as v
from auth import authenticate, require_owner
from db import ordered, store, touch
from errors import ApiError
from helpers import find
from util import ok, ok_list, plus_days

bp = Blueprint("contracts", __name__)


# --------------------------------------------------------------------------- #
# execution (PRD §3.7)
# --------------------------------------------------------------------------- #

@bp.post("/auction-lots/<rec_id>/sale-contract")
def execute_contract(rec_id):
    user_id, _role = authenticate(("AuctionOps",))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = v.body()
    closing_window_days = v.opt_int(data, "closing_window_days", default=21,
                                   minimum=1, maximum=90)
    if lot["lot_status"] != "CLOSED_SOLD":
        raise ApiError("ERR_LOT_NOT_CLOSED_SOLD")
    if lot["closed_by_user_id"] is not None and user_id == lot["closed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    asset = store.asset_listings.get(lot["asset_listing_id"])
    if asset["title_clearance_status"] == "PENDING":
        raise ApiError("ERR_TITLE_CLEARANCE_PENDING")
    if asset["title_clearance_status"] == "DEFECTIVE":
        raise ApiError("ERR_TITLE_DEFECTIVE")

    event = store.auction_events.get(lot["auction_event_id"])
    sale = None
    postponements = 0
    if event is not None and event["trustee_sale_id"] is not None:
        sale = store.trustee_sales.get(event["trustee_sale_id"])
        if sale is not None:
            postponements = sale["postponement_count"]

    winning_bid = services.winning_bid_of_lot(lot["id"])
    seller = store.sellers.get(asset["seller_id"])
    execution_at = db.now()
    closing_deadline_at = plus_days(execution_at, closing_window_days)

    contract_price = calc.contract_price(lot["hammer_price_cents"], postponements)
    final_premium = calc.buyer_premium(contract_price, asset["occupancy_status"],
                                      asset["title_condition"])
    doc_fee, total_due = calc.doc_fee_and_total_due(contract_price, final_premium)
    split = calc.settlement_split(
        contract_price,
        seller["default_commission_bps"] if seller is not None else 0,
        asset["title_condition"],
        final_premium,
    )

    contract = db.new_record(
        auction_lot_id=lot["id"],
        winning_bidder_id=winning_bid["bidder_id"] if winning_bid is not None else None,
        contract_price_cents=contract_price,
        final_buyer_premium_cents=final_premium,
        doc_fee_cents=doc_fee,
        total_due_cents=total_due,
        closing_window_days=closing_window_days,
        closing_deadline_at=closing_deadline_at,
        contract_status="EXECUTED",
        execution_at=execution_at,
        executed_by_user_id=user_id,
        settlement_status="POSTED",
        settlement_gross_cents=split["settlement_gross_cents"],
        seller_net_cents=split["seller_net_cents"],
        platform_fee_cents=split["platform_fee_cents"],
        buyer_premium_cents=split["buyer_premium_cents"],
        forfeited_deposit_cents=0,
        forfeiture_seller_net_cents=0,
        forfeiture_platform_fee_cents=0,
        fallout_reason=None,
        closing_reference=None,
        closed_at=None,
        fallout_at=None,
    )
    store.sale_contracts[contract["id"]] = contract

    if seller is not None:
        seller["settled_net_cents"] = seller["settled_net_cents"] + split["seller_net_cents"]
        touch(seller)

    if winning_bid is not None:
        hold = services.live_hold(winning_bid["bidder_id"], lot["id"])
        if hold is not None:
            hold["status"] = "EXTENDED"
            hold["expires_at"] = closing_deadline_at
            touch(hold)
    return ok(serial.dump("sale_contract", contract), 201)


@bp.post("/sale-contracts/<rec_id>/close")
def close_contract(rec_id):
    authenticate(("AuctionOps",))
    contract = find(store.sale_contracts, rec_id, "ERR_SALE_CONTRACT_NOT_FOUND")
    data = v.body()
    reference = v.req_str(data, "closing_reference")
    if contract["contract_status"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED")
    if db.now() > contract["closing_deadline_at"]:
        raise ApiError("ERR_CLOSING_DEADLINE_PASSED")

    contract["contract_status"] = "CLOSED"
    contract["closing_reference"] = reference
    contract["closed_at"] = db.now()
    touch(contract)

    lot = store.auction_lots.get(contract["auction_lot_id"])
    if lot is not None:
        hold = services.live_hold(contract["winning_bidder_id"], lot["id"])
        if hold is not None:
            services.release_hold(hold, "CONTRACT_CLOSED")
            bidder = store.bidders.get(contract["winning_bidder_id"])
            if bidder is not None:
                services.refresh_bidder(bidder)
        asset = store.asset_listings.get(lot["asset_listing_id"])
        if asset is not None and asset["listing_status"] == "SOLD_PENDING_CONTRACT":
            asset["listing_status"] = "SOLD_CLOSED"
            touch(asset)
    return ok(serial.dump("sale_contract", contract))


@bp.post("/sale-contracts/<rec_id>/fallout")
def fallout_contract(rec_id):
    authenticate(("AuctionOps",))
    contract = find(store.sale_contracts, rec_id, "ERR_SALE_CONTRACT_NOT_FOUND")
    data = v.body()
    reason = v.req_str(data, "fallout_reason")
    if contract["contract_status"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED")

    contract["contract_status"] = "FALLOUT"
    contract["fallout_at"] = db.now()
    contract["fallout_reason"] = reason
    contract["settlement_status"] = "VOID"

    lot = store.auction_lots.get(contract["auction_lot_id"])
    asset = store.asset_listings.get(lot["asset_listing_id"]) if lot is not None else None
    seller = store.sellers.get(asset["seller_id"]) if asset is not None else None
    bidder = store.bidders.get(contract["winning_bidder_id"])

    seller_delta = -contract["seller_net_cents"]

    forfeited = 0
    if lot is not None and bidder is not None:
        hold = services.live_hold(bidder["id"], lot["id"])
        if hold is not None:
            hold["status"] = "CAPTURED"
            hold["released_reason"] = "FORFEITED"
            touch(hold)
            forfeited = hold["amount_cents"]
    contract["forfeited_deposit_cents"] = forfeited
    seller_share, platform_share = calc.forfeiture_split(forfeited)
    contract["forfeiture_seller_net_cents"] = seller_share
    contract["forfeiture_platform_fee_cents"] = platform_share
    seller_delta += seller_share
    touch(contract)

    if seller is not None:
        seller["settled_net_cents"] = seller["settled_net_cents"] + seller_delta
        touch(seller)

    if bidder is not None:
        bidder["fallout_count"] = bidder["fallout_count"] + 1
        services.bar_bidder_if_needed(bidder)
        services.refresh_bidder(bidder, force=True, with_score=True)

    if asset is not None:
        changed = False
        if asset["listing_status"] == "SOLD_PENDING_CONTRACT":
            asset["listing_status"] = "RELIST_PENDING"
            changed = True
        if lot is not None:
            changed = services.recompute_second_chance_eligible(asset, lot) or changed
        if changed:
            touch(asset)
    return ok(serial.dump("sale_contract", contract))


@bp.get("/sale-contracts/<rec_id>")
def get_contract(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Seller", "Bidder"))
    contract = find(store.sale_contracts, rec_id, "ERR_SALE_CONTRACT_NOT_FOUND")
    return ok(serial.dump("sale_contract", contract))


# --------------------------------------------------------------------------- #
# second-chance offers (PRD §3.8)
# --------------------------------------------------------------------------- #

@bp.post("/auction-lots/<rec_id>/second-chance-offers")
def create_offer(rec_id):
    authenticate(("AuctionOps",))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = v.body()
    expires_at = v.opt_dt(data, "expires_at")
    if lot["lot_status"] != "CLOSED_SOLD":
        raise ApiError("ERR_LOT_NOT_CLOSED_SOLD")
    candidates = services.backup_bid_candidates(lot)
    if not candidates:
        raise ApiError("ERR_NO_BACKUP_BIDDER")
    for other in store.offers.values():
        if other["auction_lot_id"] == lot["id"] and other["status"] == "OUTSTANDING":
            raise ApiError("ERR_DUPLICATE_ACTIVE_OFFER")

    bid, bidder = candidates[0]
    if expires_at is None:
        expires_at = plus_days(db.now(), calc.OFFER_WINDOW_DAYS)
    offer = db.new_record(
        auction_lot_id=lot["id"],
        offered_bidder_id=bidder["id"],
        offer_price_cents=bid["amount_cents"],
        expires_at=expires_at,
        status="OUTSTANDING",
        responded_at=None,
    )
    store.offers[offer["id"]] = offer
    return ok(serial.dump("offer", offer), 201)


@bp.post("/second-chance-offers/<rec_id>/respond")
def respond_offer(rec_id):
    user_id, _role = authenticate(("Bidder",))
    offer = find(store.offers, rec_id, "ERR_OFFER_NOT_FOUND")
    require_owner(user_id, offer["offered_bidder_id"])
    data = v.body()
    decision = v.req_enum(data, "decision", calc.OFFER_DECISIONS)

    bidder = store.bidders.get(offer["offered_bidder_id"])
    if bidder is None:
        raise ApiError("ERR_BIDDER_NOT_FOUND")
    lot = store.auction_lots.get(offer["auction_lot_id"])
    event = store.auction_events.get(lot["auction_event_id"]) if lot is not None else None

    if bidder["registration_status"] == "SUSPENDED":
        raise ApiError("ERR_BIDDER_NOT_REGISTERED")
    if offer["status"] != "OUTSTANDING":
        raise ApiError("ERR_OFFER_NOT_OUTSTANDING")
    if bidder["identity_verification_status"] != "VERIFIED":
        raise ApiError("ERR_IDENTITY_UNVERIFIED")
    county = event["county_code"] if event is not None else None
    if services.is_excluded_now(bidder["id"], county):
        raise ApiError("ERR_BIDDER_EXCLUDED")
    if db.now() > offer["expires_at"]:
        offer["status"] = "EXPIRED"
        touch(offer)
        raise ApiError("ERR_OFFER_EXPIRED")
    existing_hold = services.live_hold(bidder["id"], lot["id"]) if lot is not None else None
    if existing_hold is None and lot is not None and \
            bidder["deposit_available_cents"] < lot["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT")

    offer["status"] = "ACCEPTED" if decision == "ACCEPTED" else "DECLINED"
    offer["responded_at"] = db.now()
    touch(offer)

    asset = store.asset_listings.get(lot["asset_listing_id"]) if lot is not None else None

    if decision == "ACCEPTED":
        services.create_hold(bidder["id"], lot)
        services.refresh_bidder(bidder)

        previous = services.winning_bid_of_lot(lot["id"])
        if previous is not None:
            previous["bid_status"] = "OUTBID"
            touch(previous)
        promoted = _bid_to_promote(lot, bidder["id"])
        if promoted is not None:
            promoted["bid_status"] = "WINNING"
            touch(promoted)

        lot["hammer_price_cents"] = offer["offer_price_cents"]
        services.recompute_provisional_premium(lot)
        touch(lot)

        if asset is not None:
            if asset["listing_status"] == "RELIST_PENDING":
                asset["listing_status"] = "SOLD_PENDING_CONTRACT"
            asset["second_chance_eligible"] = False
            touch(asset)
    else:
        if asset is not None and asset["second_chance_eligible"]:
            asset["second_chance_eligible"] = False
            touch(asset)
    return ok(serial.dump("offer", offer))


def _bid_to_promote(lot, bidder_id):
    """The accepting bidder's own highest bid on the lot becomes WINNING."""
    own = [b for b in services.bids_of_lot(lot["id"])
           if b["bidder_id"] == bidder_id and b["bid_status"] == "OUTBID"]
    if not own:
        own = [b for b in services.bids_of_lot(lot["id"])
               if b["bidder_id"] == bidder_id and b["bid_status"] != "WINNING"]
    if not own:
        return None
    own.sort(key=lambda b: (-b["amount_cents"], b["created_at"], b["_seq"]))
    return own[0]


@bp.get("/second-chance-offers/<rec_id>")
def get_offer(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Bidder"))
    offer = find(store.offers, rec_id, "ERR_OFFER_NOT_FOUND")
    return ok(serial.dump("offer", offer))


@bp.get("/second-chance-offers")
def list_offers():
    authenticate(("PlatformAdmin", "AuctionOps", "Bidder"))
    limit, offset = v.pagination()
    lot_id = v.query_str("auction_lot_id")
    bidder_id = v.query_str("offered_bidder_id")
    status = v.query_enum("status", calc.OFFER_STATUS)
    items = ordered(store.offers.values())
    if lot_id is not None:
        items = [o for o in items if o["auction_lot_id"] == lot_id]
    if bidder_id is not None:
        items = [o for o in items if o["offered_bidder_id"] == bidder_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("offer", v.page(items, limit, offset)),
                   limit, offset, total)
