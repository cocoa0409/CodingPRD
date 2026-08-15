"""Composite setup helpers (multi-step API preconditions).

Every fixture uses get_success_data() (lenient) so setup failures surface as
clear errors instead of confusing assertion failures.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_kyc_case_payload,
    create_accreditation_payload,
    create_subscription_payload,
    create_nav_period_payload,
    create_funding_payload,
    create_side_letter_payload,
    create_mfn_clause_payload,
    create_redemption_payload,
)
from .test_users import TEST_USERS, make_investor_headers


FA = TEST_USERS["fund_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TA = TEST_USERS["transfer_agent_headers"]
PM = TEST_USERS["portfolio_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_fund(**overrides) -> dict:
    payload = create_fund_payload(**overrides)
    resp = api_client.create_fund(payload, FA)
    return get_success_data(resp)


def create_share_class(fund_id: str, **overrides) -> dict:
    payload = create_share_class_payload(**overrides)
    resp = api_client.create_share_class(fund_id, payload, FA)
    return get_success_data(resp)


def create_investor(**overrides) -> dict:
    payload = create_investor_payload(**overrides)
    resp = api_client.create_investor(payload, FA)
    return get_success_data(resp)


def create_kyc_case(investor_id: str, **overrides) -> dict:
    payload = create_kyc_case_payload(**overrides)
    resp = api_client.create_kyc_case(investor_id, payload, CO)
    return get_success_data(resp)


def create_accreditation(investor_id: str, as_user_id: Optional[str] = None, **overrides) -> dict:
    payload = create_accreditation_payload(**overrides)
    headers = make_investor_headers(as_user_id or investor_id)
    resp = api_client.create_accreditation(investor_id, payload, headers)
    return get_success_data(resp)


def create_nav_period(fund_id: str, **overrides) -> dict:
    payload = create_nav_period_payload(**overrides)
    resp = api_client.create_nav_period(fund_id, payload, FA)
    return get_success_data(resp)


def get_fund(fund_id: str) -> dict:
    resp = api_client.get_fund(fund_id, FA)
    return get_success_data(resp)


def get_investor(investor_id: str) -> dict:
    resp = api_client.get_investor(investor_id, FA)
    return get_success_data(resp)


def get_subscription(fund_id: str, sub_id: str) -> dict:
    resp = api_client.get_subscription(fund_id, sub_id, FA)
    return get_success_data(resp)


def get_capital_account(investor_id: str, account_id: str) -> dict:
    resp = api_client.get_capital_account(investor_id, account_id, FA)
    return get_success_data(resp)


def list_capital_accounts(investor_id: str) -> list:
    resp = api_client.list_capital_accounts(investor_id, FA)
    body = resp.json()
    return body.get("data", [])


def list_series(fund_id: str, class_id: str) -> list:
    resp = api_client.list_series(fund_id, class_id, FA)
    body = resp.json()
    return body.get("data", [])


def list_statements(investor_id: str, account_id: str) -> list:
    resp = api_client.list_statements(investor_id, account_id, FA)
    body = resp.json()
    return body.get("data", [])


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, FA)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — fund + share class + open nav period
# ---------------------------------------------------------------------------

def setup_fund_with_class_and_period(
    fund_overrides: Optional[dict] = None,
    class_overrides: Optional[dict] = None,
    period_end_utc: str = "2026-08-31T23:59:59Z",
) -> tuple:
    """Create Fund + ShareClass + open NavPeriod.

    Returns (fund, share_class, nav_period).
    """
    fund = create_fund(**(fund_overrides or {}))
    share_class = create_share_class(fund["id"], **(class_overrides or {}))
    nav_period = create_nav_period(fund["id"], period_end_utc=period_end_utc)
    return fund, share_class, nav_period


# ---------------------------------------------------------------------------
# Tier 3: full subscription lifecycle — create -> submit -> compliance-approve
#         -> fund -> accept. Returns the subscription plus the capital account
#         created on acceptance.
# ---------------------------------------------------------------------------

def setup_accepted_subscription(
    fund_overrides: Optional[dict] = None,
    class_overrides: Optional[dict] = None,
    investor_overrides: Optional[dict] = None,
    commitment_amount_cents: int = 200000,
    funding_deadline_utc: str = "2026-08-10T00:00:00Z",
    funding_received_at_utc: str = "2026-08-04T00:00:00Z",
    open_nav_period: bool = True,
    period_end_utc: str = "2026-08-31T23:59:59Z",
) -> dict:
    """Bring a subscription all the way to ACCEPTED and return a context dict
    containing: fund, share_class, nav_period (or None), investor, subscription,
    capital_account (first listed)."""
    if open_nav_period:
        fund, share_class, nav_period = setup_fund_with_class_and_period(
            fund_overrides=fund_overrides,
            class_overrides=class_overrides,
            period_end_utc=period_end_utc,
        )
    else:
        fund = create_fund(**(fund_overrides or {}))
        share_class = create_share_class(fund["id"], **(class_overrides or {}))
        nav_period = None

    investor = create_investor(**(investor_overrides or {}))

    sub_resp = api_client.create_subscription(
        fund["id"],
        create_subscription_payload(
            investor_id=investor["id"],
            share_class_id=share_class["id"],
            commitment_amount_cents=commitment_amount_cents,
            funding_deadline_utc=funding_deadline_utc,
        ),
        FA,
    )
    subscription = get_success_data(sub_resp)

    api_client.submit_subscription(fund["id"], subscription["id"], TA)
    api_client.compliance_approve_subscription(fund["id"], subscription["id"], CO)
    api_client.record_funding(
        fund["id"], subscription["id"],
        create_funding_payload(
            amount_cents=commitment_amount_cents,
            received_at_utc=funding_received_at_utc,
        ),
        TA,
    )

    fund_now = get_fund(fund["id"])
    api_client.accept_subscription(
        fund["id"], subscription["id"],
        {"expected_fund_version": fund_now["version"]},
        FA,
    )

    # Refresh the subscription and pull the resulting capital account.
    subscription = get_subscription(fund["id"], subscription["id"])
    cas = list_capital_accounts(investor["id"])
    capital_account = cas[0] if cas else None

    return {
        "fund": get_fund(fund["id"]),
        "share_class": share_class,
        "nav_period": nav_period,
        "investor": investor,
        "subscription": subscription,
        "capital_account": capital_account,
    }


# ---------------------------------------------------------------------------
# Tier 4: side letter under an accepted subscription (EXECUTED)
# ---------------------------------------------------------------------------

def setup_executed_side_letter(ctx: Optional[dict] = None, **side_letter_overrides) -> dict:
    """Given an accepted-subscription context (or create one), attach a DRAFT
    side letter and execute it. Returns ctx extended with side_letter."""
    if ctx is None:
        ctx = setup_accepted_subscription()

    fund = ctx["fund"]
    subscription = ctx["subscription"]

    sl_payload = create_side_letter_payload(
        subscription_id=subscription["id"],
        **side_letter_overrides,
    )
    sl_resp = api_client.create_side_letter(fund["id"], sl_payload, FA)
    side_letter = get_success_data(sl_resp)

    sub_now = get_subscription(fund["id"], subscription["id"])
    api_client.execute_side_letter(
        fund["id"], side_letter["id"],
        {"expected_subscription_version": sub_now["version"]},
        FA,
    )
    ctx["side_letter"] = get_success_data(
        api_client.get_side_letter(fund["id"], side_letter["id"], FA)
    )
    ctx["subscription"] = get_subscription(fund["id"], subscription["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: Redemption request under an accepted subscription
# ---------------------------------------------------------------------------

def setup_redemption_request(
    ctx: Optional[dict] = None,
    requested_amount_cents: int = 100000,
    **red_overrides,
) -> dict:
    """Attach a PENDING RedemptionRequest to an accepted-subscription ctx."""
    if ctx is None:
        ctx = setup_accepted_subscription()

    fund = ctx["fund"]
    nav_period = ctx["nav_period"]
    capital_account = ctx["capital_account"]

    red_resp = api_client.create_redemption(
        fund["id"],
        create_redemption_payload(
            capital_account_id=capital_account["id"],
            requested_amount_cents=requested_amount_cents,
            requested_effective_period_id=nav_period["id"],
            **red_overrides,
        ),
        TA,
    )
    redemption = get_success_data(red_resp)
    ctx["redemption"] = redemption
    return ctx


# ---------------------------------------------------------------------------
# MFN clause helper
# ---------------------------------------------------------------------------

def create_mfn_clause(fund_id: str, **overrides) -> dict:
    payload = create_mfn_clause_payload(**overrides)
    resp = api_client.create_mfn_clause(fund_id, payload, FA)
    return get_success_data(resp)
