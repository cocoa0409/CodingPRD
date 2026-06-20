"""Composite setup helpers for the Donor-Advised Fund API.

These encapsulate the multi-step preambles that most test claims require: opening a
sponsor + account, funding the account with settled cash, vetting a charity, buying into
pools, and walking grants through their lifecycle. All setup calls use get_success_data()
(lenient) so a setup break surfaces as a clear "Setup failed" rather than a confusing
assertion error.

The server starts with an empty database before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_donor_advisor_headers,
    make_grant_officer_headers,
)
from . import factories


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
SPONSOR_ADMIN = TEST_USERS["sponsor_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CONTRIB_ADMIN = TEST_USERS["contribution_admin_headers"]


def advisor_headers(user_id: str) -> dict:
    return make_donor_advisor_headers(user_id)


def officer_headers(user_id: str) -> dict:
    return make_grant_officer_headers(user_id)


# ---------------------------------------------------------------------------
# Tier 1: Base resource creation
# ---------------------------------------------------------------------------
def create_sponsor(**overrides) -> dict:
    payload = factories.create_sponsor_payload(**overrides)
    return get_success_data(api_client.create_sponsor(payload, SPONSOR_ADMIN))


def create_pool(sponsor_id: str, **overrides) -> dict:
    payload = factories.create_pool_payload(sponsor_id, **overrides)
    return get_success_data(api_client.create_pool(payload, SPONSOR_ADMIN))


def create_account(sponsor_id: str, advisor_user_id: str = "adv-1", **overrides) -> dict:
    payload = factories.create_account_payload(sponsor_id, advisor_user_id, **overrides)
    return get_success_data(api_client.create_account(payload, SPONSOR_ADMIN))


def create_charity(sponsor_id: str, **overrides) -> dict:
    payload = factories.create_charity_payload(sponsor_id, **overrides)
    return get_success_data(api_client.create_charity(payload, COMPLIANCE))


def create_vetted_charity(sponsor_id: str, **overrides) -> dict:
    """Register a charity and APPROVE it to VETTED. Returns the vetted charity."""
    charity = create_charity(sponsor_id, **overrides)
    get_success_data(api_client.vet_charity(
        charity["id"], factories.vet_decision_payload("APPROVE"), COMPLIANCE))
    return get_success_data(api_client.get_charity(charity["id"], COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 2: Funded accounts (settled cash)
# ---------------------------------------------------------------------------
def fund_account_with_cash(account_id: str, cash_amount_cents: int, advisor_user_id: str) -> dict:
    """Record a CASH contribution and settle it, crediting the account's cash balance.
    Returns the settled contribution."""
    contrib = get_success_data(api_client.create_contribution(
        factories.create_cash_contribution_payload(account_id, cash_amount_cents),
        advisor_headers(advisor_user_id)))
    return get_success_data(api_client.settle_contribution(contrib["id"], CONTRIB_ADMIN))


def setup_funded_account(cash_amount_cents: int = 1_000_000, advisor_user_id: str = "adv-1",
                         sponsor_overrides=None):
    """Sponsor + ACTIVE account funded with settled cash. Returns (sponsor, account)."""
    sponsor = create_sponsor(**(sponsor_overrides or {}))
    account = create_account(sponsor["id"], advisor_user_id)
    fund_account_with_cash(account["id"], cash_amount_cents, advisor_user_id)
    account = get_success_data(api_client.get_account(account["id"], SPONSOR_ADMIN))
    return sponsor, account


def setup_funded_account_with_vetted_charity(cash_amount_cents: int = 1_000_000,
                                             advisor_user_id: str = "adv-1",
                                             sponsor_overrides=None):
    """Sponsor + VETTED charity + ACTIVE account funded with settled cash.
    Returns (sponsor, charity, account)."""
    sponsor = create_sponsor(**(sponsor_overrides or {}))
    charity = create_vetted_charity(sponsor["id"])
    account = create_account(sponsor["id"], advisor_user_id)
    fund_account_with_cash(account["id"], cash_amount_cents, advisor_user_id)
    account = get_success_data(api_client.get_account(account["id"], SPONSOR_ADMIN))
    return sponsor, charity, account


# ---------------------------------------------------------------------------
# Tier 2b: Pool allocations via rebalance buy
# ---------------------------------------------------------------------------
def buy_into_pool(account_id: str, pool_id: str, amount_cents: int, advisor_user_id: str,
                  target_pct_bps: int = 5000) -> dict:
    """Create + execute a buy rebalance order. Returns the executed order."""
    order = get_success_data(api_client.create_rebalance_order(
        factories.create_rebalance_order_payload(
            account_id, amount_cents, target_pool_id=pool_id, target_pct_bps=target_pct_bps),
        advisor_headers(advisor_user_id)))
    return get_success_data(api_client.execute_rebalance_order(
        order["id"], advisor_headers(advisor_user_id)))


# ---------------------------------------------------------------------------
# Tier 3: Grant lifecycle shortcuts
# ---------------------------------------------------------------------------
def current_account_version(account_id: str) -> int:
    account = get_success_data(api_client.get_account(account_id, SPONSOR_ADMIN))
    return account["version"]


def submit_grant(account_id: str, charity_id: str, amount_cents: int, advisor_user_id: str,
                 **overrides) -> dict:
    """Submit an OCC-guarded grant using the account's current version. Returns the grant."""
    version = current_account_version(account_id)
    payload = factories.create_grant_payload(
        account_id, charity_id, amount_cents, version, **overrides)
    return get_success_data(api_client.create_grant(payload, advisor_headers(advisor_user_id)))


