"""Auction lots & bids (PRD §3.5)."""
import errors
from cascades import payoff_floor_plan_for_unit
from clock import clock, parse_iso8601
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_generic, serialize_bid
from validation import get_json, require_fk, require_int

LOT_READ_ROLES = ("AuctionClerk", "DealerAdmin", "SalesRep", "FinanceManager")
BID_READ_ROLES = ("AuctionClerk", "DealerAdmin")


def register(app):

    @app.route("/auction-lots", methods=["POST"])
    @require_roles("AuctionClerk", "DealerAdmin")
    def consign_lot():
        body = get_json()
        unit_id = require_fk(body, "unit_id")
        reserve_price_cents = require_int(body, "reserve_price_cents", gt=0)
        opens_at_raw = body.get("opens_at")
        closes_at_raw = body.get("closes_at")
        opens_at = parse_iso8601(opens_at_raw)
        closes_at = parse_iso8601(closes_at_raw)
        if opens_at is None or closes_at is None:
            raise err(errors.ERR_INVALID_REQUEST,
                      "opens_at and closes_at must be ISO 8601 instants.")
        unit = lookup(db.units, unit_id)

        # temporal window check (ERR_AUCTION_WINDOW)
        if not (closes_at > opens_at):
            raise err(errors.ERR_AUCTION_WINDOW, "closes_at must be strictly after opens_at.")
        # consign only when unit AVAILABLE and USED
        if unit["status"] != "AVAILABLE" or unit["condition"] != "USED":
            raise err(errors.ERR_INVALID_STATE,
                      "Unit must be AVAILABLE and USED to consign.")

        lot = {
            "unit_id": unit_id,
            "reserve_price_cents": reserve_price_cents,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "high_bid_cents": 0,
            "high_bidder_customer_id": None,
            "winning_deal_id": None,
            "status": "DRAFT",
        }
        make_common(lot)
        db.auction_lots[lot["id"]] = lot

        unit["status"] = "AUCTION_LISTED"
        touch(unit)
        return respond(serialize_generic(lot), status=201)

    @app.route("/auction-lots", methods=["GET"])
    @require_roles(*LOT_READ_ROLES)
    def list_lots():
        from flask import request
        items = list(db.auction_lots.values())
        for key in ("unit_id", "high_bidder_customer_id", "winning_deal_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [l for l in items if l.get(key) == val]
        return list_and_respond(items, serialize_generic)

    @app.route("/auction-lots/<lot_id>", methods=["GET"])
    @require_roles(*LOT_READ_ROLES)
    def get_lot(lot_id):
        lot = lookup(db.auction_lots, lot_id)
        return respond(serialize_generic(lot))

    @app.route("/auction-lots/<lot_id>/open", methods=["POST"])
    @require_roles("AuctionClerk")
    def open_lot(lot_id):
        lot = lookup(db.auction_lots, lot_id)
        if lot["status"] != "DRAFT":
            raise err(errors.ERR_INVALID_STATE, "Lot is not DRAFT.")
        if clock.now() < lot["opens_at"]:
            raise err(errors.ERR_AUCTION_WINDOW, "Clock is before opens_at.")
        lot["status"] = "LIVE"
        touch(lot)
        return respond(serialize_generic(lot))

    @app.route("/auction-lots/<lot_id>/bids", methods=["POST"])
    @require_roles("AuctionClerk", "SalesRep")
    def place_bid(lot_id):
        lot = lookup(db.auction_lots, lot_id)
        body = get_json()
        bidder_customer_id = require_fk(body, "bidder_customer_id")
        amount_cents = require_int(body, "amount_cents", gt=0)
        lookup(db.customers, bidder_customer_id)

        # lot must be LIVE and clock within [opens_at, closes_at), and bid
        # strictly greater than current high — all surface ERR_BID_TOO_LOW.
        now = clock.now()
        if lot["status"] != "LIVE" or now < lot["opens_at"] or now >= lot["closes_at"]:
            raise err(errors.ERR_BID_TOO_LOW, "Lot is not open for bidding.")
        if amount_cents <= lot["high_bid_cents"]:
            raise err(errors.ERR_BID_TOO_LOW,
                      "Bid must be strictly greater than current high bid.")

        bid = {
            "lot_id": lot_id,
            "bidder_customer_id": bidder_customer_id,
            "amount_cents": amount_cents,
        }
        # Bid is append-only: only id + created_at (no version/updated_at).
        from db import new_id, now_ts
        bid["id"] = new_id()
        bid["created_at"] = now_ts()
        bid["_seq"] = db.next_seq()
        db.bids[bid["id"]] = bid

        lot["high_bid_cents"] = amount_cents
        lot["high_bidder_customer_id"] = bidder_customer_id
        touch(lot)
        return respond(serialize_bid(bid), status=201)

    @app.route("/auction-lots/<lot_id>/bids", methods=["GET"])
    @require_roles("AuctionClerk", "DealerAdmin")
    def list_lot_bids(lot_id):
        lookup(db.auction_lots, lot_id)
        items = [b for b in db.bids.values() if b["lot_id"] == lot_id]
        return list_and_respond(items, serialize_bid)

    @app.route("/bids", methods=["GET"])
    @require_roles(*BID_READ_ROLES)
    def list_bids():
        from flask import request
        items = list(db.bids.values())
        for key in ("lot_id", "bidder_customer_id"):
            val = request.args.get(key)
            if val is not None:
                items = [b for b in items if b.get(key) == val]
        return list_and_respond(items, serialize_bid)

    @app.route("/bids/<bid_id>", methods=["GET"])
    @require_roles(*BID_READ_ROLES)
    def get_bid(bid_id):
        bid = lookup(db.bids, bid_id)
        return respond(serialize_bid(bid))

    @app.route("/auction-lots/<lot_id>/close", methods=["POST"])
    @require_roles("AuctionClerk")
    def close_lot(lot_id):
        lot = lookup(db.auction_lots, lot_id)
        if lot["status"] != "LIVE":
            raise err(errors.ERR_INVALID_STATE, "Lot is not LIVE.")
        if clock.now() < lot["closes_at"]:
            raise err(errors.ERR_AUCTION_WINDOW, "Clock is before closes_at.")
        if lot["high_bid_cents"] >= lot["reserve_price_cents"] and lot["high_bid_cents"] > 0:
            lot["status"] = "CLOSED_MET"
        else:
            lot["status"] = "CLOSED_NO_SALE"
        touch(lot)
        return respond(serialize_generic(lot))

    @app.route("/auction-lots/<lot_id>/settle", methods=["POST"])
    @require_roles("AuctionClerk")
    def settle_lot(lot_id):
        lot = lookup(db.auction_lots, lot_id)
        body = get_json()
        expected_unit_version = require_int(body, "expected_unit_version", minimum=0)

        if lot["status"] not in ("CLOSED_MET", "CLOSED_NO_SALE"):
            raise err(errors.ERR_INVALID_STATE, "Lot is not CLOSED_MET/CLOSED_NO_SALE.")
        unit = db.units.get(lot["unit_id"])
        if unit is None or unit["version"] != expected_unit_version:
            raise err(errors.ERR_STALE_UNIT_VERSION,
                      "expected_unit_version does not match the unit's version.")

        if lot["status"] == "CLOSED_MET":
            # create an AUCTION_SALE Deal (FUNDED) for the high bidder
            deal = {
                "unit_id": lot["unit_id"],
                "customer_id": lot["high_bidder_customer_id"],
                "deal_type": "AUCTION_SALE",
                "sale_price_cents": lot["high_bid_cents"],
                "lease_term_months": 0,
                "tradein_id": None,
                "trade_allowance_cents": 0,
                "tax_cents": 0,
                "monthly_payment_cents": 0,
                "amount_due_cents": 0,
                "status": "FUNDED",
            }
            # compute amount due for the auction sale (no trade)
            import calc
            customer = db.customers.get(lot["high_bidder_customer_id"])
            tax_exempt = bool(customer["tax_exempt"]) if customer else False
            tax_cents, amount_due = calc.deal_amount_due(
                lot["high_bid_cents"], 0, tax_exempt
            )
            deal["tax_cents"] = tax_cents
            deal["amount_due_cents"] = amount_due
            make_common(deal)
            db.deals[deal["id"]] = deal

            unit["status"] = "AUCTION_SOLD"
            if unit["floor_planned"]:
                payoff_floor_plan_for_unit(unit)
            touch(unit)

            lot["winning_deal_id"] = deal["id"]
            lot["status"] = "SETTLED"
            touch(lot)
        else:  # CLOSED_NO_SALE
            unit["status"] = "AVAILABLE"
            touch(unit)
            lot["status"] = "SETTLED"
            touch(lot)

        return respond(serialize_generic(lot))
