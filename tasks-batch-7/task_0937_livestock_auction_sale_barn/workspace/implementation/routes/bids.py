"""The ring: recording bids (PRD 3.8)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, check_min, fields, path_row, reference
from envelope import filter_arg, ok, paginate
from errors import fail
from gates import run_gates
from money import D, q2
from services import buyers
from services.bidding import current_winning, lot_bids, minimum_acceptable
from services.lots import lot_extension
from store import db, get, insert_versioned, touch

bp = Blueprint("bids", __name__)
ALL = config.ALL_ROLES


@bp.post("/sale-barn/bids")
def create_bid():
    role, user_id = actor(["RingClerk", "Buyer"])
    data = body()
    v = fields(data, required=[("lot_id", "string"),
                               ("buyer_registration_id", "string"),
                               ("unit_price", "number")])
    check_min(v["unit_price"], 0, "unit_price", inclusive=False)

    lot = reference("lots", v["lot_id"], "Lot")
    reg = reference("buyer_registrations", v["buyer_registration_id"],
                    "BuyerRegistration")

    # Rung 8 - a bid's registration and its lot share a sale day.
    if reg["sale_day_id"] != lot["sale_day_id"]:
        fail("ERR_SALE_DAY_MISMATCH")

    # Rung 9 - a Buyer recording a bid is checked through the named
    # registration's party_id (PRD 2.1).
    if role == "Buyer" and user_id != reg["party_id"]:
        fail("ERR_OWNERSHIP_VIOLATION")

    sale_day = get("sale_days", lot["sale_day_id"])
    party = get("parties", reg["party_id"])
    run_gates("bids.create", sale_day=sale_day, lot=lot, party=party)

    if lot["sale_status"] != "IN_RING":
        fail("ERR_INVALID_STATE")

    # Rungs 33 and 34.
    if reg["status"] != "APPROVED" and reg["status"] != "CREDIT_HOLD":
        fail("ERR_BUYER_NOT_APPROVED")
    if reg["status"] == "CREDIT_HOLD":
        fail("ERR_BUYER_CREDIT_HOLD")

    price = D(v["unit_price"])
    winner = current_winning(lot["id"])
    floor = minimum_acceptable(lot, winner)
    if winner is None:
        # Rung 35.
        if price < floor:
            fail("ERR_BID_BELOW_OPENING")
    else:
        # Rung 36 - the increment is tiered off the CURRENT HIGH.
        if price < floor:
            fail("ERR_BID_BELOW_INCREMENT")

    projected_extension = lot_extension(lot, price)

    # Rung 37 - a buyer bidding against themselves displaces their own bid
    # rather than stacking on it.
    displaced = D(0)
    if winner is not None and winner["buyer_registration_id"] == reg["id"]:
        displaced = D(winner["projected_extension"])
    projected_exposure = q2(buyers.exposure(reg) - displaced + projected_extension)
    if projected_exposure > D(reg["effective_limit"]):
        fail("ERR_CREDIT_LIMIT_EXCEEDED")

    bid = insert_versioned("bids", {
        "lot_id": lot["id"],
        "buyer_registration_id": reg["id"],
        "unit_price": price,
        "bid_seq": len(lot_bids(lot["id"])) + 1,
        "projected_extension": projected_extension,
        "status": "WINNING",
    })
    if winner is not None:
        winner["status"] = "OUTBID"
        touch(winner)
    return ok(serialize.bid(bid), 201)


@bp.get("/sale-barn/bids/<bid_id>")
def read_bid(bid_id):
    actor(ALL)
    return ok(serialize.bid(path_row("bids", bid_id, "Bid")))


@bp.get("/sale-barn/bids")
def list_bids():
    actor(ALL)
    rows = list(db["bids"].values())
    for key in ("lot_id", "buyer_registration_id", "status"):
        value = filter_arg(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paginate(rows, serialize.bid)
