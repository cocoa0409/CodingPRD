"""The early-purchase option: quoting a payoff and accepting it."""

from flask import Blueprint

import clock
import middleware
import response
import validators
from db import base_row, db, public, sort_rows, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("payoff", __name__)


@bp.post("/agreements/<agreement_id>/early-purchase-quotes")
def issue_quote(agreement_id):
    user_id, role = middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    middleware.require_owner(role, user_id, agreement["customer_id"])
    body = validators.json_body()
    expected = validators.integer(body, "expected_agreement_version")

    domain.check_expected_version(agreement, expected)
    domain.check_payment_status(agreement, domain.OP_QUOTE_ISSUE)
    domain.check_possession_status(agreement, domain.OP_QUOTE_ISSUE)

    customer = db.customers.get(agreement["customer_id"])
    rule = domain.pinned_rule(agreement)
    tier_snapshot = customer["loyalty_tier"] if customer else "STANDARD"
    rent_snapshot = agreement["rent_applied_cents"]
    figures = calc.early_purchase_payoff(agreement, rule, rent_snapshot, tier_snapshot)

    now = clock.now()
    for other in sort_rows(domain.agreement_quotes(agreement["id"]), "issued_at"):
        if other["status"] == "OPEN":
            other["status"] = "SUPERSEDED"
            touch(other)

    quote = base_row()
    quote["agreement_id"] = agreement["id"]
    quote["formula_applied"] = figures["formula_applied"]
    quote["rent_applied_snapshot_cents"] = rent_snapshot
    quote["pre_discount_cents"] = figures["pre_discount_cents"]
    quote["loyalty_tier_snapshot"] = tier_snapshot
    quote["loyalty_discount_cents"] = figures["loyalty_discount_cents"]
    quote["late_fee_component_cents"] = figures["late_fee_component_cents"]
    quote["payoff_amount_cents"] = figures["payoff_amount_cents"]
    quote["issued_at"] = clock.fmt(now)
    quote["expires_at"] = clock.fmt(clock.plus_days(now, calc.QUOTE_VALID_DAYS))
    quote["status"] = "OPEN"
    db.quotes[quote["id"]] = quote

    touch(agreement)
    return response.object_response(public(quote), 201)


@bp.get("/agreements/<agreement_id>/early-purchase-quotes")
def list_quotes(agreement_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    rows = domain.agreement_quotes(agreement["id"])
    return common.paged(rows, primary="issued_at", filters=("status",))


@bp.post("/early-purchase-quotes/<quote_id>/accept")
def accept_quote(quote_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
        )
    )
    quote = domain.require_quote(quote_id)
    body = validators.json_body()
    amount = validators.integer(body, "payment_amount_cents", minimum=0)

    agreement = db.agreements.get(quote["agreement_id"])
    domain.check_payment_status(agreement, domain.OP_QUOTE_ACCEPT)
    domain.check_possession_status(agreement, domain.OP_QUOTE_ACCEPT)

    if quote["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    now = clock.now()
    expires_at = clock.parse(quote["expires_at"])
    if expires_at is not None and now > expires_at:
        raise ApiError("ERR_QUOTE_EXPIRED")
    if amount != quote["payoff_amount_cents"]:
        raise ApiError("ERR_PAYOFF_AMOUNT_MISMATCH")

    quote["status"] = "ACCEPTED"
    touch(quote)

    agreement["early_purchase_paid_cents"] = quote["payoff_amount_cents"]
    agreement["late_fee_balance_cents"] = 0
    agreement["reinstatement_fee_balance_cents"] = 0
    agreement["paid_pct"] = 1.0
    agreement["payment_status"] = "CLOSED"
    agreement["possession_status"] = "OWNED"
    touch(agreement)

    touched_stores = set()
    unit = db.units.get(agreement["unit_id"])
    if unit is not None:
        unit["status"] = "SOLD"
        unit["accumulated_rent_received_cents"] += agreement["rent_applied_cents"]
        touch(unit)
        touched_stores.add(unit["store_id"])

    domain.cancel_scheduled_delivery_orders(agreement)
    domain.void_open_tickets(agreement, touched_stores)

    for store_id in sorted(touched_stores):
        store = db.stores.get(store_id)
        if store is not None:
            domain.sync_store(store)

    customer = db.customers.get(agreement["customer_id"])
    if customer is not None:
        domain.append_ledger_entry(
            customer,
            agreement["id"],
            None,
            "EARLY_PAYOFF_BONUS",
            calc.EARLY_PAYOFF_BONUS_POINTS,
        )
    return response.object_response(public(quote))
