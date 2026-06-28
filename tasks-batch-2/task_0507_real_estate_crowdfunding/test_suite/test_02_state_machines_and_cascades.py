"""Non-linear state-machine cycles and transitive cascade chains.

Translates difficulty-design instances under non_linear_state_machine and transitive_cascade
(queue A).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success,
    set_clock, create_fund, create_share_class, create_investor, create_approved_investor,
    create_subscription, settle_subscription, post_valuation, declare_distribution,
    create_redemption_request, holding_version, fund_version,
    setup_three_holdings_for_distribution, setup_fund_with_settled_holding,
    make_operator_headers, make_compliance_officer_headers, make_investor_headers,
    make_fund_manager_headers,
)

OP = make_operator_headers()
CO = make_compliance_officer_headers()
FM = make_fund_manager_headers()


# ===========================================================================
# Rule 3a — redemption_cyclic_queued_deferred_queued
# ===========================================================================

def test_redemption_cyclic_queued_deferred_requeued_fulfilled(api):
    """PRD §3.7: "a request that would push the running total above the cap is not fulfilled but
    instead **deferred**, transitioning `QUEUED → DEFERRED` while retaining its `queue_seq`".
    PRD §3.7: "When a window reopens, an `Operator` moves the fund's deferred requests back into
    the queue, transitioning each `DEFERRED → QUEUED` and incrementing its `version`, so a
    deferred request can be picked up by a subsequent sweep."
    PRD §3.7: "The full cycle is therefore `QUEUED → DEFERRED → QUEUED → (sweep) → FULFILLED`."

    Design: Difficulty/non_linear_state_machine/redemption_cyclic_queued_deferred_queued
    """
    set_clock("2026-03-01T00:00:00Z")
    # total_capital 1,000,000 -> cap 50,000. NAV 1000.
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)

    r1 = create_redemption_request(holding_id, 30, inv["id"])  # gross 30000
    r2 = create_redemption_request(holding_id, 25, inv["id"])  # gross 25000

    # First sweep: R1 fulfilled (30000 <= 50000); R2 deferred (30000+25000=55000 > 50000).
    get_success_data(api.run_redemption_sweep(fund["id"], OP))
    r2_after = get_success_data(api.get_redemption_request(r2["id"], OP))
    assert r2_after["status"] == "DEFERRED"

    # Reopen window: R2 DEFERRED -> QUEUED.
    get_success_data(api.open_redemption_window(fund["id"], OP))
    r2_requeued = get_success_data(api.get_redemption_request(r2["id"], OP))
    assert r2_requeued["status"] == "QUEUED"

    # Second sweep fulfils R2 (cap recomputed from the now-lower total_capital).
    get_success_data(api.run_redemption_sweep(fund["id"], OP))
    r1_final = get_success_data(api.get_redemption_request(r1["id"], OP))
    r2_final = get_success_data(api.get_redemption_request(r2["id"], OP))
    assert r1_final["status"] == "FULFILLED"
    assert r2_final["status"] == "FULFILLED"


def test_redemption_deferred_request_retains_queue_seq(api):
    """PRD §3.7: "a request that would push the running total above the cap is not fulfilled but
    instead **deferred**, transitioning `QUEUED → DEFERRED` while retaining its `queue_seq`, with
    no holding or fund mutation and only its `version` incremented."

    Design: Difficulty/non_linear_state_machine/redemption_cyclic_queued_deferred_queued
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
    seq_before = r2["queue_seq"]
    get_success_data(api.run_redemption_sweep(fund["id"], OP))
    r2_after = get_success_data(api.get_redemption_request(r2["id"], OP))
    assert r2_after["status"] == "DEFERRED"
    assert r2_after["queue_seq"] == seq_before


# ===========================================================================
# Rule 3b — investor_suitability_cyclic_approved_pending_approved
# ===========================================================================

