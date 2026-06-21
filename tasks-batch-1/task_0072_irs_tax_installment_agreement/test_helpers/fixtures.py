"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures. Every
fixture builds its preconditions from scratch — the harness restarts the server
with an empty database before each test.

Standard clock instant used across temporal scenarios: 2024-04-15 (3 full months
after the canonical 2024-01-15 assessment date).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_tax_account_payload,
    create_tax_period_payload,
    create_agreement_payload,
    create_offer_payload,
    create_csed_suspension_payload,
    create_payment_payload,
    create_lien_payload,
)
from .test_users import (
    TEST_USERS,
    make_revenue_officer_headers,
    make_case_reviewer_headers,
)

OFFICER = TEST_USERS["revenue_officer_headers"]
REVIEWER = TEST_USERS["case_reviewer_headers"]

CLOCK_3MO = "2024-04-15T00:00:00.000Z"
ASSESSMENT_3MO = "2024-01-15T00:00:00.000Z"


# ─── Tier 0: Clock ────────────────────────────────────────────────────────

def set_clock(instant: str):
    """Set the server logical clock to `instant`."""
    return get_success_data(api_client.set_clock(instant, OFFICER))


# ─── Tier 1: Account + Period scaffolding ─────────────────────────────────

def create_account(**overrides):
    """Create a tax account. Returns the account dict."""
    return get_success_data(
        api_client.create_tax_account(create_tax_account_payload(**overrides), OFFICER))


def create_period(account_id, **overrides):
    """Create a tax period on the account. Returns the period dict."""
    return get_success_data(
        api_client.create_tax_period(create_tax_period_payload(account_id, **overrides), OFFICER))


def get_account_version(account_id):
    """Read the account's current version (for OCC expected_tax_account_version)."""
    acct = get_success_data(api_client.get_tax_account(account_id, OFFICER))
    return acct["version"]


def setup_account_with_recomputed_period(
        assessed_tax_cents=1000000,
        assessment_date=ASSESSMENT_3MO,
        clock=CLOCK_3MO,
        mdi_cents=300000,
        tax_year=2023,
        **acct_overrides):
    """Clock -> account -> one period -> recompute. Returns (account_dict, period_dict).

    After recompute the single 1,000,000-cent period at 3 months elapsed carries
    penalty 15000 + interest 18000, balance 1033000.
    """
    if clock is not None:
        set_clock(clock)
    acct = create_account(monthly_disposable_income_cents=mdi_cents, **acct_overrides)
    period = create_period(
        acct["id"], assessed_tax_cents=assessed_tax_cents,
        assessment_date=assessment_date, tax_year=tax_year)
    get_success_data(api_client.recompute_account(acct["id"], OFFICER))
    return acct, period


def setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000,
        assessment_date=ASSESSMENT_3MO,
        clock=CLOCK_3MO,
        mdi_cents=300000,
        tax_year=2023,
        **acct_overrides):
    """Clock -> account -> one period (no recompute). Returns (account_dict, period_dict)."""
    if clock is not None:
        set_clock(clock)
    acct = create_account(monthly_disposable_income_cents=mdi_cents, **acct_overrides)
    period = create_period(
        acct["id"], assessed_tax_cents=assessed_tax_cents,
        assessment_date=assessment_date, tax_year=tax_year)
    return acct, period


# ─── Tier 2: Agreements (propose / approve) ───────────────────────────────

def propose_agreement(account_id, **overrides):
    """Create a PROPOSED agreement on the account. Returns the agreement dict."""
    return get_success_data(
        api_client.create_agreement(create_agreement_payload(account_id, **overrides), OFFICER))


def approve_agreement(account_id, agreement_id, headers=OFFICER):
    """Approve a proposed agreement with the account's current version.
    Returns the approved agreement dict."""
    v = get_account_version(account_id)
    return get_success_data(api_client.approve_agreement(
        agreement_id, {"expected_tax_account_version": v}, headers))


