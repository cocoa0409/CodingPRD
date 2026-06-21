"""Prepaid charge (pinned floor-once-on-aggregate rounding), the dual-variant
cancellation refund (prepaid-amortized vs period-proration), and the
money-conservation invariant across prepay -> cancel -> refund.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    prepay_payload, cancel_payload,
    set_clock, get_subscription, get_subscriber,
    setup_subscription, setup_prepaid_subscription,
    create_plan, create_subscriber, create_subscription,
    list_wallet_entries, list_invoices_for_subscription,
)

ADMIN = TEST_USERS["curation_admin_headers"]


# ─── combinatorial_formula: prepaid charge floor-once (queue A, >=2 tests) ───

def test_prepaid_charge_discount_floored_once_on_aggregate_gross(api):
    """PRD §3.4: "the discount in cents is the floor of that whole gross multiplied
    by the plan's `prepaid_discount_pct`; the discount is floored exactly once on
    the summed gross, never per period (flooring per period and then summing would
    yield a different, larger discount loss). The prepaid total paid is the gross
    minus the floored discount."

    period_price 3335, term 3, discount 0.10: gross=10005,
    floor(10005*0.10)=floor(1000.5)=1000, total=10005-1000=9005.

    Design: Difficulty/combinatorial_formula/prepaid_charge_discount_floored_once_on_aggregate_gross
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="ODD", period_price_cents=3335,
                       prepaid_terms_offered=[3], prepaid_discount_pct=0.10)
    subscriber = create_subscriber(email="odd@x.com", full_name="Odd S")
    sub = create_subscription(subscriber, plan)
    headers = make_subscriber_headers(subscriber["id"])
    res = api.prepay_subscription(sub["id"], prepay_payload(3, sub["version"]), headers)
    updated = validate_success(res, 200)
    assert updated["billing_status"] == "PREPAID"
    assert updated["prepaid_periods_remaining"] == 3

    invoices = [i for i in list_invoices_for_subscription(sub["id"]) if i["kind"] == "PREPAID_CHARGE"]
    assert len(invoices) == 1, f"expected one PREPAID_CHARGE invoice, got {len(invoices)}"
    assert invoices[0]["gross_amount_cents"] == 9005, (
        f"floor-once-on-aggregate total must be 9005, got {invoices[0]['gross_amount_cents']}")


