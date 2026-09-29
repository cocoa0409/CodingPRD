"""Redemption orders: quotes, confirmation, ticketing, settlement (PRD 3.6)."""

from flask import Blueprint, request

from auth import endpoint, require_agency_scope, require_ownership
from core import DB, clock_iso, dec, find, must_find, new_row, ok, store, touch
from errors import ApiError, invalid
from rhelp import (
    require_account_open,
    require_agency_active,
    require_available_points,
    require_in_parity,
    require_not_locked,
    require_state,
)
from shapes import body, opt_int, req_enum, req_int, req_string
from svc_ledger import append_entry, recompute_seats, refresh_account
from svc_pricing import blank_order, cost_per_1k, price_statement_credit
from views import ADMIN, ALL_ROLES, CARDHOLDER, SUPPLIER, listing, plain

bp = Blueprint("orders", __name__)

CHANNELS = ("PORTAL_BOOKING", "STATEMENT_CREDIT")
STATEMENT_CREDIT_MINIMUM = 2500


def _offer_of(order):
    if not order.get("inventory_offer_id"):
        return None
    return find("offers", order["inventory_offer_id"])


def _agency_of(order):
    offer = _offer_of(order)
    if offer is None:
        return None
    return find("agencies", offer["agency_partner_id"])


@bp.post("/redemption-orders")
@endpoint(CARDHOLDER)
def create_order():
    data = body()
    account_id = data.get("account_id")
    if isinstance(account_id, str):
        require_ownership(account_id)
    if not isinstance(account_id, str) or account_id.strip() == "":
        raise invalid("'account_id' is required")
    account = must_find("accounts", account_id)

    channel = req_enum(data, "channel", CHANNELS)
    points_requested = None
    if channel == "STATEMENT_CREDIT":
        points_requested = req_int(data, "points_requested", minimum=1)

    require_account_open(account)
    require_not_locked(account)

    if channel == "PORTAL_BOOKING":
        raise ApiError(
            "ERR_CHANNEL_REQUIRES_OFFER",
            "A PORTAL_BOOKING order must be created through the offer's book endpoint.",
        )
    if points_requested < STATEMENT_CREDIT_MINIMUM:
        raise ApiError(
            "ERR_STATEMENT_CREDIT_BELOW_MINIMUM",
            "A statement credit must be for at least %d points." % STATEMENT_CREDIT_MINIMUM,
        )
    require_available_points(account, points_requested)

    row = new_row("orders", blank_order(account_id, channel))
    row["points_requested"] = points_requested
    price_statement_credit(row, account, points_requested)
    store("orders", row)
    refresh_account(account)
    touch(account)
    return ok(plain(row), 201)


@bp.get("/redemption-orders/<order_id>")
@endpoint(ALL_ROLES)
def read_order(order_id):
    return ok(plain(must_find("orders", order_id)))


@bp.get("/redemption-orders")
@endpoint(ALL_ROLES)
def list_orders():
    args = request.args
    filters = {
        "account_id": args.get("account_id"),
        "inventory_offer_id": args.get("inventory_offer_id"),
        "channel": args.get("channel"),
        "fulfillment_status": args.get("fulfillment_status"),
        "settlement_status": args.get("settlement_status"),
    }
    return listing("orders", args, filters)


@bp.post("/redemption-orders/<order_id>/confirm")
@endpoint(CARDHOLDER)
def confirm_order(order_id):
    order = must_find("orders", order_id)
    require_ownership(order["account_id"])
    account = must_find("accounts", order["account_id"])
    require_state(order, ("QUOTED",), "fulfillment_status")
    require_not_locked(account)
    offer = _offer_of(order)
    if order["channel"] == "PORTAL_BOOKING" and offer is not None:
        if offer["status"] not in ("OPEN", "SOLD_OUT"):
            raise ApiError(
                "ERR_OFFER_NOT_BOOKABLE",
                "Offer '%s' is %s and cannot back a confirmation." % (offer["id"], offer["status"]),
            )
        require_in_parity(offer)
    refresh_account(account)
    if account["points_balance"] < order["points_debited"]:
        raise ApiError(
            "ERR_INSUFFICIENT_POINTS",
            "Account '%s' has insufficient points to confirm." % account["id"],
        )

    order["fulfillment_status"] = "CONFIRMED"
    order["confirmed_at"] = clock_iso()
    touch(order)
    append_entry(
        account,
        "REDEEM_DEBIT",
        -order["points_debited"],
        "REDEMPTION_ORDER",
        order["id"],
        "Points debited on redemption confirmation",
    )
    refresh_account(account)
    touch(account)
    return ok(plain(order))


