"""Reserves, live bidding, lot close and the settlement preview (PRD §3.5–§3.7)."""

from flask import Blueprint

import calc
import db
import serial
import services
import validate as v
from auth import authenticate, require_owner
from db import ordered, store, touch
from errors import ApiError
from util import ok, ok_list, plus_seconds
from helpers import find

bp = Blueprint("lots", __name__)


@bp.patch("/auction-lots/<rec_id>/reserve-price")
def revise_reserve(rec_id):
    authenticate(("AuctionOps",))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = v.body()
    reserve = v.req_int(data, "reserve_price_cents", minimum=1)
    expected_version = v.req_int(data, "expected_auction_lot_version")
    if lot["current_high_bid_cents"] != 0:
        raise ApiError("ERR_LOT_HAS_BIDS")
    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION")
    if reserve < lot["opening_bid_cents"]:
        raise ApiError("ERR_RESERVE_BELOW_OPENING")

    lot["reserve_price_cents"] = reserve
    touch(lot)
    return ok(serial.dump("auction_lot", lot))


@bp.post("/auction-lots/<rec_id>/bids")
def place_bid(rec_id):
    user_id, _role = authenticate(("Bidder",))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    data = v.body()

    raw_bidder_id = v.raw_str(data, "bidder_id")
    bidder = None
    if raw_bidder_id is not None:
        require_owner(user_id, raw_bidder_id)
        bidder = store.bidders.get(raw_bidder_id)
        if bidder is None:
            raise ApiError("ERR_BIDDER_NOT_FOUND")
    amount = v.req_int(data, "amount_cents", minimum=1)
    if bidder is None:
        v.bad("Field 'bidder_id' is required.")

    event = store.auction_events.get(lot["auction_event_id"])
    if event is None or event["event_status"] != "LIVE":
        raise ApiError("ERR_EVENT_NOT_LIVE")
    if lot["lot_status"] not in ("OPEN", "EXTENDED"):
        raise ApiError("ERR_LOT_NOT_OPEN")
    if bidder["registration_status"] == "SUSPENDED":
        raise ApiError("ERR_BIDDER_NOT_REGISTERED")
    if bidder["identity_verification_status"] != "VERIFIED":
        raise ApiError("ERR_IDENTITY_UNVERIFIED")
    if bidder["registration_status"] == "BARRED":
        raise ApiError("ERR_BIDDER_BARRED")
    if services.is_excluded_now(bidder["id"], event["county_code"]):
        raise ApiError("ERR_BIDDER_EXCLUDED")

    clock = db.now()
    if clock >= lot["bid_close_at"]:
        raise ApiError("ERR_BID_WINDOW_CLOSED")
    if lot["current_high_bid_cents"] == 0:
        minimum = lot["opening_bid_cents"]
    else:
        minimum = lot["current_high_bid_cents"] + lot["min_increment_cents"]
    if amount < minimum:
        raise ApiError("ERR_BID_BELOW_MINIMUM")

    existing_hold = services.live_hold(bidder["id"], lot["id"])
    if existing_hold is None and bidder["deposit_available_cents"] < lot["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_INSUFFICIENT")

    # --- acceptance (PRD §3.5) ------------------------------------------- #
    affected = set()
    standing = services.active_bid_of_lot(lot["id"])
    if standing is not None:
        standing["bid_status"] = "OUTBID"
        touch(standing)
        displaced_hold = services.live_hold(standing["bidder_id"], lot["id"])
        if displaced_hold is not None and standing["bidder_id"] != bidder["id"]:
            services.release_hold(displaced_hold, "OUTBID")
            affected.add(standing["bidder_id"])

    remaining = (lot["bid_close_at"] - clock).total_seconds()
    triggered = (remaining <= calc.EXTENSION_TRIGGER_SECONDS
                 and lot["extension_count"] < calc.MAX_EXTENSIONS_PER_LOT)
    if triggered:
        lot["bid_close_at"] = plus_seconds(clock, calc.EXTENSION_SECONDS)
        lot["extension_count"] = lot["extension_count"] + 1
        lot["lot_status"] = "EXTENDED"

    bid = db.new_record(
        auction_lot_id=lot["id"],
        bidder_id=bidder["id"],
        amount_cents=amount,
        placed_at=clock,
        bid_status="ACTIVE",
        is_above_reserve=amount >= lot["reserve_price_cents"],
        triggered_extension=triggered,
    )
    store.bids[bid["id"]] = bid

    if existing_hold is None:
        services.create_hold(bidder["id"], lot)
    affected.add(bidder["id"])

    lot["current_high_bid_cents"] = amount
    touch(lot)
    services.refresh_bidders(affected)
    return ok(serial.dump("bid", bid), 201)


