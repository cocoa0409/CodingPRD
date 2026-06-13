"""Bid routes (PRD §3.5).

Place a bid on an OPEN lot, read, list, retract. Bidding carries the full
domain validation chain: eligibility, min-next-bid, credit limit.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_int, require_enum, parse_pagination, paginate,
    validate_occ_field, match_occ,
)
from services.domain import (
    standing_high_amount, recompute_bidder_outstanding,
)
from services.calculations import min_next_bid_cents, buyers_premium_cents

bp = Blueprint("bids", __name__)

BID_READ_ROLES = {
    "SaleAdministrator", "FinanceOfficer", "Auctioneer", "Bidder", "Viewer",
}


def _projected_total_due(lot, hammer_cents):
    """Projected total_due_cents if this bid won: hammer + buyer's premium for
    the lot's sale schedule (PRD §3.5 credit check)."""
    sale = db.auction_sales.get(lot["auction_sale_id"])
    schedule = db.premium_schedules.get(sale["buyers_premium_schedule_id"]) if sale else None
    tiers = schedule["tiers"] if schedule else []
    premium = buyers_premium_cents(hammer_cents, tiers)
    return hammer_cents + premium


@bp.route("/lots/<id>/bids", methods=["POST"])
def place_bid(id):
    user_id, role = require_role({"Auctioneer", "Bidder"})
    body = get_json_body()

    with db.LOCK:
        # priority 4: path existence
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")

        # body well-formedness for the FK field presence (need it to resolve)
        paddle_id = body.get("paddle_registration_id")
        if paddle_id is None or not isinstance(paddle_id, str) or paddle_id == "":
            raise err(errors.ERR_INVALID_REQUEST, "paddle_registration_id required")

        # priority 5: body FK resolution (needed before ownership can apply)
        paddle = db.paddle_registrations.get(paddle_id)
        if paddle is None:
            raise err(errors.ERR_FK_NOT_FOUND, "paddle_registration_id does not resolve")

        # priority 3: ownership — a Bidder may bid only via its own paddle.
        if role == "Bidder" and paddle["bidder_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning bidder's paddle")

        # priority 6: remaining body well-formedness
        amount = require_int(body, "amount_cents", minimum=0)
        bid_channel = require_enum(body, "bid_channel", {"FLOOR", "ABSENTEE", "PHONE"},
                                   default="FLOOR")

        # priority 7: single-entity state — lot must be OPEN.
        # (Lot OPEN is treated as the dependency guard per §1.4 priority 8;
        # but the lot being OPEN is also its own room state. PRD §3.5 lists the
        # lot-OPEN and sale-LIVE both as dependency guards -> ERR_DEPENDENCY_NOT_READY.)
        sale = db.auction_sales.get(lot["auction_sale_id"])
        if sale is None or sale["status"] != "LIVE" or lot["sale_status"] != "OPEN":
            raise err(errors.ERR_DEPENDENCY_NOT_READY, "Sale not LIVE or lot not OPEN")

        # priority 10: eligibility — suspended bidder / revoked paddle / channel.
        bidder = db.bidders.get(paddle["bidder_id"])
        if bidder is None or bidder["status"] == "SUSPENDED":
            raise err(errors.ERR_PADDLE_INELIGIBLE, "Bidder is suspended")
        if paddle["status"] == "REVOKED":
            raise err(errors.ERR_PADDLE_INELIGIBLE, "Paddle is revoked")
        if bid_channel != paddle["registration_type"]:
            raise err(errors.ERR_PADDLE_INELIGIBLE,
                      "bid_channel inconsistent with registration_type")

        # priority 12: minimum next bid threshold.
        standing = standing_high_amount(id, statuses=("ACCEPTED", "WINNING"))
        min_next = min_next_bid_cents(standing)
        if amount < min_next:
            raise err(errors.ERR_BID_TOO_LOW, "Bid below minimum next bid")

        # priority 14: credit limit — outstanding + projected total_due of this
        # bid (if it won) must not exceed credit_limit_cents.
        projected = _projected_total_due(lot, amount)
        if bidder["outstanding_balance_cents"] + projected > bidder["credit_limit_cents"]:
            raise err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "Bid would exceed credit limit")

        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "lot_id": id,
            "paddle_registration_id": paddle_id,
            "amount_cents": amount,
            "bid_channel": bid_channel,
            "status": "ACCEPTED",
        }
        db.bids[record["id"]] = record
        # Placing a bid bumps the lot's version (arms the knock-down OCC guard).
        db.touch(lot)
        return object_response(serialize(record), 201)


@bp.route("/bids/<id>", methods=["GET"])
def get_bid(id):
    user_id, role = require_role(BID_READ_ROLES)
    with db.LOCK:
        bid = db.bids.get(id)
        if bid is None:
            raise err(errors.ERR_NOT_FOUND, "Bid not found")
        if role == "Bidder":
            paddle = db.paddle_registrations.get(bid["paddle_registration_id"])
            if paddle is None or paddle["bidder_id"] != user_id:
                raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning bidder's bid")
        return object_response(serialize(bid), 200)


@bp.route("/lots/<id>/bids", methods=["GET"])
def list_lot_bids(id):
    user_id, role = require_role(BID_READ_ROLES)
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        limit, offset = parse_pagination(request.args)
        paddle_filter = request.args.get("paddle_registration_id")
        rows = [b for b in db.bids.values() if b["lot_id"] == id]
        if paddle_filter is not None:
            rows = [b for b in rows if b["paddle_registration_id"] == paddle_filter]
        if role == "Bidder":
            owned = {p["id"] for p in db.paddle_registrations.values()
                     if p["bidder_id"] == user_id}
            rows = [b for b in rows if b["paddle_registration_id"] in owned]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/bids", methods=["GET"])
def list_bids():
    user_id, role = require_role(BID_READ_ROLES)
    with db.LOCK:
        limit, offset = parse_pagination(request.args)
        paddle_filter = request.args.get("paddle_registration_id")
        lot_filter = request.args.get("lot_id")
        rows = list(db.bids.values())
        if paddle_filter is not None:
            rows = [b for b in rows if b["paddle_registration_id"] == paddle_filter]
        if lot_filter is not None:
            rows = [b for b in rows if b["lot_id"] == lot_filter]
        if role == "Bidder":
            owned = {p["id"] for p in db.paddle_registrations.values()
                     if p["bidder_id"] == user_id}
            rows = [b for b in rows if b["paddle_registration_id"] in owned]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/bids/<id>/retract", methods=["POST"])
def retract_bid(id):
    require_role({"Auctioneer"})
    body = get_json_body()
    with db.LOCK:
        bid = db.bids.get(id)
        if bid is None:
            raise err(errors.ERR_NOT_FOUND, "Bid not found")
        validate_occ_field(body, "expected_bid_version", required=True)
        if bid["status"] != "ACCEPTED":
            raise err(errors.ERR_INVALID_STATE, "Bid is not ACCEPTED")
        match_occ(bid, body, "expected_bid_version")
        bid["status"] = "RETRACTED"
        db.touch(bid)
        return object_response(serialize(bid), 200)
