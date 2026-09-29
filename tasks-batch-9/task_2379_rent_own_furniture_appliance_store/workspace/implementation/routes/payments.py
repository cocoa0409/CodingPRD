"""Renewal payments: the five-bucket waterfall, loyalty and reversal."""

from flask import Blueprint

import clock
import middleware
import response
import validators
from db import base_row, db, public, sort_rows, touch
from errors import ApiError
from routes import common
from services import calc, domain

bp = Blueprint("payments", __name__)

METHODS = ("CASH", "CARD", "ACH", "MONEY_ORDER")
REVERSAL_REASONS = ("CHARGEBACK", "NSF", "POSTING_ERROR")


def _cure(agreement, customer, window):
    """The cure cascade of PRD 3.6, run backwards from the delinquency one."""
    agreement["payment_status"] = "CURRENT"
    if window is not None:
        window["status"] = "USED"
        touch(window)
    agreement["collections_stage"] = "NONE"
    domain.sync_customer(customer)


@bp.post("/agreements/<agreement_id>/renewal-payments")
def post_payment(agreement_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.COLLECTIONS_AGENT,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    body = validators.json_body()
    amount = validators.raw_integer(body, "amount_cents")
    method = validators.enum(body, "payment_method", METHODS)
    validators.boolean(body, "apply_customer_credit", required=False, default=False)

    domain.check_payment_status(agreement, domain.OP_PAYMENT)
    domain.check_possession_status(agreement, domain.OP_PAYMENT)

    if amount < 1:
        raise ApiError("ERR_INVALID_PAYMENT_AMOUNT")
    remaining_rent = (
        agreement["total_of_payments_cents"] - agreement["rent_applied_cents"]
    )
    ceiling = (
        remaining_rent
        + agreement["late_fee_balance_cents"]
        + agreement["reinstatement_fee_balance_cents"]
    )
    if amount > ceiling:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    customer = db.customers.get(agreement["customer_id"])
    now = clock.now()
    status_before = agreement["payment_status"]
    tier_before = customer["loyalty_tier"] if customer else "STANDARD"

    due_before = clock.parse(agreement["current_period_due_at"])
    days_late = 0
    if due_before is not None:
        days_late = max(0, clock.whole_days_between(now, due_before))

    # ---- bucket 1: late fees
    rem = amount
    bucket_late = min(rem, agreement["late_fee_balance_cents"])
    rem -= bucket_late

    # ---- bucket 2: the reinstatement fee, only inside a live window
    window = domain.open_window(agreement["id"])
    bucket_reinstatement = 0
    if window is not None:
        expires_at = clock.parse(window["expires_at"])
        if expires_at is not None and now <= expires_at:
            bucket_reinstatement = min(
                rem, agreement["reinstatement_fee_balance_cents"]
            )
            rem -= bucket_reinstatement

    # ---- bucket 3: rent, drawing the carried partial credit into the pool
    partial_before = agreement["partial_credit_cents"]
    rent_pool = rem + partial_before
    periods_remaining = agreement["renewal_count"] - agreement["periods_paid"]
    rate = agreement["renewal_rate_cents"]
    periods_advanced = min(rent_pool // rate, periods_remaining) if rate > 0 else 0
    bucket_rent = periods_advanced * rate
    leftover = rent_pool - bucket_rent

    # ---- buckets 4 and 5: the split on term completion
    term_complete = agreement["periods_paid"] + periods_advanced >= agreement[
        "renewal_count"
    ]
    if not term_complete:
        bucket_partial = leftover
        bucket_credit = 0
        agreement["partial_credit_cents"] = leftover
    else:
        bucket_partial = 0
        bucket_credit = leftover
        agreement["partial_credit_cents"] = 0
        agreement["customer_credit_contributed_cents"] += leftover
        if customer is not None and leftover:
            customer["credit_balance_cents"] += leftover
            touch(customer)

    agreement["periods_paid"] += periods_advanced
    agreement["late_fee_paid_cents"] += bucket_late
    agreement["reinstatement_fee_paid_cents"] += bucket_reinstatement
    domain.sync_agreement_money(agreement)

    payment = base_row()
    payment["agreement_id"] = agreement["id"]
    payment["amount_cents"] = amount
    payment["payment_method"] = method
    payment["posted_at"] = clock.fmt(now)
    payment["status"] = "POSTED"
    payment["days_late"] = days_late
    payment["allocation_late_fee_cents"] = bucket_late
    payment["allocation_reinstatement_fee_cents"] = bucket_reinstatement
    payment["allocation_rent_cents"] = bucket_rent
    payment["allocation_partial_credit_cents"] = bucket_partial
    payment["partial_credit_before_cents"] = partial_before
    payment["allocation_customer_credit_cents"] = bucket_credit
    payment["periods_advanced"] = periods_advanced
    payment["loyalty_points_awarded"] = 0
    payment["cured_delinquency"] = False
    payment["reversed_at"] = None
    payment["reversal_reason"] = "NONE"
    db.payments[payment["id"]] = payment

    # ---- the cure test
    if status_before == "DELINQUENT":
        due_after = clock.parse(agreement["current_period_due_at"])
        cured = (
            agreement["late_fee_balance_cents"] == 0
            and agreement["reinstatement_fee_balance_cents"] == 0
            and due_after is not None
            and due_after > now
        )
        if cured:
            payment["cured_delinquency"] = True
            _cure(agreement, customer, window)

    # ---- term completion closes the books
    if (
        agreement["periods_paid"] >= agreement["renewal_count"]
        and agreement["late_fee_balance_cents"] == 0
        and agreement["reinstatement_fee_balance_cents"] == 0
        and agreement["payment_status"] == "CURRENT"
        and agreement["possession_status"] == "DELIVERED"
    ):
        agreement["payment_status"] = "CLOSED"
        agreement["possession_status"] = "OWNED"
        unit = db.units.get(agreement["unit_id"])
        if unit is not None:
            unit["status"] = "SOLD"
            touch(unit)
            store = db.stores.get(unit["store_id"])
            if store is not None:
                domain.sync_store(store)

    # ---- loyalty accrual reads the tier as it stood before the posting
    points = calc.loyalty_points_for_payment(
        tier_before, periods_advanced, bucket_rent, days_late
    )
    payment["loyalty_points_awarded"] = points
    if points and customer is not None:
        domain.append_ledger_entry(
            customer, agreement["id"], payment["id"], "PAYMENT_ACCRUAL", points
        )
    elif customer is not None:
        domain.sync_customer(customer)

    touch(agreement)
    return response.object_response(public(payment), 201)


@bp.get("/agreements/<agreement_id>/renewal-payments")
def list_payments(agreement_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.COLLECTIONS_AGENT,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    rows = domain.agreement_payments(agreement["id"])
    return common.paged(rows, primary="posted_at", filters=("status",))


@bp.post("/renewal-payments/<payment_id>/reverse")
def reverse_payment(payment_id):
    middleware.authenticate((middleware.PLATFORM_ADMIN, middleware.STORE_MANAGER))
    payment = domain.require_payment(payment_id)
    body = validators.json_body()
    reason = validators.enum(body, "reason", REVERSAL_REASONS)

    agreement = db.agreements.get(payment["agreement_id"])
    if payment["status"] != "POSTED":
        raise ApiError("ERR_PAYMENT_NOT_REVERSIBLE")
    latest = domain.latest_posted_payment(payment["agreement_id"])
    if latest is None or latest["id"] != payment["id"]:
        raise ApiError("ERR_PAYMENT_NOT_REVERSIBLE")

    now = clock.now()
    customer = db.customers.get(agreement["customer_id"]) if agreement else None

    payment["status"] = "REVERSED"
    payment["reversed_at"] = clock.fmt(now)
    payment["reversal_reason"] = reason
    touch(payment)

    agreement["late_fee_paid_cents"] -= payment["allocation_late_fee_cents"]
    agreement["reinstatement_fee_paid_cents"] -= payment[
        "allocation_reinstatement_fee_cents"
    ]
    agreement["periods_paid"] -= payment["periods_advanced"]
    agreement["partial_credit_cents"] = payment["partial_credit_before_cents"]
    if payment["allocation_customer_credit_cents"] > 0:
        agreement["customer_credit_contributed_cents"] -= payment[
            "allocation_customer_credit_cents"
        ]
        if customer is not None:
            customer["credit_balance_cents"] -= payment[
                "allocation_customer_credit_cents"
            ]
            touch(customer)
    domain.sync_agreement_money(agreement)

    # the compensating ledger entry is the exact negation of the accrual
    if payment["loyalty_points_awarded"] and customer is not None:
        domain.append_ledger_entry(
            customer,
            agreement["id"],
            payment["id"],
            "PAYMENT_REVERSAL",
            -payment["loyalty_points_awarded"],
        )

    if payment["cured_delinquency"]:
        agreement["payment_status"] = "DELINQUENT"
        agreement["collections_stage"] = "ADVERSE"
        if customer is not None:
            customer["lifetime_delinquency_count"] += 1
            touch(customer)
        used = [
            w
            for w in domain.agreement_windows(agreement["id"])
            if w["status"] == "USED"
        ]
        window = sort_rows(used)[-1] if used else None
        if window is not None:
            expires_at = clock.parse(window["expires_at"])
            if expires_at is not None and now <= expires_at:
                window["status"] = "OPEN"
            else:
                window["status"] = "EXPIRED"
                agreement["payment_status"] = "DEFAULTED"
            touch(window)

    if customer is not None:
        domain.sync_customer(customer)
    touch(agreement)
    return response.object_response(public(payment))


@bp.get("/agreements/<agreement_id>/reinstatement-windows")
def list_windows(agreement_id):
    middleware.authenticate(
        (
            middleware.PLATFORM_ADMIN,
            middleware.COMPLIANCE_OFFICER,
            middleware.STORE_MANAGER,
            middleware.SALES_ASSOCIATE,
            middleware.COLLECTIONS_AGENT,
            middleware.CUSTOMER,
        )
    )
    agreement = domain.require_agreement(agreement_id)
    rows = domain.agreement_windows(agreement["id"])
    return common.paged(rows, primary="opened_at", filters=("status",))