def create_approved_grant(account_id: str, charity_id: str, amount_cents: int,
                          advisor_user_id: str, officer_user_id: str = "officer-1",
                          **grant_overrides) -> dict:
    """Submit a grant then APPROVE it (segregation-of-duties-safe). Returns the approved grant."""
    grant = submit_grant(account_id, charity_id, amount_cents, advisor_user_id, **grant_overrides)
    get_success_data(api_client.approve_grant(grant["id"], officer_headers(officer_user_id)))
    return get_success_data(api_client.get_grant(grant["id"], SPONSOR_ADMIN))


def create_scheduled_grant(account_id: str, charity_id: str, amount_cents: int,
                           advisor_user_id: str, officer_user_id: str = "officer-1",
                           **grant_overrides) -> dict:
    """Submit -> approve -> schedule a grant. Returns the scheduled grant."""
    grant = submit_grant(account_id, charity_id, amount_cents, advisor_user_id, **grant_overrides)
    get_success_data(api_client.approve_grant(grant["id"], officer_headers(officer_user_id)))
    get_success_data(api_client.schedule_grant(grant["id"], officer_headers(officer_user_id)))
    return get_success_data(api_client.get_grant(grant["id"], SPONSOR_ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: Threshold / accumulation targeting
# ---------------------------------------------------------------------------
def setup_account_with_pool_holding(cash_amount_cents: int, buy_amount_cents: int,
                                    advisor_user_id: str = "adv-1",
                                    nav_per_unit_cents: int = 2500, fee_bps: int = 50,
                                    target_pct_bps: int = 5000, sponsor_overrides=None):
    """Sponsor + OPEN pool + ACTIVE account funded with cash, then one executed buy into the pool.
    Returns (sponsor, pool, account, buy_order). The remaining cash is
    cash_amount_cents - buy_amount_cents."""
    sponsor = create_sponsor(**(sponsor_overrides or {}))
    pool = create_pool(sponsor["id"], nav_per_unit_cents=nav_per_unit_cents, fee_bps=fee_bps)
    account = create_account(sponsor["id"], advisor_user_id)
    fund_account_with_cash(account["id"], cash_amount_cents, advisor_user_id)
    buy = buy_into_pool(account["id"], pool["id"], buy_amount_cents, advisor_user_id,
                        target_pct_bps=target_pct_bps)
    account = get_success_data(api_client.get_account(account["id"], SPONSOR_ADMIN))
    return sponsor, pool, account, buy


# ---------------------------------------------------------------------------
# Tier 5: Succession / wind-down / finalization
# ---------------------------------------------------------------------------
def create_confirmed_legacy_plan(account_id: str, beneficiaries: list, advisor_user_id: str) -> dict:
    """Create a LEGACY_GRANTS succession plan and CONFIRM it. Returns the confirmed plan."""
    plan = get_success_data(api_client.create_succession_plan(
        factories.create_succession_plan_payload(account_id, "LEGACY_GRANTS", beneficiaries),
        advisor_headers(advisor_user_id)))
    get_success_data(api_client.confirm_succession_plan(plan["id"], advisor_headers(advisor_user_id)))
    return get_success_data(api_client.get_succession_plan(plan["id"], SPONSOR_ADMIN))


def setup_account_in_wind_down(cash_amount_cents: int, beneficiaries: list,
                               advisor_user_id: str = "adv-1", sponsor=None, account=None):
    """Account funded with settled cash, a CONFIRMED LEGACY_GRANTS plan, moved to WIND_DOWN.

    `beneficiaries` is a list of {charity_id, share_bps} dicts that must already reference
    existing charities. If `sponsor`/`account` are not supplied, a fresh sponsor + account
    are created. Returns (sponsor, account, plan)."""
    if sponsor is None:
        sponsor = create_sponsor()
    if account is None:
        account = create_account(sponsor["id"], advisor_user_id)
        fund_account_with_cash(account["id"], cash_amount_cents, advisor_user_id)
    plan = create_confirmed_legacy_plan(account["id"], beneficiaries, advisor_user_id)
    get_success_data(api_client.wind_down_account(account["id"], SPONSOR_ADMIN))
    account = get_success_data(api_client.get_account(account["id"], SPONSOR_ADMIN))
    return sponsor, account, plan