@bp.post("/redemption-orders/<order_id>/cancel")
@endpoint(CARDHOLDER)
def cancel_order(order_id):
    order = must_find("orders", order_id)
    require_ownership(order["account_id"])
    account = must_find("accounts", order["account_id"])
    closed_reason = req_string(body(), "closed_reason")
    require_state(order, ("QUOTED", "CONFIRMED"), "fulfillment_status")

    was_confirmed = order["fulfillment_status"] == "CONFIRMED"
    order["fulfillment_status"] = "CANCELLED"
    order["closed_reason"] = closed_reason
    touch(order)
    if was_confirmed:
        append_entry(
            account,
            "REDEEM_REFUND",
            order["points_debited"],
            "REDEMPTION_ORDER",
            order["id"],
            "Points refunded on cancellation of a confirmed order",
        )
    offer = _offer_of(order)
    if offer is not None and recompute_seats(offer, release=True):
        touch(offer)
    refresh_account(account)
    touch(account)
    return ok(plain(order))


@bp.post("/redemption-orders/<order_id>/ticket")
@endpoint(SUPPLIER)
def ticket_order(order_id):
    order = must_find("orders", order_id)
    offer = _offer_of(order)
    if offer is not None:
        require_agency_scope(offer["agency_partner_id"])
    ticket_number = req_string(body(), "ticket_number")
    require_state(order, ("CONFIRMED",), "fulfillment_status")
    if order["channel"] != "PORTAL_BOOKING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "Only a PORTAL_BOOKING order can be ticketed.",
        )
    agency = _agency_of(order)
    if agency is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "TravelAgencyPartner not found.")
    require_agency_active(agency)

    order["fulfillment_status"] = "TICKETED"
    order["ticket_number"] = ticket_number
    order["ticketed_at"] = clock_iso()
    order["settlement_status"] = "AGENCY_INVOICED"
    touch(order)
    agency["payable_cents"] = agency["payable_cents"] + order["issuer_cost_provisional_cents"]
    touch(agency)
    return ok(plain(order))


@bp.post("/redemption-orders/<order_id>/refund")
@endpoint(SUPPLIER)
def refund_order(order_id):
    order = must_find("orders", order_id)
    offer = _offer_of(order)
    if offer is not None:
        require_agency_scope(offer["agency_partner_id"])
    closed_reason = req_string(body(), "closed_reason")
    require_state(order, ("TICKETED",), "fulfillment_status")
    account = must_find("accounts", order["account_id"])
    agency = _agency_of(order)

    settled = order["settlement_status"] == "SETTLED"
    order["fulfillment_status"] = "REFUNDED"
    order["closed_reason"] = closed_reason
    order["settlement_status"] = "CLAWED_BACK"
    touch(order)
    append_entry(
        account,
        "REDEEM_REFUND",
        order["points_debited"],
        "REDEMPTION_ORDER",
        order["id"],
        "Points refunded on ticketed booking refund",
    )
    if agency is not None:
        previously_added = (
            order["issuer_cost_final_cents"] if settled else order["issuer_cost_provisional_cents"]
        )
        agency["payable_cents"] = agency["payable_cents"] - (previously_added or 0)
        touch(agency)
    if offer is not None and recompute_seats(offer, release=True):
        touch(offer)
    refresh_account(account)
    touch(account)
    return ok(plain(order))


@bp.post("/redemption-orders/<order_id>/settle")
@endpoint(ADMIN)
def settle_order(order_id):
    order = must_find("orders", order_id)
    data = body()
    invoice_amount_cents = req_int(data, "invoice_amount_cents")
    settlement_adjustment_cents = opt_int(data, "settlement_adjustment_cents", 0)
    require_state(order, ("AGENCY_INVOICED",), "settlement_status")
    require_state(order, ("TICKETED",), "fulfillment_status")

    final_cost = invoice_amount_cents - order["cash_copay_cents"] + settlement_adjustment_cents
    if invoice_amount_cents < 0 or final_cost < 0:
        raise ApiError(
            "ERR_SETTLEMENT_AMOUNT_INVALID",
            "The settlement amounts would drive the final issuer cost below zero.",
        )

    agency = _agency_of(order)
    order["invoice_amount_cents"] = invoice_amount_cents
    order["settlement_adjustment_cents"] = settlement_adjustment_cents
    order["issuer_cost_final_cents"] = final_cost
    order["cost_per_1k_final_cents"] = cost_per_1k(final_cost, order["points_debited"])
    order["settlement_status"] = "SETTLED"
    order["settled_at"] = clock_iso()
    touch(order)
    if agency is not None:
        agency["payable_cents"] = agency["payable_cents"] + (
            final_cost - order["issuer_cost_provisional_cents"]
        )
        touch(agency)
    return ok(plain(order))