def test_prepaid_unit_value_floored_after_aggregate_discount(api):
    """PRD §3.4: "sets `prepaid_unit_value_cents` to the amortized per-period value
    (the floor of the prepaid total paid divided by the term length)".

    total=9005, term=3: floor(9005/3)=floor(3001.66)=3001.

    Design: Difficulty/combinatorial_formula/prepaid_charge_discount_floored_once_on_aggregate_gross
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="ODD2", period_price_cents=3335,
                       prepaid_terms_offered=[3], prepaid_discount_pct=0.10)
    subscriber = create_subscriber(email="odd2@x.com", full_name="Odd S2")
    sub = create_subscription(subscriber, plan)
    headers = make_subscriber_headers(subscriber["id"])
    res = api.prepay_subscription(sub["id"], prepay_payload(3, sub["version"]), headers)
    updated = validate_success(res, 200)
    assert updated["prepaid_unit_value_cents"] == 3001, (
        f"unit value must be floor(9005/3)=3001, got {updated['prepaid_unit_value_cents']}")


# ─── dual_variant_calc: cancellation refund (queue A, >=2 tests) ────────────

def test_cancel_refund_prepaid_amortized_variant(api):
    """PRD §3.5: "Under the **prepaid-amortized** variant, which applies when
    `billing_status` is `PREPAID` at cancel time, the refund is
    `prepaid_periods_remaining` multiplied by `prepaid_unit_value_cents`".
    PRD §3.3: "creates an `Invoice` of kind `CANCEL_REFUND` (a negative
    `gross_amount_cents`) together with a `WalletEntry` of kind `REFUND_CREDIT`
    for the refund amount."

    6000/period, 6 periods, 0.10 discount: gross=36000, discount=3600, total=32400,
    unit=floor(32400/6)=5400, refund=6*5400=32400.

    Design: Difficulty/dual_variant_calc/cancel_refund_prepaid_amortized_vs_period_proration
    """
    ctx = setup_prepaid_subscription(period_price_cents=6000, term_periods=6,
                                     prepaid_discount_pct=0.10)
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.cancel_subscription(sub["id"], cancel_payload("IMMEDIATE"), headers)
    cancelled = validate_success(res, 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    subscriber = get_subscriber(ctx["subscriber"]["id"])
    assert subscriber["wallet_balance_cents"] == 32400, (
        f"amortized refund must credit 32400, got {subscriber['wallet_balance_cents']}")

    entries = list_wallet_entries(ctx["subscriber"]["id"])
    refunds = [e for e in entries if e["kind"] == "REFUND_CREDIT"]
    assert len(refunds) == 1, f"expected one REFUND_CREDIT, got {len(refunds)}"
    assert refunds[0]["amount_cents"] == 32400


def test_cancel_refund_period_proration_variant(api):
    """PRD §3.5: "Under the **period-proration** variant, which applies when
    `billing_status` is `CURRENT` (pay-as-you-go) at cancel time, the refund is
    the sum of `amount_charged_cents` over every unshipped `CURRENT`-funded paid
    billing cycle — the full per-period price comes back for each period not yet
    shipped".

    Pay-as-you-go: period-1 charged 6000, never shipped -> refund 6000.

    Design: Difficulty/dual_variant_calc/cancel_refund_prepaid_amortized_vs_period_proration
    """
    ctx = setup_subscription(plan_overrides={"period_price_cents": 6000})
    sub = ctx["subscription"]
    assert sub["billing_status"] == "CURRENT"
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.cancel_subscription(sub["id"], cancel_payload("IMMEDIATE"), headers)
    cancelled = validate_success(res, 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    subscriber = get_subscriber(ctx["subscriber"]["id"])
    assert subscriber["wallet_balance_cents"] == 6000, (
        f"period-proration refund must credit the full unshipped period price 6000, "
        f"got {subscriber['wallet_balance_cents']}")
    entries = [e for e in list_wallet_entries(ctx["subscriber"]["id"]) if e["kind"] == "REFUND_CREDIT"]
    assert len(entries) == 1 and entries[0]["amount_cents"] == 6000


# ─── compensating_invariant: money conserved (queue A, >=2 tests) ───────────

def test_money_conserved_prepay_then_cancel_refund_wallet(api):
    """PRD §3.5: "the refund is `prepaid_periods_remaining` multiplied by
    `prepaid_unit_value_cents`".
    PRD §3.2: "A `subscriber`'s `wallet_balance_cents` is always the running sum of
    the `amount_cents` of every `WalletEntry` whose `subscriber_id` matches that
    subscriber".

    For a prepaid term fully refunded before any box ships, the credited refund
    equals the prepaid total paid (32400) with zero drift.

    Design: Difficulty/compensating_invariant/money_conserved_across_prepay_then_cancel_refund
    """
    ctx = setup_prepaid_subscription(period_price_cents=6000, term_periods=6,
                                     prepaid_discount_pct=0.10)
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    validate_success(api.cancel_subscription(sub["id"], cancel_payload("IMMEDIATE"), headers), 200)

    entries = [e for e in list_wallet_entries(ctx["subscriber"]["id"]) if e["kind"] == "REFUND_CREDIT"]
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 32400, "refund credit equals prepaid total paid"
    subscriber = get_subscriber(ctx["subscriber"]["id"])
    assert subscriber["wallet_balance_cents"] == 32400, "wallet lands at the prepaid total, no drift"


def test_money_conserved_prepay_then_cancel_refund_invoice(api):
    """PRD §3.3: "creates an `Invoice` of kind `CANCEL_REFUND` (a negative
    `gross_amount_cents`)".
    PRD §3.5: "the refund is `prepaid_periods_remaining` multiplied by
    `prepaid_unit_value_cents`".

    The CANCEL_REFUND invoice mirrors the credit as a negative: -32400.

    Design: Difficulty/compensating_invariant/money_conserved_across_prepay_then_cancel_refund
    """
    ctx = setup_prepaid_subscription(period_price_cents=6000, term_periods=6,
                                     prepaid_discount_pct=0.10)
    sub = ctx["subscription"]
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    validate_success(api.cancel_subscription(sub["id"], cancel_payload("IMMEDIATE"), headers), 200)

    refund_invoices = [i for i in list_invoices_for_subscription(sub["id"]) if i["kind"] == "CANCEL_REFUND"]
    assert len(refund_invoices) == 1, f"expected one CANCEL_REFUND invoice, got {len(refund_invoices)}"
    assert refund_invoices[0]["gross_amount_cents"] == -32400, (
        f"CANCEL_REFUND gross must be -32400, got {refund_invoices[0]['gross_amount_cents']}")


# ─── validations corner: prepay term not offered ────────────────────────────

def test_prepay_term_not_offered_rejected(api):
    """PRD §3.4: "only when `term_periods` is a member of the plan's
    `prepaid_terms_offered`; a term that the plan does not offer is rejected with
    `ERR_PREPAID_TERM_NOT_OFFERED`."

    Design: Corner/validations/prepay_term_not_offered_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="PT", period_price_cents=6000,
                       prepaid_terms_offered=[6], prepaid_discount_pct=0.10)
    subscriber = create_subscriber(email="pt@x.com", full_name="PT S")
    sub = create_subscription(subscriber, plan)
    headers = make_subscriber_headers(subscriber["id"])
    res = api.prepay_subscription(sub["id"], prepay_payload(4, sub["version"]), headers)
    validate_error(res, ApiErrorId.ERR_PREPAID_TERM_NOT_OFFERED.value, expected_status=422)
