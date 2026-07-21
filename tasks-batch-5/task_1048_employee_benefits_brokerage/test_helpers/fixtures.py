"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every test.
All setup calls use get_success_data (lenient) so failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_client_contact_headers,
    make_compliance_headers,
    make_platform_admin_headers,
)

CONSULTANT = TEST_USERS["consultant_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------
def create_client(**overrides) -> dict:
    resp = api_client.create_client(f.create_client_payload(**overrides), CONSULTANT)
    return get_success_data(resp)


def create_member(client_id, **overrides) -> dict:
    resp = api_client.create_census_member(
        f.create_census_member_payload(client_id, **overrides), CONSULTANT
    )
    return get_success_data(resp)


def set_clock(to_iso8601) -> None:
    get_success_data(api_client.set_clock(to_iso8601, make_platform_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 2: marketing -> selected quote -> bound / active policy
# ---------------------------------------------------------------------------
def create_selected_quote(client_id, coverage_line="MEDICAL",
                          monthly_premium_cents=500_000, commission_rate_pct=0.04,
                          target_effective_date="2026-01-01") -> dict:
    """Campaign -> open -> quote -> select. Returns the SELECTED quote dict."""
    camp = get_success_data(api_client.create_campaign(
        f.create_campaign_payload(client_id, coverage_line=coverage_line,
                                  target_effective_date=target_effective_date),
        CONSULTANT))
    get_success_data(api_client.open_campaign(camp["id"], CONSULTANT))
    quote = get_success_data(api_client.create_quote(
        f.create_quote_payload(camp["id"], monthly_premium_cents=monthly_premium_cents,
                               commission_rate_pct=commission_rate_pct),
        CARRIER))
    get_success_data(api_client.select_quote(quote["id"], CONSULTANT))
    return get_success_data(api_client.get_quote(quote["id"], CONSULTANT))


def bind_policy(client_id, coverage_line="MEDICAL", monthly_premium_cents=500_000,
                commission_rate_pct=0.04, effective_date="2026-01-01",
                expiration_date="2026-12-31") -> dict:
    """Selected quote -> POST /policies. Returns the BOUND policy dict."""
    quote = create_selected_quote(client_id, coverage_line=coverage_line,
                                  monthly_premium_cents=monthly_premium_cents,
                                  commission_rate_pct=commission_rate_pct)
    policy = get_success_data(api_client.create_policy(
        f.create_policy_payload(client_id, quote["id"],
                                effective_date=effective_date,
                                expiration_date=expiration_date),
        CONSULTANT))
    return policy


def activate_policy(client_id, coverage_line="MEDICAL", monthly_premium_cents=500_000,
                    commission_rate_pct=0.04, effective_date="2026-01-01",
                    expiration_date="2026-12-31") -> dict:
    """Bind + activate. Returns the ACTIVE policy dict (version reflects activation)."""
    policy = bind_policy(client_id, coverage_line=coverage_line,
                         monthly_premium_cents=monthly_premium_cents,
                         commission_rate_pct=commission_rate_pct,
                         effective_date=effective_date,
                         expiration_date=expiration_date)
    return get_success_data(api_client.activate_policy(policy["id"], CONSULTANT))


def setup_client_with_active_policy(coverage_line="MEDICAL",
                                    monthly_premium_cents=500_000,
                                    commission_rate_pct=0.04,
                                    effective_date="2026-01-01",
                                    expiration_date="2026-12-31",
                                    **client_overrides):
    """Returns (client, active_policy)."""
    client = create_client(**client_overrides)
    policy = activate_policy(client["id"], coverage_line=coverage_line,
                             monthly_premium_cents=monthly_premium_cents,
                             commission_rate_pct=commission_rate_pct,
                             effective_date=effective_date,
                             expiration_date=expiration_date)
    return client, policy


# ---------------------------------------------------------------------------
# Tier 3: renewals
# ---------------------------------------------------------------------------
def open_renewal(policy, initial_offer_premium_cents=900_000) -> dict:
    """Open a renewal against an ACTIVE policy using the policy's current version."""
    return get_success_data(api_client.create_renewal(
        f.create_renewal_payload(policy["id"], policy["version"],
                                 initial_offer_premium_cents=initial_offer_premium_cents),
        CONSULTANT))


def setup_open_renewal(coverage_line="MEDICAL", monthly_premium_cents=1_000_000,
                       commission_rate_pct=0.04, initial_offer_premium_cents=900_000):
    """Returns (client, active_policy, open_renewal)."""
    client, policy = setup_client_with_active_policy(
        coverage_line=coverage_line, monthly_premium_cents=monthly_premium_cents,
        commission_rate_pct=commission_rate_pct)
    renewal = open_renewal(policy, initial_offer_premium_cents=initial_offer_premium_cents)
    return client, policy, renewal


# ---------------------------------------------------------------------------
# Tier 4: enrollment windows + elections
# ---------------------------------------------------------------------------
def create_scheduled_window(client_id, opens_at="2026-07-01T00:00:00Z",
                            closes_at="2026-07-31T00:00:00Z", plan_year=2026) -> dict:
    return get_success_data(api_client.create_enrollment_window(
        f.create_enrollment_window_payload(client_id, plan_year=plan_year,
                                            opens_at=opens_at, closes_at=closes_at),
        CONSULTANT))


def create_open_window(client_id, opens_at="2026-07-01T00:00:00Z",
                       closes_at="2026-07-31T00:00:00Z", plan_year=2026) -> dict:
    win = create_scheduled_window(client_id, opens_at=opens_at, closes_at=closes_at,
                                  plan_year=plan_year)
    return get_success_data(api_client.open_window(win["id"], CONSULTANT))


def create_election(client_id, window_id, member_id, policy_id,
                    coverage_tier="EMPLOYEE_ONLY") -> dict:
    """Create a SELECTED election as the owning ClientContact."""
    return get_success_data(api_client.create_election(
        f.create_election_payload(window_id, member_id, policy_id,
                                  coverage_tier=coverage_tier),
        make_client_contact_headers(client_id)))


def confirm_election(client_id, election_id) -> dict:
    return get_success_data(api_client.confirm_election(
        election_id, make_client_contact_headers(client_id)))


def setup_enrollment_scenario(members=1, coverage_tier="EMPLOYEE_ONLY",
                              monthly_premium_cents=500_000,
                              opens_at="2026-07-01T00:00:00Z",
                              closes_at="2026-07-31T00:00:00Z"):
    """Client + ACTIVE policy + OPEN window + N members each with a SELECTED
    election of coverage_tier. Returns
    (client, policy, window, [members], [elections])."""
    client, policy = setup_client_with_active_policy(
        monthly_premium_cents=monthly_premium_cents)
    window = create_open_window(client["id"], opens_at=opens_at, closes_at=closes_at)
    member_list, election_list = [], []
    tiers = coverage_tier if isinstance(coverage_tier, list) else [coverage_tier] * members
    for i in range(members):
        m = create_member(client["id"], full_name=f"Member {i}")
        e = create_election(client["id"], window["id"], m["id"], policy["id"],
                            coverage_tier=tiers[i])
        member_list.append(m)
        election_list.append(e)
    return client, policy, window, member_list, election_list


# ---------------------------------------------------------------------------
# Tier 5: compliance filings
# ---------------------------------------------------------------------------
def create_filing(client_id, filing_type="ACA_1094C", plan_year=2026,
                  due_date="2027-03-31T00:00:00Z", officer_id="officer-a") -> dict:
    return get_success_data(api_client.create_filing(
        f.create_filing_payload(client_id, filing_type=filing_type,
                                plan_year=plan_year, due_date=due_date),
        make_compliance_headers(officer_id)))


def create_prepared_filing(client_id, filing_type="ACA_1094C", plan_year=2026,
                           due_date="2027-03-31T00:00:00Z", officer_id="officer-a") -> dict:
    filing = create_filing(client_id, filing_type=filing_type, plan_year=plan_year,
                           due_date=due_date, officer_id=officer_id)
    return get_success_data(api_client.prepare_filing(
        filing["id"], make_compliance_headers(officer_id)))


# ---------------------------------------------------------------------------
# Tier 6: stop-loss
# ---------------------------------------------------------------------------
def create_stop_loss(client_id, attachment_point_cents=5_000_000,
                     aggregate_limit_cents=50_000_000, wellness_credit_pct=0.05) -> dict:
    return get_success_data(api_client.create_stop_loss_policy(
        f.create_stop_loss_payload(client_id,
                                   attachment_point_cents=attachment_point_cents,
                                   aggregate_limit_cents=aggregate_limit_cents,
                                   wellness_credit_pct=wellness_credit_pct),
        CONSULTANT))


def record_claim(sl_id, claim_amount_cents) -> dict:
    return get_success_data(api_client.record_claim(
        sl_id, {"claim_amount_cents": claim_amount_cents}, CONSULTANT))