@bp.post("/auction-lots/<rec_id>/close")
def close_lot(rec_id):
    user_id, _role = authenticate(("AuctionOps",))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    v.body()
    event = store.auction_events.get(lot["auction_event_id"])
    if event is None or event["event_status"] != "LIVE":
        raise ApiError("ERR_EVENT_NOT_LIVE")
    if lot["lot_status"] not in ("OPEN", "EXTENDED"):
        raise ApiError("ERR_LOT_NOT_OPEN")
    if db.now() < lot["bid_close_at"]:
        raise ApiError("ERR_LOT_WINDOW_STILL_OPEN")

    asset = store.asset_listings.get(lot["asset_listing_id"])
    candidates = services.winning_bid_candidates(lot)
    lot["closed_by_user_id"] = user_id
    lot["closed_at"] = db.now()

    if candidates:
        winner = candidates[0]
        winner["bid_status"] = "WINNING"
        touch(winner)
        lot["hammer_price_cents"] = winner["amount_cents"]
        lot["provisional_buyer_premium_cents"] = calc.buyer_premium(
            winner["amount_cents"], asset["occupancy_status"], asset["title_condition"])
        lot["lot_status"] = "CLOSED_SOLD"
        touch(lot)

        changed = False
        if asset["listing_status"] == "LISTED":
            asset["listing_status"] = "SOLD_PENDING_CONTRACT"
            changed = True
        changed = services.recompute_second_chance_eligible(asset, lot) or changed
        if changed:
            touch(asset)

        if event["trustee_sale_id"] is not None:
            sale = store.trustee_sales.get(event["trustee_sale_id"])
            if sale is not None and sale["status"] == "CONFIRMED":
                sale["status"] = "HELD"
                touch(sale)
    else:
        lot["lot_status"] = "CLOSED_NO_SALE"
        touch(lot)
        affected = set()
        for hold in services.holds_of_lot(lot["id"]):
            if hold["status"] in calc.HOLD_ENCUMBERED:
                services.release_hold(hold, "NO_SALE")
                affected.add(hold["bidder_id"])
        services.refresh_bidders(affected)
        if asset["listing_status"] == "LISTED":
            asset["listing_status"] = "UNSOLD"
            touch(asset)

    services.bubble_up_event_close(event)
    return ok(serial.dump("auction_lot", lot))


@bp.get("/auction-lots/<rec_id>")
def get_lot(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Seller", "Bidder", "Anonymous"))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    return ok(serial.dump("auction_lot", lot))


@bp.get("/auction-lots")
def list_lots():
    authenticate(("PlatformAdmin", "AuctionOps", "Trustee", "Seller", "Bidder", "Anonymous"))
    limit, offset = v.pagination()
    event_id = v.query_str("auction_event_id")
    asset_id = v.query_str("asset_listing_id")
    status = v.query_enum("lot_status", calc.LOT_STATUS)
    items = ordered(store.auction_lots.values())
    if event_id is not None:
        items = [l for l in items if l["auction_event_id"] == event_id]
    if asset_id is not None:
        items = [l for l in items if l["asset_listing_id"] == asset_id]
    if status is not None:
        items = [l for l in items if l["lot_status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("auction_lot", v.page(items, limit, offset)),
                   limit, offset, total)


@bp.get("/auction-lots/<rec_id>/sale-contracts")
def list_lot_contracts(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Seller", "Bidder"))
    find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    limit, offset = v.pagination()
    status = v.query_enum("contract_status", calc.CONTRACT_STATUS)
    items = [c for c in ordered(store.sale_contracts.values())
             if c["auction_lot_id"] == rec_id]
    if status is not None:
        items = [c for c in items if c["contract_status"] == status]
    total = len(items)
    return ok_list(serial.dump_many("sale_contract", v.page(items, limit, offset)),
                   limit, offset, total)


@bp.get("/auction-lots/<rec_id>/settlement-preview")
def settlement_preview(rec_id):
    authenticate(("PlatformAdmin", "AuctionOps", "Seller"))
    lot = find(store.auction_lots, rec_id, "ERR_AUCTION_LOT_NOT_FOUND")
    hammer = lot["hammer_price_cents"]
    data = {
        "auction_lot_id": lot["id"],
        "hammer_price_cents": 0,
        "contract_price_cents": 0,
        "provisional_premium_cents": 0,
        "final_premium_cents": 0,
        "premium_variant_delta_cents": 0,
        "doc_fee_cents": 0,
        "total_due_cents": 0,
        "settlement_gross_cents": 0,
        "seller_net_cents": 0,
        "platform_fee_cents": 0,
    }
    if hammer <= 0:
        return ok(data)

    asset = store.asset_listings.get(lot["asset_listing_id"])
    seller = store.sellers.get(asset["seller_id"]) if asset is not None else None
    event = store.auction_events.get(lot["auction_event_id"])
    postponements = 0
    if event is not None and event["trustee_sale_id"] is not None:
        sale = store.trustee_sales.get(event["trustee_sale_id"])
        if sale is not None:
            postponements = sale["postponement_count"]

    contract_price = calc.contract_price(hammer, postponements)
    provisional = lot["provisional_buyer_premium_cents"]
    final = calc.buyer_premium(contract_price, asset["occupancy_status"],
                               asset["title_condition"])
    doc_fee, total_due = calc.doc_fee_and_total_due(contract_price, final)
    split = calc.settlement_split(
        contract_price,
        seller["default_commission_bps"] if seller is not None else 0,
        asset["title_condition"],
        final,
    )
    data.update({
        "hammer_price_cents": hammer,
        "contract_price_cents": contract_price,
        "provisional_premium_cents": provisional,
        "final_premium_cents": final,
        "premium_variant_delta_cents": final - provisional,
        "doc_fee_cents": doc_fee,
        "total_due_cents": total_due,
        "settlement_gross_cents": split["settlement_gross_cents"],
        "seller_net_cents": split["seller_net_cents"],
        "platform_fee_cents": split["platform_fee_cents"],
    })
    return ok(data)
