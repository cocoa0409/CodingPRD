"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures.

Identity threading: an Accountholder-owned (entity_backed) call always uses
make_accountholder_headers(holder_id); never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_accountholder_payload, create_employer_payload,
    create_payroll_period_payload, create_account_payload,
    create_coverage_period_payload, create_contribution_payload,
    create_sweep_payload, create_card_payload, create_receipt_payload,
    create_distribution_payload, create_correction_payload, create_tax_form_payload,
)
from .test_users import (
    TEST_USERS, make_accountholder_headers, make_employer_headers, make_admin_headers,
)
from .constants import CLOCK_DEFAULT

ADMIN = TEST_USERS["admin_headers"]
# Two distinct opaque admins for segregation-of-duties (clear vs substantiate/reverse).
ADMIN_A = make_admin_headers("adminA")
ADMIN_B = make_admin_headers("adminB")


# ─── Logical clock ───────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical server clock. Admin-only."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: Reference data + account state progression ──────────────────────

def create_accountholder(date_of_birth="1980-01-01", **overrides):
    """Create one Accountholder. Returns the entity (use entity['id'] for headers)."""
    payload = create_accountholder_payload(date_of_birth=date_of_birth, **overrides)
    return get_success_data(api_client.create_accountholder(payload, ADMIN))


def create_employer(payroll_contributions_enabled=None, **overrides):
    """Create one Employer (payroll sponsor)."""
    extra = {}
    if payroll_contributions_enabled is not None:
        extra["payroll_contributions_enabled"] = payroll_contributions_enabled
    payload = create_employer_payload(**extra, **overrides)
    return get_success_data(api_client.create_employer(payload, ADMIN))


def open_account(holder_id, **overrides):
    """Open a PENDING_VERIFICATION HSA. Returns the account entity (carries
    verification_token)."""
    payload = create_account_payload(holder_id, **overrides)
    return get_success_data(api_client.create_account(payload, ADMIN))


def attest_coverage(account_id, coverage_tier="SELF_ONLY", effective_month=1,
                    end_month=12):
    """Attest one HDHP coverage interval (admin)."""
    payload = create_coverage_period_payload(coverage_tier, effective_month, end_month)
    return get_success_data(api_client.create_coverage_period(account_id, payload, ADMIN))


def verify_account(account_id, holder_id, token):
    """Activate a PENDING_VERIFICATION account as its owning holder."""
    return get_success_data(api_client.verify_account(
        account_id, {"verification_token": token},
        make_accountholder_headers(holder_id)))


def setup_active_account(coverage_tier="SELF_ONLY", effective_month=1, end_month=12,
                         date_of_birth="1980-01-01", plan_year=2026,
                         employer_id=None, clock=None, **account_overrides):
    """Holder + open account + attest one coverage period + verify -> ACTIVE.

    Returns (account, holder) where account is the verified ACTIVE HsaAccount and holder
    is the owning Accountholder. account['id'] is the live account id; holder['id'] is the
    X-User-ID for any holder-scoped follow-on call.
    """
    if clock is not None:
        set_clock(clock)
    holder = create_accountholder(date_of_birth=date_of_birth)
    extra = dict(account_overrides)
    extra["plan_year"] = plan_year
    if employer_id is not None:
        extra["employer_id"] = employer_id
    account = open_account(holder["id"], **extra)
    attest_coverage(account["id"], coverage_tier, effective_month, end_month)
    verify_account(account["id"], holder["id"], account["verification_token"])
    fresh = get_success_data(api_client.get_account(account["id"], ADMIN))
    # Preserve the token (GET omits it) for downstream re-verify tests.
    fresh["verification_token"] = account["verification_token"]
    return fresh, holder


# ─── Tier 2: Contribution helpers ────────────────────────────────────────────

def create_contribution(account_id, channel="INDIVIDUAL", amount_cents=100000,
                        contribution_kind=None):
    """Create a PENDING contribution (admin). Returns the contribution entity."""
    extra = {}
    if contribution_kind is not None:
        extra["contribution_kind"] = contribution_kind
    payload = create_contribution_payload(channel, amount_cents, **extra)
    return get_success_data(api_client.create_contribution(account_id, payload, ADMIN))


def post_contribution(account_id, contribution_id):
    """Post a PENDING contribution (admin)."""
    return get_success_data(
        api_client.post_contribution(account_id, contribution_id, ADMIN))


def create_and_post_contribution(account_id, channel="INDIVIDUAL", amount_cents=100000,
                                 contribution_kind=None):
    """Create then post a contribution. Returns the POSTED contribution entity."""
    contrib = create_contribution(account_id, channel, amount_cents, contribution_kind)
    return post_contribution(account_id, contrib["id"])