def setup_approved_agreement(payment_method="MANUAL", agreement_type="LONG_TERM",
                             monthly_payment_cents=200000, term_months=6,
                             low_income_flag=False,
                             active_from=None, active_to=None,
                             **scaffold_overrides):
    """Account + recomputed period + an APPROVED agreement.
    Returns (account, period, agreement)."""
    acct, period = setup_account_with_recomputed_period(**scaffold_overrides)
    agr_kwargs = dict(
        payment_method=payment_method, agreement_type=agreement_type,
        monthly_payment_cents=monthly_payment_cents, term_months=term_months,
        low_income_flag=low_income_flag)
    if active_from is not None:
        agr_kwargs["active_from"] = active_from
    if active_to is not None:
        agr_kwargs["active_to"] = active_to
    agr = propose_agreement(acct["id"], **agr_kwargs)
    approved = approve_agreement(acct["id"], agr["id"])
    return acct, period, approved


# ─── Tier 3: Offers (submit / evaluate / accept) ──────────────────────────

def submit_offer(account_id, offer_amount_cents, net_realizable_equity_cents=500000,
                 submitter_user_id="officer-submitter"):
    """Submit an OIC as a RevenueOfficer with an explicit operator id.
    Returns the offer dict."""
    headers = make_revenue_officer_headers(submitter_user_id)
    return get_success_data(api_client.create_offer(
        create_offer_payload(account_id, offer_amount_cents,
                             net_realizable_equity_cents=net_realizable_equity_cents),
        headers))


def begin_evaluation(offer_id, reviewer_user_id="reviewer-evaluator"):
    """Move an offer SUBMITTED -> EVALUATING (computes rcp_cents). Returns the offer dict."""
    headers = make_case_reviewer_headers(reviewer_user_id)
    return get_success_data(api_client.begin_evaluation(offer_id, headers))


def setup_offer_in_evaluating(
        offer_amount_cents=18500000,
        net_realizable_equity_cents=500000,
        submitter_user_id="officer-submitter",
        reviewer_user_id="reviewer-evaluator",
        recompute=False,
        **scaffold_overrides):
    """Account + period + an OIC moved to EVALUATING (rcp computed).
    Returns (account, period, offer)."""
    if recompute:
        acct, period = setup_account_with_recomputed_period(**scaffold_overrides)
    else:
        acct, period = setup_account_with_period_no_recompute(**scaffold_overrides)
    offer = submit_offer(acct["id"], offer_amount_cents,
                         net_realizable_equity_cents=net_realizable_equity_cents,
                         submitter_user_id=submitter_user_id)
    offer = begin_evaluation(offer["id"], reviewer_user_id=reviewer_user_id)
    return acct, period, offer


# ─── Tier 4: CSED suspensions ─────────────────────────────────────────────

def open_suspension(period_id, start_at, reason="MANUAL"):
    """Open a CSED suspension interval on a period. Returns the suspension dict."""
    return get_success_data(api_client.create_csed_suspension(
        create_csed_suspension_payload(period_id, reason=reason, start_at=start_at), OFFICER))


def close_suspension(suspension_id, end_at):
    """Close an open suspension interval. Returns the suspension dict."""
    return get_success_data(api_client.close_csed_suspension(
        suspension_id, {"end_at": end_at}, OFFICER))


# ─── Tier 5: Liens / Payments ─────────────────────────────────────────────

def setup_lien_release_pending(filed_amount_cents=1000000, **scaffold_overrides):
    """Account + recomputed period + a lien FILED then RELEASE_PENDING.
    Returns (account, period, lien)."""
    acct, period = setup_account_with_recomputed_period(**scaffold_overrides)
    lien = get_success_data(api_client.create_lien(
        create_lien_payload(acct["id"], filed_amount_cents=filed_amount_cents), OFFICER))
    lien = get_success_data(api_client.request_lien_release(lien["id"], OFFICER))
    return acct, period, lien


def post_payment(account_id, amount_cents, payment_source="MANUAL", tax_period_id=None):
    """Post a payment. Returns the payment dict."""
    extra = {}
    if tax_period_id is not None:
        extra["tax_period_id"] = tax_period_id
    return get_success_data(api_client.create_payment(
        create_payment_payload(account_id, amount_cents, payment_source=payment_source, **extra),
        OFFICER))
