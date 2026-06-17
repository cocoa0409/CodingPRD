"""RunListEntry (lot) lifecycle + bidding (PRD §3.4, §3.5, §3.6)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import (
    base_record, touch, get_body, require_str, require_int, require_enum,
    optional_int, public, list_collection,
)
from services import lookup, cascade, calc

bp = Blueprint("lots", __name__)

ALL_ROLES = {"AuctionAdmin", "Seller", "Buyer", "Arbitrator"}


# ===== Lot creation (run-listing) ==========================================
@bp.route("/auction/lots", methods=["POST"])
def create_lot():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    sale_id = require_str(body, "sale_id")
    consignment_id = require_str(body, "consignment_id")
    lane_id = require_str(body, "lane_id")
    run_number = require_int(body, "run_number", positive=True)
    slot_start = require_int(body, "slot_start_minute", minimum=0)
    slot_end = require_int(body, "slot_end_minute")
    starting_bid = require_int(body, "starting_bid_cents", minimum=0)
    if not (slot_start < slot_end):
        raise ApiError("ERR_VALIDATION", "Invalid slot window.")

    with db.lock:
        # existence (priority 4)
        sale = lookup.get_sale(sale_id)
        consignment = lookup.get_consignment(consignment_id)
        lane = lookup.get_lane(lane_id)

        # cross-aggregate coherence (priority 6): lane & consignment same sale
        if lane["sale_id"] != sale_id or consignment["sale_id"] != sale_id:
            raise ApiError("ERR_CROSS_SALE_REFERENCE", "References cross sales.")

        # temporal window (priority 7): slot must fit within lane window
        if not (slot_start >= lane["open_minute"] and slot_end <= lane["close_minute"]
                and slot_start < slot_end):
            raise ApiError("ERR_LANE_SLOT_OVERLAP", "Slot outside lane window.")
        # overlap with other active lots in the same lane (half-open intervals)
        for other in db.lots.values():
            if other["lane_id"] != lane_id:
                continue
            if other["status"] in ("WITHDRAWN", "PASSED"):
                continue
            o_start = other["slot_start_minute"]
            o_end = other["slot_end_minute"]
            if slot_start < o_end and o_start < slot_end:
                raise ApiError("ERR_LANE_SLOT_OVERLAP", "Slot overlaps another lot.")

        # run_number uniqueness within lane (priority 10)
        for other in db.lots.values():
            if other["lane_id"] == lane_id and other["run_number"] == run_number:
                raise ApiError("ERR_DUPLICATE_RUN_NUMBER", "Run number already used.")

        rec = base_record()
        rec.update({
            "sale_id": sale_id,
            "consignment_id": consignment_id,
            "lane_id": lane_id,
            "run_number": run_number,
            "slot_start_minute": slot_start,
            "slot_end_minute": slot_end,
            "starting_bid_cents": starting_bid,
            "high_bid_cents": 0,
            "high_bidder_id": None,
            "hammer_price_cents": 0,
            "outcome": "NONE",
            "status": "SCHEDULED",
        })
        db.lots[rec["id"]] = rec

        # cascade: Consignment CATALOGED -> RUN_LISTED
        if consignment["status"] == "CATALOGED":
            consignment["status"] = "RUN_LISTED"
            touch(consignment)

        cascade.recompute_lane_slot_count(lane)
        return success_object(public(rec), 201)


@bp.route("/auction/lots", methods=["GET"])
def list_lots():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    filters = {
        "sale_id": request.args.get("sale_id"),
        "consignment_id": request.args.get("consignment_id"),
        "lane_id": request.args.get("lane_id"),
        "status": request.args.get("status"),
    }
    items, limit, offset, total = list_collection(db.lots, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        lot = lookup.get_lot(lot_id)
        return success_object(public(lot))


# ===== Block lifecycle ======================================================
@bp.route("/auction/lots/<lot_id>/open-bidding", methods=["POST"])
def open_bidding(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "SCHEDULED":
            raise ApiError("ERR_LOT_NOT_SCHEDULED", "Lot not SCHEDULED.")
        sale = db.sales.get(lot["sale_id"])
        if sale is None or sale["status"] != "RUNNING":
            raise ApiError("ERR_SALE_NOT_RUNNING", "Sale not RUNNING.")
        lane = db.lanes.get(lot["lane_id"])
        if lane is None or lane["status"] != "ACTIVE":
            raise ApiError("ERR_LANE_NOT_ACTIVE", "Lane not ACTIVE.")
        consignment = db.consignments.get(lot["consignment_id"])
        floor = consignment["floor_price_cents"] if consignment else 0
        lot["status"] = "BIDDING_OPEN"
        lot["high_bid_cents"] = max(lot["starting_bid_cents"], floor)
        lot["high_bidder_id"] = None
        touch(lot)
        return success_object(public(lot))


@bp.route("/auction/lots/<lot_id>/close-bidding", methods=["POST"])
def close_bidding(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "BIDDING_OPEN":
            raise ApiError("ERR_LOT_NOT_BIDDING_OPEN", "Lot not BIDDING_OPEN.")
        # high_bid_cents and high_bidder_id are already maintained live; freeze.
        lot["status"] = "BIDDING_CLOSED"
        touch(lot)
        return success_object(public(lot))


def _frozen_outcome(lot, consignment):
    return calc.sale_outcome(lot["high_bidder_id"], lot["high_bid_cents"],
                             consignment["reserve_price_cents"])


def _winning_channel(lot):
    """Channel of the high bidder's max-ceiling bid frozen at hammer."""
    bidder = lot["high_bidder_id"]
    if bidder is None:
        return None
    best = None
    for b in db.bids.values():
        if b["lot_id"] != lot["id"] or b["buyer_id"] != bidder:
            continue
        if best is None or b["ceiling_cents"] > best["ceiling_cents"] or (
            b["ceiling_cents"] == best["ceiling_cents"] and b["_seq"] < best["_seq"]
        ):
            best = b
    return best["channel"] if best else "ONLINE"