def setup_active_account_with_cash(amount_cents=100000, coverage_tier="SELF_ONLY",
                                   effective_month=1, end_month=12,
                                   date_of_birth="1980-01-01", clock="2026-03-01T00:00:00Z"):
    """ACTIVE account funded by one POSTED INDIVIDUAL contribution of amount_cents.

    Returns (account, holder, contribution). The account dict is a fresh GET snapshot, so
    cash_balance_cents and version reflect the posted contribution.
    """
    account, holder = setup_active_account(
        coverage_tier=coverage_tier, effective_month=effective_month,
        end_month=end_month, date_of_birth=date_of_birth, clock=clock)
    contrib = create_and_post_contribution(account["id"], "INDIVIDUAL", amount_cents)
    fresh = get_success_data(api_client.get_account(account["id"], ADMIN))
    fresh["verification_token"] = account["verification_token"]
    return fresh, holder, contrib


def account_version(account_id):
    """Fetch the current HsaAccount.version (for OCC expected_account_version)."""
    return get_success_data(api_client.get_account(account_id, ADMIN))["version"]


# ─── Tier 3: Distribution lifecycle helpers ──────────────────────────────────

def request_distribution(account_id, holder_id, method="REIMBURSEMENT",
                         amount_cents=50000, card_id=None):
    """Holder requests a distribution. Returns the REQUESTED distribution."""
    extra = {}
    if card_id is not None:
        extra["card_id"] = card_id
    payload = create_distribution_payload(method, amount_cents, **extra)
    return get_success_data(api_client.create_distribution(
        account_id, payload, make_accountholder_headers(holder_id)))


def clear_distribution(account_id, distribution_id, admin_headers=ADMIN_A):
    """Admin clears a REQUESTED distribution (debits cash, stamps cleared_by_user_id)."""
    return get_success_data(api_client.clear_distribution(
        account_id, distribution_id, admin_headers))


def request_and_clear_distribution(account_id, holder_id, method="REIMBURSEMENT",
                                   amount_cents=50000, card_id=None,
                                   clearer=ADMIN_A):
    """Holder requests + admin clears. Returns the CLEARED distribution."""
    dist = request_distribution(account_id, holder_id, method, amount_cents, card_id)
    return clear_distribution(account_id, dist["id"], clearer)


def vault_receipt(account_id, holder_id, amount_cents=60000, is_qualified_medical=True,
                  merchant="Clinic", service_date="2026-01-20T00:00:00Z"):
    """Holder vaults a receipt against the account. Returns the VAULTED receipt."""
    payload = create_receipt_payload(account_id, amount_cents, is_qualified_medical,
                                     merchant=merchant, service_date=service_date)
    return get_success_data(api_client.create_receipt(
        payload, make_accountholder_headers(holder_id)))


# ─── Tier 4: Debit card lifecycle ────────────────────────────────────────────

def issue_card(account_id, holder_id, last_four="4242"):
    """Holder issues an ISSUED debit card. Returns the card."""
    payload = create_card_payload(last_four=last_four)
    return get_success_data(api_client.create_card(
        account_id, payload, make_accountholder_headers(holder_id)))


def issue_and_activate_card(account_id, holder_id, last_four="4242"):
    """Issue + activate a card (holder). Returns the ACTIVE card."""
    card = issue_card(account_id, holder_id, last_four)
    return get_success_data(api_client.activate_card(
        account_id, card["id"], make_accountholder_headers(holder_id)))


# ─── Tier 5: Excess / correction setup ───────────────────────────────────────

def setup_account_with_excess(over_amount_cents=500000, coverage_tier="SELF_ONLY",
                              effective_month=1, end_month=12,
                              date_of_birth="1980-01-01", clock="2026-03-01T00:00:00Z"):
    """ACTIVE account driven into excess / LOCKED posture by one large POSTED INDIVIDUAL
    contribution of over_amount_cents (which exceeds the limit).

    Returns (account, holder, over_contribution).
    """
    account, holder, contrib = setup_active_account_with_cash(
        amount_cents=over_amount_cents, coverage_tier=coverage_tier,
        effective_month=effective_month, end_month=end_month,
        date_of_birth=date_of_birth, clock=clock)
    return account, holder, contrib


def create_correction(account_id, requested_amount_cents, expected_account_version,
                      caller=ADMIN):
    """Create a REQUESTED ExcessCorrection (admin or holder). Returns the correction."""
    payload = create_correction_payload(requested_amount_cents, expected_account_version)
    return get_success_data(api_client.create_correction(account_id, payload, caller))


# ─── Tier 6: Tax forms ───────────────────────────────────────────────────────

def generate_tax_form(account_id, form_type, tax_year=2026):
    """Generate an immutable tax form snapshot (admin). Returns the TaxForm."""
    payload = create_tax_form_payload(form_type, tax_year)
    return get_success_data(api_client.create_tax_form(account_id, payload, ADMIN))


# ─── Tier 7: Payroll calendar ────────────────────────────────────────────────

def create_payroll_period(employer_id, period_start_day, period_end_day):
    """Schedule a payroll period under an employer. Returns the SCHEDULED period."""
    payload = create_payroll_period_payload(period_start_day, period_end_day)
    return get_success_data(api_client.create_payroll_period(
        employer_id, payload, ADMIN))
