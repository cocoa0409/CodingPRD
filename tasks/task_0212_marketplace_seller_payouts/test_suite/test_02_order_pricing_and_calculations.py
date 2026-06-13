"""Order pricing and money calculations.

Translates queue A (Difficulty) dual_variant_calc / combinatorial_formula and
queue B (Corner) calculations-section instances: round-per-component net,
provisional-vs-final divergence, risk score, tiered reserve, refund/chargeback
clawback math, balance statement, 1099-K threshold.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_order_payload,
    create_fee_schedule, create_seller, create_order,
    seller_order_with_applied_refund, seller_order_with_chargeback_received,
    seller_with_scheduled_payout, current_seller_version,
    seller_with_settled_gross, set_clock, advance_clock,
    create_requested_refund, create_chargeback,
    make_finance_headers,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / order_net_round_per_component_then_sum_pinned_order
# ─────────────────────────────────────────────────────────────────────────────

def test_order_net_round_per_component_then_sum(api, finance_headers):
    """PRD §3.4: "The commission, stored in `commission_cents`, is the gross
    multiplied by the schedule's commission basis points divided by ten thousand,
    rounded half-up to whole cents."
    PRD §3.4: "The `processing_fee_cents` is the gross multiplied by the processing
    basis points divided by ten thousand and rounded half-up, then added to the
    fixed processing fee. Each of these three components is rounded to whole cents
    before any summation."

    Design: Difficulty/combinatorial_formula/order_net_round_per_component_then_sum_pinned_order
    """
    set_clock("2026-04-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=12345)
    # commission = round(1851.75) = 1852
    # processing = round(358.005) = 358 + 30 = 388
    # net = 12345 - 1852 - 50 - 388 = 10055
    assert order["commission_cents"] == 1852
    assert order["processing_fee_cents"] == 388
    assert order["net_earnings_cents"] == 10055


def test_order_net_platform_fee_copied_from_schedule(api, finance_headers):
    """PRD §3.4: "The `platform_fee_cents` is copied directly from the schedule's
    fixed fee."
    PRD §3.4: "The provisional `net_earnings_cents` is then the gross minus the
    commission, minus the platform fee, minus the processing fee".

    Design: Difficulty/combinatorial_formula/order_net_round_per_component_then_sum_pinned_order
    """
    set_clock("2026-04-02T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=12345)
    assert order["platform_fee_cents"] == 50
    # net is gross minus the three components, each pre-rounded.
    assert order["net_earnings_cents"] == (
        order["gross_amount_cents"]
        - order["commission_cents"]
        - order["platform_fee_cents"]
        - order["processing_fee_cents"]
    )


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / order_net_provisional_vs_final_diverge_after_partial_refund
# ─────────────────────────────────────────────────────────────────────────────

def test_order_net_provisional_vs_final_diverge_after_partial_refund(api, finance_headers):
    """PRD §3.4: "The provisional `net_earnings_cents` is then the gross minus the
    commission, minus the platform fee, minus the processing fee — with no refund
    yet considered."
    PRD §3.5: "The final `net_earnings_cents` is the provisional net minus the
    seller's net share of any refund, where that share is the cumulative
    `refunded_amount_cents` minus the commission proportional to it — specifically
    the refunded amount minus (the refunded amount multiplied by the order's pinned
    commission basis points divided by ten thousand, rounded half-up)."

    Design: Difficulty/dual_variant_calc/order_net_provisional_vs_final_diverge_after_partial_refund
    """
    set_clock("2026-01-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    # Provisional net captured at creation.
    assert order["net_earnings_cents"] == 8130
    refund = create_requested_refund(order["id"], refund_amount_cents=4000)
    # PRD §3.6: applying the refund recomputes net_earnings_cents to its final
    # form and drives clawback_status to REFUND_CLAWED.
    validate_success(api.apply_refund(refund["id"], finance_headers), 200)
    # final = 8130 - (4000 - round(4000*0.15)) = 8130 - (4000 - 600) = 8130 - 3400 = 4730
    clawed = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert clawed["net_earnings_cents"] == 4730
    # PRD §3.5: "an order matures ... only when ... the order has not been clawed
    # (clawback_status is NONE, since a clawed order does not mature normally)."
    # Advancing the clock past settled_at + 7d must therefore NOT mature this
    # refund-clawed order; its settlement stays PENDING and net stays final.
    advance_clock("2026-01-10T00:00:00Z")
    after = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert after["net_earnings_cents"] == 4730
    assert after["settlement_status"] == "PENDING"
    assert after["clawback_status"] == "REFUND_CLAWED"


def test_order_net_unchanged_at_maturation_when_no_refund(api, finance_headers):
    """PRD §3.5: "If no refund touched the order, provisional and final coincide."

    Design: Difficulty/dual_variant_calc/order_net_provisional_vs_final_diverge_after_partial_refund
    """
    set_clock("2026-01-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    assert order["net_earnings_cents"] == 8130
    advance_clock("2026-01-10T00:00:00Z")
    matured = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert matured["net_earnings_cents"] == 8130
    assert matured["settlement_status"] == "AVAILABLE"


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / seller_risk_score_recomputed_on_chargeback...
# ─────────────────────────────────────────────────────────────────────────────

def test_seller_risk_score_recomputed_on_chargeback_to_high_tier(api, finance_headers):
    """PRD §3.10: "the chargeback rate counts the seller's chargebacks in `RECEIVED`,
    `REPRESENTED`, or `LOST` status".
    PRD §3.10: "The raw score is one hundred multiplied by the sum of the chargeback
    rate weighted by sixty hundredths, the refund rate weighted by twenty-five
    hundredths, and the dispute rate weighted by fifteen hundredths."
    PRD §3.10: "a score of 50 or above is `HIGH`."

    Design: Difficulty/dual_variant_calc/seller_risk_score_recomputed_on_chargeback_distinct_from_order_cost
    """
    set_clock("2026-02-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    create_chargeback(order["id"])
    # chargeback_rate = 1/1 = 1.0; raw = 100 * (0.6 * 1.0) = 60; score 60 → HIGH.
    refetched = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert refetched["seller_risk_score"] == 60
    assert refetched["risk_tier"] == "HIGH"


def test_seller_risk_score_zero_with_no_adverse_events(api, finance_headers):
    """PRD §3.10: "The `risk_tier` follows from the score by threshold: a score below
    20 is `STANDARD`".
    PRD §3.1: "Its computed standing fields — `risk_tier` (`STANDARD`),
    `seller_risk_score` (0) ... all begin at their defaults."

    Design: Difficulty/dual_variant_calc/seller_risk_score_recomputed_on_chargeback_distinct_from_order_cost
    """
    set_clock("2026-02-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    create_order(seller["id"], gross_amount_cents=10000)
    refetched = validate_success(api.get_seller(seller["id"], finance_headers), 200)
    assert refetched["seller_risk_score"] == 0
    assert refetched["risk_tier"] == "STANDARD"


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / payout_reserve_tiered_rate_selection_by_risk_tier
# ─────────────────────────────────────────────────────────────────────────────

def test_payout_reserve_tiered_rate_selection_high_tier(api, finance_headers):
    """PRD §3.9: "the `reserve_withheld_cents` is the available pool multiplied by
    the applicable reserve percentage divided by one hundred, rounded half-up; the
    percentage is selected from the active fee schedule by the seller's `risk_tier`
    — `reserve_pct_standard` for a `STANDARD` seller, `reserve_pct_elevated` for an
    `ELEVATED` seller, `reserve_pct_high` for a `HIGH` seller. The
    `payout_amount_cents` is then the exact remainder, the available pool minus the
    withheld reserve."

    Design: Difficulty/combinatorial_formula/payout_reserve_tiered_rate_selection_by_risk_tier
    """
    set_clock("2026-03-01T00:00:00Z")
    from test_helpers import onboard_active_seller, schedule_payout
    seller, _pm = onboard_active_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    advance_clock("2026-03-10T00:00:00Z")  # matures: +8130 AVAILABLE
    # Chargeback RECEIVED on that order: posts -1500 fee (AVAILABLE pool 6630) and
    # pushes chargeback_rate 1/1 → score 60 → HIGH tier (50%).
    create_chargeback(order["id"])
    payout = schedule_payout(seller["id"])
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    released = validate_success(res, 200)
    # reserve = round(6630 * 50 / 100) = 3315; payout = 6630 - 3315 = 3315.
    assert released["reserve_withheld_cents"] == 3315
    assert released["payout_amount_cents"] == 3315


def test_payout_reserve_standard_tier_zero_reserve(api, finance_headers):
    """PRD §3.9: "the percentage is selected from the active fee schedule by the
    seller's `risk_tier` — `reserve_pct_standard` for a `STANDARD` seller".
    PRD §3.9: "The `payout_amount_cents` is then the exact remainder, the available
    pool minus the withheld reserve."

    Design: Difficulty/combinatorial_formula/payout_reserve_tiered_rate_selection_by_risk_tier
    """
    # STANDARD seller (no adverse events), reserve_pct_standard == 0.
    seller, order, payout, _pm = seller_with_scheduled_payout(gross_amount_cents=10000)
    version = current_seller_version(seller["id"])
    res = api.release_payout(
        payout["id"], {"expected_seller_version": version}, make_finance_headers("finance-2")
    )
    released = validate_success(res, 200)
    # available pool 8130; reserve 0%; payout = 8130.
    assert released["reserve_withheld_cents"] == 0
    assert released["payout_amount_cents"] == 8130


# ─────────────────────────────────────────────────────────────────────────────
# Corner / calculations
# ─────────────────────────────────────────────────────────────────────────────

def test_refund_clawback_returns_proportional_commission(api, finance_headers):
    """PRD §3.6: "When the refund applies, the platform computes, in pinned order,
    the `commission_returned_cents` first — the refund amount multiplied by the
    order's commission basis points divided by ten thousand, rounded half-up — and
    then the `clawback_cents` as the refund amount minus that returned commission."

    Design: Corner/calculations/refund_clawback_returns_proportional_commission
    """
    set_clock("2026-03-05T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    refund = create_requested_refund(order["id"], refund_amount_cents=4000)
    applied = validate_success(api.apply_refund(refund["id"], finance_headers), 200)
    # commission_returned = round(4000 * 0.15) = 600; clawback = 4000 - 600 = 3400.
    assert applied["commission_returned_cents"] == 600
    assert applied["clawback_cents"] == 3400


def test_chargeback_lost_claws_full_gross_plus_flat_fee(api, finance_headers):
    """PRD §3.7: "That `dispute_fee_cents` is fixed at fifteen hundred cents and is
    posted at once as a negative `CHARGEBACK_FEE` ledger entry".
    PRD §3.7: "the platform computes `clawback_cents` as the order's entire
    `gross_amount_cents` — no commission proportionality, unlike a refund — and
    posts a negative `CHARGEBACK_CLAWBACK` ledger entry for that full gross".

    Design: Corner/calculations/chargeback_lost_claws_full_gross_plus_flat_fee
    """
    set_clock("2026-03-06T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=20000)
    cb = create_chargeback(order["id"])
    from test_helpers import make_seller_headers
    validate_success(api.represent_chargeback(cb["id"], make_seller_headers(seller["id"])), 200)
    decided = validate_success(
        api.decide_chargeback(cb["id"], {"outcome": "LOST"}, finance_headers), 200
    )
    assert decided["dispute_fee_cents"] == 1500
    assert decided["clawback_cents"] == 20000
    assert decided["chargeback_status"] == "LOST"


def test_balance_statement_credits_and_debits_from_ledger(api, finance_headers):
    """PRD §3.12: "`total_credits_cents` is the sum of positive ledger amounts posted
    in the period, `total_debits_cents` is the sum of negative ledger amounts posted
    in the period".

    Design: Corner/calculations/balance_statement_credits_and_debits_from_ledger
    """
    # order +8130 proceeds and refund 4000 applied (-3400 clawback), all in 2026-03.
    seller, order, refund = seller_order_with_applied_refund(
        order_gross=10000, refund_amount=4000, settle_iso="2026-03-05T00:00:00Z"
    )
    res = api.create_balance_statement(
        {"seller_id": seller["id"], "period_year": 2026, "period_month": 3}, finance_headers
    )
    stmt = validate_success(res, 201)
    assert stmt["total_credits_cents"] == 8130
    assert stmt["total_debits_cents"] == -3400


def test_form_1099k_below_threshold_force_issues_with_basis_none(api, finance_headers):
    """PRD §3.11: "With `force` true, the form issues anyway with its basis recorded
    as `NONE`."
    PRD §3.11: "The `gross_reported_cents` is the sum of `gross_amount_cents` over
    the seller's orders whose `settled_at` year equals the `tax_year` and whose
    `settlement_status` is `AVAILABLE` or `PAID`".

    Design: Corner/calculations/form_1099k_below_threshold_force_issues_with_basis_none
    """
    seller, orders, form = seller_with_settled_gross(
        total_gross=499900, num_orders=1, tax_year=2026,
        settle_iso="2026-02-05T00:00:00Z", mature_iso="2026-02-15T00:00:00Z",
    )
    issued = validate_success(api.issue_tax_form(form["id"], {"force": True}, finance_headers), 200)
    assert issued["form_status"] == "ISSUED"
    assert issued["threshold_basis"] == "NONE"
    assert issued["gross_reported_cents"] == 499900
