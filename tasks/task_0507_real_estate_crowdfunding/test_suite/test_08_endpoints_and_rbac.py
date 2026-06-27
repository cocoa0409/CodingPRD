"""Endpoint-specific behaviors, error catalogue, and role-based access control.

Translates corner-design instances under section: endpoints, section: errors, and section: rbac
(queue B).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    set_clock, create_fund, create_share_class, create_approved_investor, create_investor,
    create_subscription, settle_subscription, post_valuation, create_redemption_request,
    holding_version,
    create_redemption_request_payload,
    make_fund_manager_headers, make_operator_headers, make_investor_headers,
    make_compliance_officer_headers, make_anonymous_headers,
)

FM = make_fund_manager_headers()
OP = make_operator_headers()
CO = make_compliance_officer_headers()
ANON = make_anonymous_headers()


# ---- Section: endpoints ----

def test_holding_drip_toggle_patch_updates_field(api):
    """PRD §3.5: "An `Investor` may toggle `drip_elected` on a holding they own; doing so
    increments the holding's `version`".

    Design: Corner/endpoints/holding_drip_toggle_patch_updates_field
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000, drip_elected=False)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    inv_headers = make_investor_headers(inv["id"])
    patched = get_success_data(api.patch_holding(holding_id, {"drip_elected": True}, inv_headers))
    assert patched["drip_elected"] is True


def test_fund_report_computed_read_returns_derived_totals(api):
    """PRD §2.8: "The platform treats `total_capital_cents` on a fund as a **conserved quantity**:
    ... settled subscriptions add their funded amount".
    PRD §3.1: "A fund report capability is a computed read that returns the fund alongside its
    project-level rollup".

    After a 1,000,000 settle: total_capital_cents 1,000,000 and shares_outstanding 1000.

    Design: Corner/endpoints/fund_report_computed_read_returns_derived_totals
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    report = get_success_data(api.get_fund_report(fund["id"], FM))
    assert report["total_capital_cents"] == 1_000_000
    assert report["shares_outstanding"] == 1000


def test_force_fulfill_over_cap_returns_redemption_cap_reached(api):
    """PRD §3.7: "The single-request force-fulfill is subject to the same cap: if fulfilling that
    one request would push fulfilled gross above the quarterly cap, the force-fulfill is rejected
    with `ERR_REDEMPTION_CAP_REACHED` (HTTP 409) rather than silently deferring."

    total_capital 1,000,000 -> cap 50,000; a single request of gross 60,000 exceeds it.

    Design: Corner/endpoints/force_fulfill_over_cap_returns_redemption_cap_reached
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
    rr = create_redemption_request(holding_id, 60, inv["id"])
    res = api.force_fulfill_redemption(rr["id"], OP)
    validate_error(res, "ERR_REDEMPTION_CAP_REACHED")


# ---- Section: errors ----

def test_redemption_more_than_owned_returns_insufficient_shares(api):
    """PRD §3.7: "A request that is non-positive or exceeds the available balance is rejected with
    `ERR_INSUFFICIENT_SHARES` (HTTP 422)".

    Design: Corner/errors/redemption_more_than_owned_returns_insufficient_shares
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    hv = holding_version(holding_id)
    inv_headers = make_investor_headers(inv["id"])
    res = api.create_redemption_request(
        create_redemption_request_payload(holding_id, 2000, hv), inv_headers)
    validate_error(res, "ERR_INSUFFICIENT_SHARES")


# ---- Section: rbac ----

def test_fund_manager_cannot_approve_suitability_segregation(api):
    """PRD §2.1: "The platform enforces a strict **segregation of duties** between the
    `FundManager` who declares valuations and distributions and the `ComplianceOfficer` who clears
    investors".
    PRD §3.3: "Suitability is gated by a `ComplianceOfficer`, and only by a `ComplianceOfficer` —
    never by the `FundManager`".
    PRD §2.1: "When the headers are valid but the named role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/fund_manager_cannot_approve_suitability_segregation
    """
    inv = create_investor(accredited_status="NON_ACCREDITED",
                          annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    res = api.approve_suitability(inv["id"], FM)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_investor_cannot_settle_subscription_operator_exclusive(api):
    """PRD §2.1: "An `Operator` is the back-office actor that settles and reverses ACH
    subscriptions".
    PRD §2.1: "When the headers are valid but the named role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/investor_cannot_settle_subscription_operator_exclusive
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    inv_headers = make_investor_headers(inv["id"])
    res = api.settle_subscription(sub["id"], inv_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_investor_cannot_cancel_other_investors_subscription(api):
    """PRD §3.4: "this is allowed only while the subscription is `PENDING_ACH` and only by the
    investor who owns it (otherwise `ERR_NOT_RESOURCE_OWNER`)".

    Design: Corner/rbac/investor_cannot_cancel_other_investors_subscription
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv_a = create_approved_investor()
    sub = create_subscription(fund["id"], inv_a["id"], sc["id"], 1_000_000)
    inv_b = create_approved_investor()
    res = api.cancel_subscription(sub["id"], make_investor_headers(inv_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "When either header is missing, or when `X-User-Role` does not name a recognized
    role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_fund(
        {"name": "NoAuth", "vehicle_type": "REIT",
         "gross_asset_value_cents": 0, "total_liabilities_cents": 0}, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")