@bp.route("/auction/lots/<lot_id>/hammer", methods=["POST"])
def hammer_lot(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "BIDDING_CLOSED":
            raise ApiError("ERR_LOT_NOT_BIDDING_CLOSED", "Lot not BIDDING_CLOSED.")
        consignment = db.consignments.get(lot["consignment_id"])
        outcome = _frozen_outcome(lot, consignment)
        if outcome != "SOLD":
            raise ApiError("ERR_OUTCOME_NOT_SOLD", "Outcome is not SOLD.")

        seller = db.sellers.get(consignment["seller_id"])
        # cross-aggregate coherence (priority 6): settlement seller == consignment seller
        # (guaranteed by construction; surfaced as defensive check)
        buyer = db.buyers.get(lot["high_bidder_id"])

        cr = cascade.condition_report_for(consignment["id"])
        as_is = bool(cr["as_is"]) if cr else False
        channel = _winning_channel(lot)
        schedule = db.sales.get(lot["sale_id"])["buyer_fee_schedule_code"]

        hammer_price = lot["high_bid_cents"]
        lot["outcome"] = "SOLD"
        lot["hammer_price_cents"] = hammer_price
        lot["status"] = "HAMMERED"
        touch(lot)

        # provisional seller proceeds + consignment SOLD
        provisional_proceeds = calc.seller_net_proceeds(
            hammer_price, seller["seller_fee_pct"] if seller else 0, as_is)
        consignment["status"] = "SOLD"
        consignment["expected_proceeds_cents"] = provisional_proceeds
        touch(consignment)

        # create Settlement (provisional)
        fee = calc.buyer_fee(hammer_price, schedule, channel)
        total_due = calc.buyer_total_due(hammer_price, fee)
        srec = base_record()
        srec.update({
            "lot_id": lot["id"],
            "buyer_id": lot["high_bidder_id"],
            "seller_id": consignment["seller_id"],
            "sale_price_cents": hammer_price,
            "buyer_fee_cents": fee,
            "total_due_cents": total_due,
            "seller_proceeds_cents": provisional_proceeds,
            "payment_status": "UNPAID",
            "title_status": "PENDING_TITLE",
            "status": "OPEN",
        })
        db.settlements[srec["id"]] = srec

        # debit buyer credit
        if buyer is not None:
            cascade.recompute_buyer_credit(buyer)

        return success_object(public(lot))


@bp.route("/auction/lots/<lot_id>/mark-if", methods=["POST"])
def mark_if(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "BIDDING_CLOSED":
            raise ApiError("ERR_LOT_NOT_BIDDING_CLOSED", "Lot not BIDDING_CLOSED.")
        consignment = db.consignments.get(lot["consignment_id"])
        outcome = _frozen_outcome(lot, consignment)
        if outcome != "IF":
            raise ApiError("ERR_OUTCOME_NOT_IF", "Outcome is not IF.")
        lot["outcome"] = "IF"
        lot["status"] = "IF_PENDING"
        touch(lot)
        if consignment["status"] == "RUN_LISTED":
            consignment["status"] = "IF_PENDING"
            touch(consignment)
        return success_object(public(lot))


@bp.route("/auction/lots/<lot_id>/pass", methods=["POST"])
def pass_lot(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "BIDDING_CLOSED":
            raise ApiError("ERR_LOT_NOT_BIDDING_CLOSED", "Lot not BIDDING_CLOSED.")
        consignment = db.consignments.get(lot["consignment_id"])
        outcome = _frozen_outcome(lot, consignment)
        if outcome != "PASSED":
            raise ApiError("ERR_OUTCOME_NOT_PASSED", "Outcome is not PASSED.")
        lot["outcome"] = "PASSED"
        lot["status"] = "PASSED"
        touch(lot)
        if consignment["status"] == "RUN_LISTED":
            consignment["status"] = "NO_SALE"
            touch(consignment)
        lane = db.lanes.get(lot["lane_id"])
        if lane is not None:
            cascade.recompute_lane_slot_count(lane)
        return success_object(public(lot))


@bp.route("/auction/lots/<lot_id>/relist", methods=["POST"])
def relist_lot(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "IF_PENDING":
            raise ApiError("ERR_LOT_NOT_IF_PENDING", "Lot not IF_PENDING.")
        sale = db.sales.get(lot["sale_id"])
        if sale is None or sale["status"] != "RUNNING":
            raise ApiError("ERR_SALE_NOT_RUNNING", "Sale not RUNNING.")
        lot["high_bid_cents"] = 0
        lot["high_bidder_id"] = None
        lot["outcome"] = "NONE"
        lot["status"] = "SCHEDULED"
        touch(lot)
        consignment = db.consignments.get(lot["consignment_id"])
        if consignment is not None and consignment["status"] == "IF_PENDING":
            consignment["status"] = "RUN_LISTED"
            touch(consignment)
        return success_object(public(lot))


@bp.route("/auction/lots/<lot_id>/withdraw", methods=["POST"])
def withdraw_lot(lot_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lot = lookup.get_lot(lot_id)
        if lot["status"] != "SCHEDULED":
            raise ApiError("ERR_LOT_NOT_SCHEDULED", "Lot not SCHEDULED.")
        lot["status"] = "WITHDRAWN"
        touch(lot)
        lane = db.lanes.get(lot["lane_id"])
        if lane is not None:
            cascade.recompute_lane_slot_count(lane)
        # cascade consignment RUN_LISTED -> NO_SALE if no other active lot
        consignment = db.consignments.get(lot["consignment_id"])
        if consignment is not None and consignment["status"] == "RUN_LISTED":
            others = [
                o for o in db.lots.values()
                if o["consignment_id"] == consignment["id"] and o["id"] != lot["id"]
                and o["status"] not in ("WITHDRAWN", "PASSED")
            ]
            if not others:
                consignment["status"] = "NO_SALE"
                touch(consignment)
        return success_object(public(lot))


# ===== Bidding ==============================================================
@bp.route("/auction/lots/<lot_id>/bids", methods=["POST"])
def place_bid(lot_id):
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    body = get_body()
    buyer_id = require_str(body, "buyer_id")
    bid_type = require_enum(body, "bid_type", ("LIVE", "PROXY"))
    amount = require_int(body, "amount_cents", positive=True)
    expected_version = require_int(body, "expected_lot_version", minimum=0)
    channel = require_enum(body, "channel", ("LANE", "ONLINE"),
                           default="ONLINE", required=False)

    with db.lock:
        # ownership (priority 3): buyer may only bid under own buyer_id
        if buyer_id != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Buyer may only bid under own id.")
        # existence (priority 4): path lot, then body buyer
        lot = lookup.get_lot(lot_id)
        buyer = lookup.get_buyer(buyer_id)

        # state (priority 5): lot must be BIDDING_OPEN
        if lot["status"] != "BIDDING_OPEN":
            raise ApiError("ERR_LOT_NOT_BIDDING_OPEN", "Lot not BIDDING_OPEN.")
        # buyer must be ACTIVE
        if buyer["status"] != "ACTIVE":
            raise ApiError("ERR_BUYER_SUSPENDED", "Buyer suspended.")
        # OCC: expected_lot_version must match
        if expected_version != lot["version"]:
            raise ApiError("ERR_STALE_LOT_VERSION", "Stale lot version.")

        consignment = db.consignments.get(lot["consignment_id"])

        # minimum increment rule (priority 9)
        current_high = lot["high_bid_cents"]
        has_buyer_high = lot["high_bidder_id"] is not None
        if has_buyer_high:
            increment = calc.bid_increment(current_high)
            minimum = current_high + increment
        else:
            minimum = current_high
        if amount < minimum:
            raise ApiError("ERR_BID_BELOW_MINIMUM", "Bid below minimum.")

        # project clearing price as if this bid were appended, for credit check
        prospective = list(_bids_for_lot(lot_id))
        prospective.append({
            "buyer_id": buyer_id,
            "ceiling_cents": amount,
            "_seq": float("inf"),  # ordering: ties resolved to existing bids first
        })
        proj_bidder, proj_high = calc.clearing_price(lot, consignment, prospective)

        # credit check (priority 11): projected total_due if THIS bid wins
        if proj_bidder == buyer_id:
            schedule = db.sales.get(lot["sale_id"])["buyer_fee_schedule_code"]
            proj_fee = calc.buyer_fee(proj_high, schedule, channel)
            proj_total = calc.buyer_total_due(proj_high, proj_fee)
            if buyer["available_credit_cents"] < proj_total:
                raise ApiError("ERR_INSUFFICIENT_CREDIT", "Insufficient credit.")

        # append immutable bid
        bid = base_record(common_fields=False)
        bid.update({
            "lot_id": lot_id,
            "buyer_id": buyer_id,
            "bid_type": bid_type,
            "channel": channel,
            "amount_cents": amount,
            "ceiling_cents": amount,
        })
        db.bids[bid["id"]] = bid

        # recompute clearing price from all bids
        all_bids = list(_bids_for_lot(lot_id))
        new_bidder, new_high = calc.clearing_price(lot, consignment, all_bids)
        lot["high_bidder_id"] = new_bidder
        lot["high_bid_cents"] = new_high
        touch(lot)  # increments version by 1

        return success_object(public(bid), 201)


def _bids_for_lot(lot_id):
    items = [b for b in db.bids.values() if b["lot_id"] == lot_id]
    items.sort(key=lambda b: b["_seq"])
    return items


@bp.route("/auction/bids", methods=["GET"])
def list_bids():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    filters = {
        "lot_id": request.args.get("lot_id"),
        "buyer_id": request.args.get("buyer_id"),
    }
    items, limit, offset, total = list_collection(db.bids, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/bids/<bid_id>", methods=["GET"])
def get_bid(bid_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        bid = lookup.get_bid(bid_id)
        return success_object(public(bid))
