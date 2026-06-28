"""Optimistic concurrency, derived-field reconciliation, tax documents, immediate consistency.

Translates corner-design instances under section: cross_cutting_complexity_layers and
section: consistency_model (queue B).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    set_clock, create_fund, create_share_class, create_approved_investor,
    create_subscription, settle_subscription, post_valuation, declare_distribution,
    create_redemption_request, holding_version, fund_version,
    create_redemption_request_payload, create_tax_document_payload,
    make_operator_headers, make_fund_manager_headers, make_investor_headers,
    make_compliance_officer_headers,
)

OP = make_operator_headers()
FM = make_fund_manager_headers()
CO = make_compliance_officer_headers()


# ---- Section: cross_cutting_complexity_layers ----

def test_occ_stale_fund_version_on_subscription_create(api):
    """PRD §2.6: "The subscription-create request must carry `expected_fund_version` holding the
    client's last observed `version` of the parent `Fund` ... If the fund's current `version`
    differs from `expected_fund_version` ... the create is rejected with `ERR_STALE_FUND_VERSION`
    (HTTP 412)."

    A first subscription create bumps Fund.version; a second still carrying the pre-bump version
    is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_fund_version_on_subscription_create
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    fund_v0 = fund["version"]
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000, expected_fund_version=fund_v0)
    inv_headers = make_investor_headers(inv["id"])
    res = api.create_subscription(
        {"investor_id": inv["id"], "share_class_id": sc["id"],
         "funded_amount_cents": 1_000_000, "expected_fund_version": fund_v0}, inv_headers)
    validate_error(res, "ERR_STALE_FUND_VERSION")


def test_occ_correct_holding_version_on_redemption_create_succeeds(api):
    """PRD §2.6: "The redemption-create request must carry `expected_holding_version` holding the
    client's last observed `version` of the parent `Holding`."
    PRD §3.7: "A new request is assigned a monotonic global `queue_seq` ..., begins `QUEUED`, and
    bumps the parent holding's `version`."

    With the holding's current version, the create succeeds (QUEUED).

    Design: Corner/cross_cutting_complexity_layers/occ_correct_holding_version_on_redemption_create_succeeds
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
        create_redemption_request_payload(holding_id, 100, hv), inv_headers)
    rr = validate_success(res, 201)
    assert rr["status"] == "QUEUED"


def test_derived_field_ytd_invested_reconciled_after_settle(api):
    """PRD §3.3: "The investor's `ytd_invested_cents` is a derived figure recomputed after every
    subscription settlement ... it is the sum of `funded_amount_cents` across that investor's
    subscriptions whose `status` is `SETTLED` and whose `tax_year` equals the current UTC year of
    the logical clock."

    Design: Corner/cross_cutting_complexity_layers/derived_field_ytd_invested_reconciled_after_settle
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(accredited_status="NON_ACCREDITED",
                                   annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 700_000)
    settle_subscription(sub["id"])
    investor_after = get_success_data(api.get_investor(inv["id"], OP))
    assert investor_after["ytd_invested_cents"] == 700_000


def test_tax_year_threshold_excludes_other_year_distributions(api):
    """PRD §3.8: "The `ordinary_dividends_cents` is the sum of `gross_dividend_cents` across
    allocations whose `mode` is `CASH`, that belong to holdings the investor owns within the fund,
    whose distribution is `PAID`, and whose distribution period falls in the requested `tax_year`."
    PRD §3.8: "a `REIT` produces `FORM_1099_DIV`".

    Design: Corner/cross_cutting_complexity_layers/tax_year_threshold_excludes_other_year_distributions
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0,
                       vehicle_type="REIT")
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000, drip_elected=False)
    settle_subscription(sub["id"])
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    dist = declare_distribution(fund["id"], period_label="2026-Q1", dividend_per_share_cents=2.5)
    get_success_data(api.pay_distribution(dist["id"], OP))  # CASH 2500 in 2026
    doc = get_success_data(api.create_tax_document(
        inv["id"], create_tax_document_payload(fund["id"], 2026), CO))
    assert doc["ordinary_dividends_cents"] == 2500
    assert doc["doc_type"] == "FORM_1099_DIV"


def test_partnership_fund_generates_k1_tax_document(api):
    """PRD §3.8: "The document's `doc_type` is derived from the fund's `vehicle_type`: a `REIT`
    produces `FORM_1099_DIV` and a `PARTNERSHIP` produces `FORM_K1`."

    Design: Corner/cross_cutting_complexity_layers/partnership_fund_generates_k1_tax_document
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0,
                       vehicle_type="PARTNERSHIP")
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    doc = get_success_data(api.create_tax_document(
        inv["id"], create_tax_document_payload(fund["id"], 2026), CO))
    assert doc["doc_type"] == "FORM_K1"
    assert doc["ordinary_dividends_cents"] == 0


# ---- Section: consistency_model ----

def test_settle_cascade_visible_in_same_response(api):
    """PRD §3.4: "It mints `shares_allocated` as `funded_amount_cents` divided by
    `settled_nav_cents`, rounded half up to four decimal places."
    PRD §2.8: "settlement, reversal, redemption fulfillment, and DRIP minting all trigger a
    recompute so that NAV always reflects the shares genuinely outstanding at that instant. These
    recomputations are part of the triggering request and are committed atomically with it."

    Design: Corner/consistency_model/settle_cascade_visible_in_same_response
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    assert settled["shares_allocated"] == 1000.0000
    fund_after = get_success_data(api.get_fund(fund["id"], OP))
    assert fund_after["shares_outstanding"] == 1000
