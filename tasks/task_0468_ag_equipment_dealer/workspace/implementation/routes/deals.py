"""Deals: quote, approve, fund, deliver, unwind (PRD §3.4)."""
import calc
import errors
from cascades import accept_tradein_and_mint, payoff_floor_plan_for_unit, \
    revert_tradein_on_unwind
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_generic
from validation import (
    get_json,
    require_fk,
    require_enum,
    require_int,
    optional_int,
    optional_fk,
)

QUOTE_ROLES = ("SalesRep", "FinanceManager")
READ_ROLES = ("SalesRep", "FinanceManager", "DealerAdmin", "AuctionClerk")


def register(app):

    @app.route("/deals", methods=["POST"])
    @require_roles(*QUOTE_ROLES)
    def quote_deal():
        body = get_json()
        unit_id = require_fk(body, "unit_id")
        customer_id = require_fk(body, "customer_id")
        deal_type = require_enum(body, "deal_type",
                                 {"SALE", "LEASE", "AUCTION_SALE"})
        sale_price_cents = require_int(body, "sale_price_cents", gt=0)
        lease_term_months = optional_int(body, "lease_term_months", default=0, minimum=0)
        tradein_id = optional_fk(body, "tradein_id")

        # existence: left-to-right (unit, customer, then tradein)
        unit = lookup(db.units, unit_id)
        lookup(db.customers, customer_id)
        tradein = None
        if tradein_id is not None:
            tradein = lookup(db.trade_ins, tradein_id)

        # business: unit must be AVAILABLE to reserve
        if unit["status"] != "AVAILABLE":
            raise err(errors.ERR_UNIT_NOT_RESERVABLE, "Unit is not AVAILABLE.")
        # trade attach: must be OFFERED
        if tradein is not None and tradein["status"] != "OFFERED":
            raise err(errors.ERR_TRADEIN_NOT_OFFERED, "Trade-in is not OFFERED.")

        deal = {
            "unit_id": unit_id,
            "customer_id": customer_id,
            "deal_type": deal_type,
            "sale_price_cents": sale_price_cents,
            "lease_term_months": lease_term_months,
            "tradein_id": tradein_id,
            "trade_allowance_cents": 0,
            "tax_cents": 0,
            "monthly_payment_cents": 0,
            "amount_due_cents": 0,
            "status": "QUOTED",
        }
        make_common(deal)
        db.deals[deal["id"]] = deal

        # Quoting a SALE or LEASE reserves the unit (AUCTION_SALE does not).
        if deal_type in ("SALE", "LEASE"):
            unit["status"] = "RESERVED"
            touch(unit)
        return respond(serialize_generic(deal), status=201)

    @app.route("/deals", methods=["GET"])
    @require_roles(*READ_ROLES)
    def list_deals():
        from flask import request
        items = list(db.deals.values())
        for key in ("unit_id", "customer_id", "tradein_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [d for d in items if d.get(key) == val]
        return list_and_respond(items, serialize_generic)

    @app.route("/deals/<deal_id>", methods=["GET"])
    @require_roles(*READ_ROLES)
    def get_deal(deal_id):
        deal = lookup(db.deals, deal_id)
        return respond(serialize_generic(deal))

    @app.route("/deals/<deal_id>/approve", methods=["POST"])
    @require_roles("FinanceManager")
    def approve_deal(deal_id):
        deal = lookup(db.deals, deal_id)
        if deal["status"] != "QUOTED":
            raise err(errors.ERR_INVALID_STATE, "Deal is not QUOTED.")
        if deal["tradein_id"]:
            tradein = db.trade_ins.get(deal["tradein_id"])
            if tradein is None or tradein["status"] != "OFFERED":
                raise err(errors.ERR_TRADEIN_NOT_OFFERED, "Trade-in is not OFFERED.")
        deal["status"] = "APPROVED"
        touch(deal)
        return respond(serialize_generic(deal))

    @app.route("/deals/<deal_id>/fund", methods=["POST"])
    @require_roles("FinanceManager")
    def fund_deal(deal_id):
        deal = lookup(db.deals, deal_id)
        body = get_json()
        expected_unit_version = require_int(body, "expected_unit_version", minimum=0)

        # state legality (priority 6)
        if deal["status"] != "APPROVED":
            raise err(errors.ERR_INVALID_STATE, "Deal is not APPROVED.")
        unit = db.units.get(deal["unit_id"])
        # OCC (priority 7) — before business preconditions
        if unit is None or unit["version"] != expected_unit_version:
            raise err(errors.ERR_STALE_UNIT_VERSION,
                      "expected_unit_version does not match the unit's version.")
        # business: unit must be RESERVED (priority 8)
        if unit["status"] != "RESERVED":
            raise err(errors.ERR_UNIT_NOT_RESERVABLE, "Unit is not RESERVED.")
        # trade attach (priority 9)
        tradein = None
        if deal["tradein_id"]:
            tradein = db.trade_ins.get(deal["tradein_id"])
            if tradein is None or tradein["status"] != "OFFERED":
                raise err(errors.ERR_TRADEIN_NOT_OFFERED, "Trade-in is not OFFERED.")

        customer = db.customers.get(deal["customer_id"])

        # compute economics
        if deal["deal_type"] in ("SALE", "AUCTION_SALE"):
            trade_allowance = tradein["appraised_value_cents"] if tradein else 0
            tax_cents, amount_due = calc.deal_amount_due(
                deal["sale_price_cents"], trade_allowance,
                bool(customer["tax_exempt"])
            )
            deal["trade_allowance_cents"] = trade_allowance
            deal["tax_cents"] = tax_cents
            deal["amount_due_cents"] = amount_due
            deal["monthly_payment_cents"] = 0
        else:  # LEASE
            trade_allowance = tradein["appraised_value_cents"] if tradein else 0
            monthly = calc.lease_monthly_payment(
                deal["sale_price_cents"], trade_allowance,
                customer["credit_tier"], deal["lease_term_months"]
            )
            deal["trade_allowance_cents"] = trade_allowance
            deal["monthly_payment_cents"] = monthly
            deal["tax_cents"] = 0
            deal["amount_due_cents"] = 0

        # unit status transition
        if deal["deal_type"] == "SALE":
            unit["status"] = "SOLD"
        elif deal["deal_type"] == "LEASE":
            unit["status"] = "LEASED"
        else:
            unit["status"] = "AUCTION_SOLD"

        # floor-plan payoff cascade
        if unit["floor_planned"]:
            payoff_floor_plan_for_unit(unit)
        touch(unit)

        # trade-in accept cascade (mint a used unit)
        if tradein is not None:
            accept_tradein_and_mint(tradein)

        deal["status"] = "FUNDED"
        touch(deal)
        return respond(serialize_generic(deal))

    @app.route("/deals/<deal_id>/deliver", methods=["POST"])
    @require_roles("SalesRep", "FinanceManager")
    def deliver_deal(deal_id):
        deal = lookup(db.deals, deal_id)
        if deal["status"] != "FUNDED":
            raise err(errors.ERR_INVALID_STATE, "Deal is not FUNDED.")
        deal["status"] = "DELIVERED"
        touch(deal)
        return respond(serialize_generic(deal))

    @app.route("/deals/<deal_id>/unwind", methods=["POST"])
    @require_roles("FinanceManager")
    def unwind_deal(deal_id):
        deal = lookup(db.deals, deal_id)
        body = get_json()
        expected_unit_version = require_int(body, "expected_unit_version", minimum=0)

        if deal["status"] != "FUNDED" or deal["deal_type"] != "SALE":
            raise err(errors.ERR_INVALID_STATE, "Only a FUNDED SALE deal can be unwound.")
        unit = db.units.get(deal["unit_id"])
        if unit is None or unit["version"] != expected_unit_version:
            raise err(errors.ERR_STALE_UNIT_VERSION,
                      "expected_unit_version does not match the unit's version.")

        # reverse economics
        deal["tax_cents"] = 0
        deal["trade_allowance_cents"] = 0
        deal["amount_due_cents"] = 0
        deal["status"] = "UNWOUND"
        touch(deal)

        # unit SOLD -> REPOSSESSED
        unit["status"] = "REPOSSESSED"
        touch(unit)

        # trade reversal cascade
        if deal["tradein_id"]:
            tradein = db.trade_ins.get(deal["tradein_id"])
            if tradein is not None and tradein["status"] == "ACCEPTED":
                revert_tradein_on_unwind(tradein)

        return respond(serialize_generic(deal))