def test_investor_suitability_cycle_approved_revoked_reapproved(api):
    """PRD §3.3: "The officer may also revoke a prior approval, transitioning `APPROVED → PENDING`,
    which increments `version` and returns the investor to review. Because of that revoke path, an
    investor may legitimately cycle through approval more than once."
    PRD §3.3: "The officer may approve a pending investor, transitioning `suitability_status` from
    `PENDING` to `APPROVED`; this is allowed only when the investor is `PENDING`".

    Design: Difficulty/non_linear_state_machine/investor_suitability_cyclic_approved_pending_approved
    """
    inv = create_investor(accredited_status="NON_ACCREDITED",
                          annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    get_success_data(api.approve_suitability(inv["id"], CO))
    revoked = get_success_data(api.revoke_suitability(inv["id"], CO))
    assert revoked["suitability_status"] == "PENDING"
    reapproved = get_success_data(api.approve_suitability(inv["id"], CO))
    assert reapproved["suitability_status"] == "APPROVED"


def test_investor_revoke_returns_to_pending(api):
    """PRD §3.3: "The officer may also revoke a prior approval, transitioning `APPROVED → PENDING`,
    which increments `version` and returns the investor to review."

    Design: Difficulty/non_linear_state_machine/investor_suitability_cyclic_approved_pending_approved
    """
    inv = create_investor(accredited_status="NON_ACCREDITED",
                          annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    approved = get_success_data(api.approve_suitability(inv["id"], CO))
    assert approved["suitability_status"] == "APPROVED"
    revoked = get_success_data(api.revoke_suitability(inv["id"], CO))
    assert revoked["suitability_status"] == "PENDING"
    assert revoked["version"] > approved["version"]


# ===========================================================================
# Rule 4a — distribution_pay_drip_chain_dist_holding_fund
# ===========================================================================

def test_distribution_pay_drip_chain_mints_shares_and_recomputes_fund(api):
    """PRD §3.6: "For a `DRIP` allocation the system computes `drip_shares` as
    `gross_dividend_cents` divided by the fund's `nav_per_share_cents`, rounded half up to four
    decimal places, then increases that holding's `shares_owned` by `drip_shares`".
    PRD §3.6: "and `drip_shares_minted` accumulates the new shares minted across all DRIP
    allocations. After the DRIP minting, the fund's `shares_outstanding` and `nav_per_share_cents`
    are recomputed."

    3 DRIP holdings of 33 shares: each gross round(33*1.5)=50; drip_shares round(50/1000,4)=0.0500;
    total minted 0.1500; shares_outstanding 99 + 0.15 = 99.1500.

    Design: Difficulty/transitive_cascade/distribution_pay_drip_chain_dist_holding_fund
    """
    fund, sc, holdings, dist = setup_three_holdings_for_distribution(
        per_subscription_cents=33_000, drip_elected=True, drip_eligible=True,
        gross_asset_value_cents=99_000, dividend_per_share_cents=1.5)
    paid = get_success_data(api.pay_distribution(dist["id"], OP))
    assert paid["drip_shares_minted"] == 0.1500
    fund_after = get_success_data(api.get_fund(fund["id"], OP))
    assert fund_after["shares_outstanding"] == 99.1500


def test_distribution_pay_drip_increases_holding_shares(api):
    """PRD §3.6: "For a `DRIP` allocation the system computes `drip_shares` as
    `gross_dividend_cents` divided by the fund's `nav_per_share_cents`, rounded half up to four
    decimal places, then increases that holding's `shares_owned` by `drip_shares` and its
    `cost_basis_cents` by `gross_dividend_cents`".

    Design: Difficulty/transitive_cascade/distribution_pay_drip_chain_dist_holding_fund
    """
    fund, sc, holdings, dist = setup_three_holdings_for_distribution(
        per_subscription_cents=33_000, drip_elected=True, drip_eligible=True,
        gross_asset_value_cents=99_000, dividend_per_share_cents=1.5)
    target = holdings[0]
    get_success_data(api.pay_distribution(dist["id"], OP))
    holding_after = get_success_data(api.get_holding(target["id"], OP))
    # 33.0000 + drip_shares 0.0500 = 33.0500.
    assert holding_after["shares_owned"] == 33.0500


# ===========================================================================
# Rule 4b — fund_wind_down_cascade_shareclass_and_redemption
# ===========================================================================

def test_wind_down_cascades_share_class_to_closed_and_redemption_to_rejected(api):
    """PRD §3.7: "When a `FundManager` transitions a fund to `WINDING_DOWN`, the system, in the
    same atomic request, transitions every share class of that fund whose status is `OFFERING` or
    `SUSPENDED` to `CLOSED` (each incrementing its `version`), and transitions every redemption
    request against that fund's holdings whose status is `QUEUED` or `DEFERRED` to `REJECTED`
    (each incrementing its `version`)".

    Design: Difficulty/transitive_cascade/fund_wind_down_cascade_shareclass_and_redemption
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
    rr = create_redemption_request(holding_id, 100, inv["id"])

    get_success_data(api.wind_down_fund(fund["id"], FM))
    sc_after = get_success_data(api.get_share_class(sc["id"], OP))
    rr_after = get_success_data(api.get_redemption_request(rr["id"], OP))
    assert sc_after["status"] == "CLOSED"
    assert rr_after["status"] == "REJECTED"


def test_wind_down_sets_fund_status_winding_down(api):
    """PRD §3.1: "A `FundManager` may also wind a fund down, transitioning it to `WINDING_DOWN`
    from either `OPEN` or `CLOSED_TO_NEW`. Winding down is terminal and is the origin of a cascade
    described in Section 3.7."

    Design: Difficulty/transitive_cascade/fund_wind_down_cascade_shareclass_and_redemption
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    create_share_class(fund["id"], min_investment_cents=100_000)
    wound = get_success_data(api.wind_down_fund(fund["id"], FM))
    assert wound["status"] == "WINDING_DOWN"
