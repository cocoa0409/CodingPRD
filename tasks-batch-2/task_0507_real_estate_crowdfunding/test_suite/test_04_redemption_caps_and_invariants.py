"""Redemption-cap window overlap, share-balance overlap, and compensating-action invariants.

Translates difficulty-design instances under resource_temporal_overlap and
compensating_invariant (queue A).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_error,
    set_clock, create_fund, create_share_class, create_approved_investor,
    create_subscription, settle_subscription, post_valuation,
    create_redemption_request, holding_version,
    make_operator_headers, make_investor_headers,
)

OP = make_operator_headers()


# ===========================================================================
# Rule 8a — redemption_cap_aggregate_window_fifo_defer
# ===========================================================================

def test_sweep_fulfills_fifo_until_cap_then_defers(api):
    """PRD §3.7: "The sweep walks that fund's `QUEUED` requests in ascending `queue_seq` order
    (oldest first) and, within a single sweep, accumulates the gross value of the requests it
    fulfills. The window is bounded by a **quarterly redemption cap**: five percent of the fund's
    `total_capital_cents` at the start of the sweep, rounded half up to whole cents."
    PRD §3.7: "A request is fulfilled only when the running fulfilled gross so far plus this
    request's gross value is less than or equal to the cap; a request that would push the running
    total above the cap is not fulfilled but instead **deferred**".

    total_capital 1,000,000 -> cap 50,000. R1 gross 30,000 fulfilled; R2 gross 25,000 deferred
    (30,000+25,000=55,000 > 50,000).

    Design: Difficulty/resource_temporal_overlap/redemption_cap_aggregate_window_fifo_defer
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    r1 = create_redemption_request(holding_id, 30, inv["id"])
    r2 = create_redemption_request(holding_id, 25, inv["id"])

    get_success_data(api.run_redemption_sweep(fund["id"], OP))
    r1_after = get_success_data(api.get_redemption_request(r1["id"], OP))
    r2_after = get_success_data(api.get_redemption_request(r2["id"], OP))
    assert r1_after["status"] == "FULFILLED"
    assert r2_after["status"] == "DEFERRED"


