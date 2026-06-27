"""Validation precedence conflicts and cross-entity state-dependency gates.

Translates difficulty-design instances under priority_pair_validation_conflict and
cross_entity_state_dependency (queue A).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_error,
    set_clock, create_fund, create_share_class, create_investor, create_approved_investor,
    create_subscription, settle_subscription, fund_version, holding_version,
    create_redemption_request,
    make_operator_headers, make_fund_manager_headers, make_investor_headers,
    create_redemption_request_payload,
)

OP = make_operator_headers()
FM = make_fund_manager_headers()


# ===========================================================================
# Rule 5a — suitability_safety_beats_annual_cap_fiscal
# ===========================================================================

def test_settle_reports_suitability_before_annual_cap(api):
    """PRD §3.9: "For a settle, the suitability gate (`ERR_SUITABILITY_NOT_APPROVED`) is checked
    before the accreditation gate (`ERR_ACCREDITATION_REQUIRED`), which is checked before the
    annual cap (`ERR_ANNUAL_CAP_EXCEEDED`)."

    A NON_ACCREDITED, NOT-approved investor with a funded amount over the cap: the suitability
    gate (priority earlier) fires -> ERR_SUITABILITY_NOT_APPROVED, not ERR_ANNUAL_CAP_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/suitability_safety_beats_annual_cap_fiscal
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    # Cap = 10% of max(8,000,000, 12,000,000) = 1,200,000; funded 2,000,000 would exceed it.
    inv = create_investor(accredited_status="NON_ACCREDITED",
                          annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 2_000_000)
    res = api.settle_subscription(sub["id"], OP)
    validate_error(res, "ERR_SUITABILITY_NOT_APPROVED")


def test_settle_suitability_gate_fires_for_pending_investor(api):
    """PRD §3.4: "The investor must have `suitability_status` of `APPROVED`, or the settle is
    rejected with `ERR_SUITABILITY_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/suitability_safety_beats_annual_cap_fiscal
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_investor(accredited_status="ACCREDITED",
                          annual_income_cents=50_000_000, net_worth_cents=50_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    res = api.settle_subscription(sub["id"], OP)
    validate_error(res, "ERR_SUITABILITY_NOT_APPROVED")


# ===========================================================================
# Rule 5b — occ_state_beats_offering_referential_on_subscription_create
# ===========================================================================

def test_subscription_create_stale_version_beats_closed_offering(api):
    """PRD §3.9: "State eligibility for the requested transition follows (`ERR_INVALID_STATE`).
    The optimistic-concurrency version checks come next on the two guarded creates
    (`ERR_STALE_FUND_VERSION` for subscription create, `ERR_STALE_HOLDING_VERSION` for redemption
    create)."
    PRD §3.9: "After those structural gates, business rules apply in order. For a subscription
    create, the offering-open check (`ERR_OFFERING_NOT_OPEN`) precedes the minimum-investment
    floor".

    A create carrying the pre-close fund version against a now CLOSED_TO_NEW fund is both stale and
    against a closed offering: the OCC check (structural) fires first -> ERR_STALE_FUND_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_offering_referential_on_subscription_create
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    fund_v0 = fund["version"]
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    get_success_data(api.close_fund_to_new(fund["id"], FM))  # bumps Fund.version

    inv_headers = make_investor_headers(inv["id"])
    res = api.create_subscription(
        {"investor_id": inv["id"], "share_class_id": sc["id"],
         "funded_amount_cents": 1_000_000, "expected_fund_version": fund_v0},
        inv_headers)
    validate_error(res, "ERR_STALE_FUND_VERSION")


def test_subscription_create_stale_fund_version_rejected(api):
    """PRD §2.6: "If the fund's current `version` differs from `expected_fund_version` — which
    happens whenever another writer has posted a valuation or settled a subscription since the
    client last read the fund ... the create is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_offering_referential_on_subscription_create
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    fund_v0 = fund["version"]
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    # First create bumps Fund.version; the second still carries fund_v0 (stale).
    create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000, expected_fund_version=fund_v0)
    inv_headers = make_investor_headers(inv["id"])
    res = api.create_subscription(
        {"investor_id": inv["id"], "share_class_id": sc["id"],
         "funded_amount_cents": 1_000_000, "expected_fund_version": fund_v0},
        inv_headers)
    validate_error(res, "ERR_STALE_FUND_VERSION")


# ===========================================================================
# Rule 7a — subscription_settle_requires_investor_approved
# ===========================================================================

def test_settle_requires_investor_approved(api):
    """PRD §3.4: "The investor must have `suitability_status` of `APPROVED`, or the settle is
    rejected with `ERR_SUITABILITY_NOT_APPROVED` (HTTP 409)."

    A subscription whose accredited investor is left PENDING cannot settle.

    Design: Difficulty/cross_entity_state_dependency/subscription_settle_requires_investor_approved
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_investor(accredited_status="ACCREDITED",
                          annual_income_cents=50_000_000, net_worth_cents=50_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    res = api.settle_subscription(sub["id"], OP)
    validate_error(res, "ERR_SUITABILITY_NOT_APPROVED")


def test_settle_succeeds_once_investor_approved(api):
    """PRD §3.4: "Settlement is where capital actually enters the fund, and it is an `Operator`
    action that transitions `PENDING_ACH → SETTLED`."
    PRD §3.4: "The investor must have `suitability_status` of `APPROVED`, or the settle is rejected
    with `ERR_SUITABILITY_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/subscription_settle_requires_investor_approved
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    assert settled["status"] == "SETTLED"


# ===========================================================================
# Rule 7b — redemption_fulfill_requires_fund_not_winding_down
# ===========================================================================

def test_redemption_create_rejected_on_winding_down_fund(api):
    """PRD §3.7: "a request whose fund is `WINDING_DOWN` is rejected with `ERR_FUND_WINDING_DOWN`".

    Design: Difficulty/cross_entity_state_dependency/redemption_fulfill_requires_fund_not_winding_down
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    hv = holding_version(holding_id)
    get_success_data(api.wind_down_fund(fund["id"], FM))

    inv_headers = make_investor_headers(inv["id"])
    res = api.create_redemption_request(
        create_redemption_request_payload(holding_id, 100, hv), inv_headers)
    validate_error(res, "ERR_FUND_WINDING_DOWN")


def test_redemption_sweep_forbidden_on_winding_down_fund(api):
    """PRD §3.7: "The sweep itself is forbidden while the fund is `WINDING_DOWN`
    (`ERR_FUND_WINDING_DOWN`)."

    Design: Difficulty/cross_entity_state_dependency/redemption_fulfill_requires_fund_not_winding_down
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    create_share_class(fund["id"], min_investment_cents=100_000)
    get_success_data(api.wind_down_fund(fund["id"], FM))
    res = api.run_redemption_sweep(fund["id"], OP)
    validate_error(res, "ERR_FUND_WINDING_DOWN")
