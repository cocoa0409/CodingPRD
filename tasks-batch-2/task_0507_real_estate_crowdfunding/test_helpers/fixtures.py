"""Composite setup helpers for the Real Estate Crowdfunding API.

Every fixture builds its preconditions from scratch via PRD-declared endpoints, using
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.

Identity threading: the Investor role is entity_backed, so subscription / redemption / holding
creates and cancels are made with make_investor_headers(investor["id"]) — never the shared
constant — to satisfy the ownership gate (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_fund_payload,
    create_share_class_payload,
    create_project_payload,
    create_investor_payload,
    create_valuation_payload,
    create_distribution_payload,
    create_subscription_payload,
    create_redemption_request_payload,
)
from .test_users import (
    make_fund_manager_headers,
    make_compliance_officer_headers,
    make_operator_headers,
    make_investor_headers,
    make_anonymous_headers,
)

FM = make_fund_manager_headers()
CO = make_compliance_officer_headers()
OP = make_operator_headers()
ANON = make_anonymous_headers()


# --- Tier 0: logical clock ---

def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §2.9). Operator/FundManager only."""
    return get_success_data(api_client.set_clock(to_iso8601, headers=OP))


# --- Tier 1: single-entity creation ---

def create_fund(**overrides) -> dict:
    """Create a fund in OPEN. Returns the fund dict (carries version)."""
    return get_success_data(api_client.create_fund(create_fund_payload(**overrides), headers=FM))


def create_share_class(fund_id, **overrides) -> dict:
    """Create an OFFERING share class under a fund. Returns the share class dict."""
    return get_success_data(api_client.create_share_class(
        fund_id, create_share_class_payload(**overrides), headers=FM))


def create_project(fund_id, **overrides) -> dict:
    """Create an ACQUIRED project under a fund. Returns the project dict."""
    return get_success_data(api_client.create_project(
        fund_id, create_project_payload(**overrides), headers=FM))


def create_investor(**overrides) -> dict:
    """Register an investor (PENDING suitability). Returns the investor dict."""
    return get_success_data(api_client.create_investor(create_investor_payload(**overrides), headers=ANON))


def create_approved_investor(**overrides) -> dict:
    """Register an investor and approve suitability (PENDING -> APPROVED).
    Returns the approved investor dict (re-read)."""
    investor = create_investor(**overrides)
    get_success_data(api_client.approve_suitability(investor["id"], headers=CO))
    return get_success_data(api_client.get_investor(investor["id"], headers=CO))


def post_valuation(fund_id, **overrides) -> dict:
    """Post a valuation against a fund (advances current_valuation_seq, recomputes NAV).
    Returns the valuation dict."""
    return get_success_data(api_client.create_valuation(
        fund_id, create_valuation_payload(**overrides), headers=FM))


def declare_distribution(fund_id, **overrides) -> dict:
    """Declare a DECLARED distribution under a fund. Returns the distribution dict."""
    return get_success_data(api_client.create_distribution(
        fund_id, create_distribution_payload(**overrides), headers=FM))


# --- Tier 2: subscription / settlement helpers ---

def fund_version(fund_id) -> int:
    """Read the fund's current version (for the OCC guard on subscription create)."""
    return get_success_data(api_client.get_fund(fund_id, headers=OP))["version"]


def holding_version(holding_id) -> int:
    """Read the holding's current version (for the OCC guard on redemption create)."""
    return get_success_data(api_client.get_holding(holding_id, headers=OP))["version"]


def create_subscription(fund_id, investor_id, share_class_id, funded_amount_cents,
                        expected_fund_version=None, **overrides) -> dict:
    """Create a PENDING_ACH subscription owned by investor_id. Reads the fund version if
    expected_fund_version is not supplied. Returns the subscription dict."""
    if expected_fund_version is None:
        expected_fund_version = fund_version(fund_id)
    inv_headers = make_investor_headers(investor_id)
    return get_success_data(api_client.create_subscription(
        create_subscription_payload(investor_id, share_class_id, funded_amount_cents,
                                    expected_fund_version, **overrides),
        headers=inv_headers))


def settle_subscription(subscription_id) -> dict:
    """Settle a PENDING_ACH subscription (Operator). Returns the SETTLED subscription dict
    (carries holding_id, settled_nav_cents, shares_allocated)."""
    return get_success_data(api_client.settle_subscription(subscription_id, headers=OP))


def create_settled_holding(fund_id, share_class_id, funded_amount_cents=1_000_000,
                           investor_overrides=None, sub_overrides=None) -> tuple:
    """Create an approved investor, subscribe funded_amount_cents, and settle it into a holding.

    Returns (investor, subscription_settled, holding) where holding is the re-read Holding dict.
    """
    investor = create_approved_investor(**(investor_overrides or {}))
    sub = create_subscription(fund_id, investor["id"], share_class_id, funded_amount_cents,
                              **(sub_overrides or {}))
    settled = settle_subscription(sub["id"])
    holding = get_success_data(api_client.get_holding(settled["holding_id"], headers=OP))
    return investor, settled, holding


def setup_fund_share_class(fund_overrides=None, share_class_overrides=None) -> tuple:
    """Create a fund + one OFFERING share class. Returns (fund, share_class)."""
    fund = create_fund(**(fund_overrides or {}))
    sc = create_share_class(fund["id"], **(share_class_overrides or {}))
    return fund, sc