def test_force_fulfill_over_cap_rejected(api):
    """PRD §3.7: "The single-request force-fulfill is subject to the same cap: if fulfilling that
    one request would push fulfilled gross above the quarterly cap, the force-fulfill is rejected
    with `ERR_REDEMPTION_CAP_REACHED` (HTTP 409) rather than silently deferring."

    total_capital 1,000,000 -> cap 50,000; a single request of gross 60,000 exceeds it.

    Design: Difficulty/resource_temporal_overlap/redemption_cap_aggregate_window_fifo_defer
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    rr = create_redemption_request(holding_id, 60, inv["id"])  # gross 60,000
    res = api.force_fulfill_redemption(rr["id"], OP)
    validate_error(res, "ERR_REDEMPTION_CAP_REACHED")


# ===========================================================================
# Rule 8b — holding_share_balance_overlap_on_concurrent_redemptions
# ===========================================================================

def test_second_force_fulfill_exceeds_remaining_balance_rejected(api):
    """PRD §3.7: "Fulfillment ... transitions a request `QUEUED → FULFILLED` ... The request must
    still be `QUEUED`, the fund must not be `WINDING_DOWN`, and the holding's `shares_owned` must
    be at least the `shares_requested`."
    PRD §3.7: "The force-fulfill also enforces the share-sufficiency check and so can surface
    `ERR_INSUFFICIENT_SHARES`."

    Holding 1000 shares: R1 600 fulfilled (-> 400 left), R2 600 then fails the balance check.

    Per PRD §3.1 NAV is net assets / shares (gross_asset moved only by valuation), so the fund is
    created at gross 0 and pegged back to par 1000 by valuations as capital enters. A second
    investor settles 11,000,000 to lift total_capital to 12,000,000 -> 5% cap 600,000, which lets
    R1 (600 shares * 1000 = 600,000) fulfill so the balance check — not the cap — is what blocks R2
    (force-fulfill checks share-sufficiency before the cap, PRD §3.7).

    Design: Difficulty/resource_temporal_overlap/holding_share_balance_overlap_on_concurrent_redemptions
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])  # 1000 shares at par
    holding_id = settled["holding_id"]
    # Peg NAV to 1000 (gross 1,000,000 / 1000), then a second investor settles 11,000,000 at par.
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    inv2 = create_approved_investor(annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub2 = create_subscription(fund["id"], inv2["id"], sc["id"], 11_000_000)
    settle_subscription(sub2["id"])  # 11,000 shares; total_capital -> 12,000,000
    # Peg NAV to 1000 (gross 12,000,000 / 12,000 shares); cap = 5% * 12,000,000 = 600,000.
    post_valuation(fund["id"], period_label="2026-Q2",
                   gross_asset_value_cents=12_000_000, total_liabilities_cents=0)
    r1 = create_redemption_request(holding_id, 600, inv["id"])
    r2 = create_redemption_request(holding_id, 600, inv["id"])
    get_success_data(api.force_fulfill_redemption(r1["id"], OP))  # holding 1000 -> 400
    res = api.force_fulfill_redemption(r2["id"], OP)
    validate_error(res, "ERR_INSUFFICIENT_SHARES")


def test_redemption_create_more_than_owned_rejected(api):
    """PRD §3.7: "the `shares_requested` (a positive quantity, no greater than the holding's
    `shares_owned` at request time) ... A request that is non-positive or exceeds the available
    balance is rejected with `ERR_INSUFFICIENT_SHARES` (HTTP 422)".

    Design: Difficulty/resource_temporal_overlap/holding_share_balance_overlap_on_concurrent_redemptions
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=100_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    hv = holding_version(holding_id)
    from test_helpers import create_redemption_request_payload
    inv_headers = make_investor_headers(inv["id"])
    res = api.create_redemption_request(
        create_redemption_request_payload(holding_id, 2000, hv), inv_headers)
    validate_error(res, "ERR_INSUFFICIENT_SHARES")


# ===========================================================================
# Rule 9a — subscription_reverse_restores_capital_and_shares
# ===========================================================================

def test_reverse_restores_fund_capital_and_shares_to_zero(api):
    """PRD §2.8: "a reversal of a settlement must restore it to exactly the value it would have
    held had the settlement never occurred."
    PRD §3.4: "Reversal is the exact inverse of settlement: the holding's `shares_owned` is
    decreased by `shares_allocated` ... the fund's `shares_outstanding` and `nav_per_share_cents`
    are recomputed; the fund's `total_capital_cents` is decreased by `funded_amount_cents`,
    restoring the conserved quantity exactly".

    Design: Difficulty/compensating_invariant/subscription_reverse_restores_capital_and_shares
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    get_success_data(api.reverse_subscription(sub["id"], OP))
    fund_after = get_success_data(api.get_fund(fund["id"], OP))
    assert fund_after["total_capital_cents"] == 0
    assert fund_after["shares_outstanding"] == 0


def test_reverse_clears_first_acquired_seq_when_holding_empty(api):
    """PRD §3.4: "and if the holding's `shares_owned` reaches zero, its `first_acquired_seq` is
    cleared to null."
    PRD §3.4: "the fund's `total_capital_cents` is decreased by `funded_amount_cents`, restoring
    the conserved quantity exactly".

    Design: Difficulty/compensating_invariant/subscription_reverse_restores_capital_and_shares
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    get_success_data(api.reverse_subscription(sub["id"], OP))
    holding_after = get_success_data(api.get_holding(holding_id, OP))
    assert holding_after["shares_owned"] == 0
    assert holding_after["first_acquired_seq"] is None


# ===========================================================================
# Rule 9b — subscription_reverse_restores_investor_ytd_invested
# ===========================================================================

def test_reverse_restores_investor_ytd_invested_to_zero(api):
    """PRD §3.3: "The investor's `ytd_invested_cents` is a derived figure recomputed after every
    subscription settlement and every subscription reversal ... Reversed subscriptions are excluded
    from this sum, which is what lets a clawback restore the investor's available cap."

    Design: Difficulty/compensating_invariant/subscription_reverse_restores_investor_ytd_invested
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(accredited_status="NON_ACCREDITED",
                                   annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    get_success_data(api.reverse_subscription(sub["id"], OP))
    investor_after = get_success_data(api.get_investor(inv["id"], OP))
    assert investor_after["ytd_invested_cents"] == 0


def test_settle_sets_investor_ytd_invested(api):
    """PRD §3.3: "The investor's `ytd_invested_cents` is a derived figure recomputed after every
    subscription settlement ... it is the sum of `funded_amount_cents` across that investor's
    subscriptions whose `status` is `SETTLED` and whose `tax_year` equals the current UTC year of
    the logical clock."

    Design: Difficulty/compensating_invariant/subscription_reverse_restores_investor_ytd_invested
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(accredited_status="NON_ACCREDITED",
                                   annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    investor_after = get_success_data(api.get_investor(inv["id"], OP))
    assert investor_after["ytd_invested_cents"] == 1_000_000