def setup_fund_with_settled_holding(funded_amount_cents=1_000_000, clock=None,
                                    fund_overrides=None, share_class_overrides=None,
                                    investor_overrides=None) -> tuple:
    """Fund + OFFERING share class + one approved investor with a settled holding.

    Returns (fund, share_class, investor, subscription, holding).
    """
    if clock is not None:
        set_clock(clock)
    fund, sc = setup_fund_share_class(fund_overrides, share_class_overrides)
    investor, sub, holding = create_settled_holding(
        fund["id"], sc["id"], funded_amount_cents,
        investor_overrides=investor_overrides)
    return fund, sc, investor, sub, holding


def advance_valuations(fund_id, count, base_period_year=2026, gross=1_000_000, liabilities=0):
    """Post `count` valuations against the fund (advancing current_valuation_seq by count),
    each holding gross/liabilities constant so NAV is unchanged. Returns nothing useful."""
    quarter = 1
    year = base_period_year
    for _ in range(count):
        post_valuation(fund_id, period_label=f"{year}-Q{quarter}",
                       gross_asset_value_cents=gross, total_liabilities_cents=liabilities)
        quarter += 1
        if quarter > 4:
            quarter = 1
            year += 1


# --- Tier 3: redemption helpers ---

def create_redemption_request(holding_id, shares_requested, investor_id,
                              expected_holding_version=None) -> dict:
    """Create a QUEUED redemption request on a holding owned by investor_id.
    Reads the holding version if not supplied. Returns the redemption request dict."""
    if expected_holding_version is None:
        expected_holding_version = holding_version(holding_id)
    inv_headers = make_investor_headers(investor_id)
    return get_success_data(api_client.create_redemption_request(
        create_redemption_request_payload(holding_id, shares_requested, expected_holding_version),
        headers=inv_headers))


def setup_holding_with_queued_redemptions(funded_amount_cents=1_000_000,
                                          shares_list=(30, 25),
                                          clock="2026-03-01T00:00:00Z",
                                          fund_overrides=None,
                                          investor_overrides=None,
                                          valuation_overrides=None):
    """Fund + share class + settled holding + one posted valuation, then a series of QUEUED
    redemption requests sized by shares_list (in order, threading holding version each time).

    Returns (fund, share_class, investor, holding, [redemption_requests...]).
    """
    fund, sc, investor, sub, holding = setup_fund_with_settled_holding(
        funded_amount_cents=funded_amount_cents, clock=clock,
        fund_overrides=fund_overrides, investor_overrides=investor_overrides)
    post_valuation(fund["id"], **(valuation_overrides or {
        "period_label": "2026-Q1",
        "gross_asset_value_cents": fund_overrides.get("gross_asset_value_cents", 1_000_000)
        if fund_overrides else 1_000_000,
        "total_liabilities_cents": 0,
    }))
    requests = []
    for shares in shares_list:
        rr = create_redemption_request(holding["id"], shares, investor["id"])
        requests.append(rr)
    holding = get_success_data(api_client.get_holding(holding["id"], headers=OP))
    return fund, sc, investor, holding, requests


# --- Tier 4: distribution / DRIP helpers ---

def setup_three_holdings_for_distribution(per_subscription_cents=33_000,
                                          drip_elected=False,
                                          drip_eligible=True,
                                          clock="2026-03-01T00:00:00Z",
                                          gross_asset_value_cents=99_000,
                                          dividend_per_share_cents=1.5):
    """Fund + share class + three approved investors each settling per_subscription_cents at
    NAV 1000 (so each holds per/1000 shares), then a valuation and a DECLARED distribution.

    Per PRD §3.1 the NAV is (gross_asset - liabilities) / shares_outstanding, recomputed after
    every settlement, and a fund's gross_asset_value_cents is NOT touched by settlement (only by
    a valuation). So a fund created with a fixed gross_asset_value would have its NAV spike off
    par after the first settle. To keep every settle priced at par 1000 (the precondition these
    distribution tests rely on), this helper pegs the NAV back to 1000 before each settle by
    posting a valuation that sets gross_asset = current_shares * 1000 — a PRD-faithful way to
    hold the price at par as capital enters. A final valuation pegs the fund to
    gross_asset_value_cents at distribution time so the dividend NAV is exactly
    gross_asset_value_cents / (3 * per_subscription_cents / 1000).
    """
    set_clock(clock)
    # Start at gross 0 so the bootstrap (shares==0) prices the first settle at par 1000.
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=1000, drip_eligible=drip_eligible)
    holdings = []
    val_seq = 0
    for i in range(3):
        if i > 0:
            # Peg NAV to par 1000 before this settle: gross = current shares * 1000.
            cur = get_success_data(api_client.get_fund(fund["id"], headers=OP))
            shares_now = cur["shares_outstanding"]
            val_seq += 1
            post_valuation(fund["id"], period_label=f"peg-{val_seq}",
                           gross_asset_value_cents=int(round(shares_now * 1000)),
                           total_liabilities_cents=0)
        investor = create_approved_investor()
        sub = create_subscription(fund["id"], investor["id"], sc["id"], per_subscription_cents,
                                  drip_elected=drip_elected)
        settled = settle_subscription(sub["id"])
        holdings.append(get_success_data(api_client.get_holding(settled["holding_id"], headers=OP)))
    # Final valuation: set gross_asset to the requested figure so the dividend-time NAV is
    # gross_asset_value_cents / shares_outstanding (1000 when gross == shares * 1000).
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=gross_asset_value_cents, total_liabilities_cents=0)
    dist = declare_distribution(fund["id"], period_label="2026-Q1",
                                dividend_per_share_cents=dividend_per_share_cents)
    return fund, sc, holdings, dist
