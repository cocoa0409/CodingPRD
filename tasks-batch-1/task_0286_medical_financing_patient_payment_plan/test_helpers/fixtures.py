"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims need the system in a state that takes 6-15 API calls to
reach (provider enrolled, plan active, promotion bound, application approved,
account active, purchase authorized, settled, paid, statement closed, etc.).
These helpers build those preconditions from scratch using only PRD-declared
endpoints, so each test starts from an empty database (the runner restarts the
server before every test).

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup step failed" errors instead of confusing assertion failures.

Identity threading: after creating an entity-backed Provider / PatientAccount,
every ownership-gated call uses make_provider_headers(provider["id"]) /
make_patient_headers(account["id"]) — never the shared constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_provider_payload,
    create_promotional_plan_payload,
    create_provider_promotion_payload,
    create_credit_application_payload,
    create_financed_purchase_payload,
    settle_payload,
    create_payment_payload,
    create_refund_payload,
    open_statement_payload,
    create_autopay_enrollment_payload,
)
from .test_users import TEST_USERS, make_provider_headers, make_patient_headers


ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Monotonic counters so unique fields (tax_id, ssn_last4) never collide within a
# single test that builds several providers / applications.
_tax_seq = itertools.count(1)
_ssn_seq = itertools.count(1)


def _next_tax_id() -> str:
    return f"TX-FX-{next(_tax_seq)}"


def _next_ssn() -> str:
    # 4-digit string, cycling 0001..9999.
    return f"{(next(_ssn_seq) % 9000) + 1000:04d}"


# ─── Clock control ─────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the logical clock to an absolute instant (fires nothing by itself)."""
    return get_success_data(api_client.clock_set(to_iso8601, ADMIN))


def advance_clock(to_iso8601: str) -> dict:
    """Advance the clock, firing every promo_end crossing. Returns the advance body
    ({current_utc, forfeited_purchase_ids})."""
    res = api_client.clock_advance(to_iso8601, ADMIN)
    return get_success_data(res)


# ─── Tier 1: State progression on a single entity ─────────────────────────
def create_enrolled_provider(base_merchant_discount_rate=0.08, specialty="DENTAL",
                             legal_name="Test Clinic", tax_id=None) -> dict:
    """Create a provider and enroll it (PENDING -> ENROLLED). Returns the ENROLLED provider."""
    payload = create_provider_payload(
        legal_name=legal_name,
        specialty=specialty,
        tax_id=tax_id or _next_tax_id(),
        base_merchant_discount_rate=base_merchant_discount_rate,
    )
    provider = get_success_data(api_client.create_provider(payload, ADMIN))
    return get_success_data(api_client.enroll_provider(provider["id"], ADMIN))


def create_active_plan(plan_category="DEFERRED_INTEREST", deferred_period_months=12,
                       promo_apr=0.2, min_payment_factor=0.05, name="Test Plan") -> dict:
    """Create a promotional plan and activate it (DRAFT -> ACTIVE). Returns the ACTIVE plan."""
    plan = get_success_data(api_client.create_promotional_plan(
        create_promotional_plan_payload(
            name=name, plan_category=plan_category,
            deferred_period_months=deferred_period_months,
            promo_apr=promo_apr, min_payment_factor=min_payment_factor,
        ), ADMIN))
    return get_success_data(api_client.activate_promotional_plan(plan["id"], ADMIN))


def create_provider_promotion(provider_id, plan_id,
                              effective_start="2026-01-01T00:00:00Z",
                              effective_end="2028-01-01T00:00:00Z") -> dict:
    """Bind an ACTIVE plan to a provider over a half-open window. Returns the ACTIVE promotion."""
    return get_success_data(api_client.create_provider_promotion(
        create_provider_promotion_payload(
            provider_id, plan_id,
            effective_start=effective_start, effective_end=effective_end,
        ), ADMIN))


def create_active_account(income_cents=6_000_000, requested_limit_cents=500_000,
                          applicant_full_name="Test Applicant", ssn_last4=None) -> dict:
    """Submit + approve an application, minting an ACTIVE PatientAccount. Returns the account."""
    app = get_success_data(api_client.create_credit_application(
        create_credit_application_payload(
            applicant_full_name=applicant_full_name,
            applicant_ssn_last4=ssn_last4 or _next_ssn(),
            stated_annual_income_cents=income_cents,
            requested_limit_cents=requested_limit_cents,
        ), ANON))
    approved_app = get_success_data(api_client.approve_credit_application(app["id"], ADMIN))
    account_id = approved_app["patient_account_id"]
    return get_success_data(api_client.get_account(account_id, ADMIN))


# ─── Tier 2: Provider + plan + promotion + account scaffolding ────────────
def setup_provider_plan_promotion(base_merchant_discount_rate=0.08, specialty="DENTAL",
                                  plan_category="DEFERRED_INTEREST",
                                  deferred_period_months=12, promo_apr=0.2,
                                  min_payment_factor=0.05,
                                  effective_start="2026-01-01T00:00:00Z",
                                  effective_end="2028-01-01T00:00:00Z"):
    """ENROLLED provider + ACTIVE plan + ACTIVE provider-promotion. Returns
    (provider, plan, promotion)."""
    provider = create_enrolled_provider(
        base_merchant_discount_rate=base_merchant_discount_rate, specialty=specialty)
    plan = create_active_plan(
        plan_category=plan_category, deferred_period_months=deferred_period_months,
        promo_apr=promo_apr, min_payment_factor=min_payment_factor)
    promotion = create_provider_promotion(
        provider["id"], plan["id"],
        effective_start=effective_start, effective_end=effective_end)
    return provider, plan, promotion


def setup_full_origination_context(base_merchant_discount_rate=0.08, specialty="DENTAL",
                                   plan_category="DEFERRED_INTEREST",
                                   deferred_period_months=12, promo_apr=0.2,
                                   min_payment_factor=0.05,
                                   income_cents=6_000_000,
                                   requested_limit_cents=500_000,
                                   effective_start="2026-01-01T00:00:00Z",
                                   effective_end="2028-01-01T00:00:00Z"):
    """ENROLLED provider + ACTIVE plan + ACTIVE promotion + ACTIVE account ready to
    originate a purchase. Returns (provider, plan, promotion, account)."""
    provider, plan, promotion = setup_provider_plan_promotion(
        base_merchant_discount_rate=base_merchant_discount_rate, specialty=specialty,
        plan_category=plan_category, deferred_period_months=deferred_period_months,
        promo_apr=promo_apr, min_payment_factor=min_payment_factor,
        effective_start=effective_start, effective_end=effective_end)
    account = create_active_account(
        income_cents=income_cents, requested_limit_cents=requested_limit_cents)
    return provider, plan, promotion, account


# ─── Tier 3: Purchase lifecycle shortcuts ─────────────────────────────────
def authorize_purchase(provider, account, promotion, principal_cents) -> dict:
    """Authorize a FinancedPurchase against a fresh-version account. Re-reads the
    account so expected_patient_account_version is current. Returns the purchase."""
    acct = get_success_data(api_client.get_account(account["id"], ADMIN))
    res = api_client.create_financed_purchase(
        create_financed_purchase_payload(
            provider["id"], acct["id"], promotion["id"], principal_cents,
            expected_patient_account_version=acct["version"],
        ),
        make_provider_headers(provider["id"]))
    return get_success_data(res)


def create_authorized_purchase(principal_cents=100_000, base_merchant_discount_rate=0.08,
                               deferred_period_months=12, promo_apr=0.2,
                               min_payment_factor=0.05, income_cents=6_000_000,
                               requested_limit_cents=500_000, clock="2026-01-01T00:00:00Z",
                               specialty="DENTAL",
                               effective_start="2026-01-01T00:00:00Z",
                               effective_end="2028-01-01T00:00:00Z"):
    """End-to-end: clock + provider + plan + promotion + account + one AUTHORIZED
    purchase. Returns (provider, plan, promotion, account, purchase)."""
    set_clock(clock)
    provider, plan, promotion, account = setup_full_origination_context(
        base_merchant_discount_rate=base_merchant_discount_rate, specialty=specialty,
        deferred_period_months=deferred_period_months, promo_apr=promo_apr,
        min_payment_factor=min_payment_factor, income_cents=income_cents,
        requested_limit_cents=requested_limit_cents,
        effective_start=effective_start, effective_end=effective_end)
    purchase = authorize_purchase(provider, account, promotion, principal_cents)
    return provider, plan, promotion, account, purchase


def settle_purchase(purchase) -> dict:
    """Settle an AUTHORIZED purchase with the correct version. Returns the PENDING Settlement."""
    fp = get_success_data(api_client.get_financed_purchase(purchase["id"], ADMIN))
    res = api_client.settle_financed_purchase(
        fp["id"], settle_payload(expected_financed_purchase_version=fp["version"]), ADMIN)
    return get_success_data(res)


def create_settled_purchase(principal_cents=100_000, base_merchant_discount_rate=0.08,
                            **ctx_overrides):
    """clock + context + AUTHORIZED purchase + settle. Returns
    (provider, plan, promotion, account, purchase, settlement)."""
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=principal_cents,
        base_merchant_discount_rate=base_merchant_discount_rate, **ctx_overrides)
    settlement = settle_purchase(purchase)
    return provider, plan, promotion, account, purchase, settlement


def create_settled_paid_purchase(principal_cents=200_000, base_merchant_discount_rate=0.10,
                                 **ctx_overrides):
    """clock + context + purchase + settle + pay the settlement. Returns
    (provider, plan, promotion, account, purchase, settlement)."""
    provider, plan, promotion, account, purchase, settlement = create_settled_purchase(
        principal_cents=principal_cents,
        base_merchant_discount_rate=base_merchant_discount_rate, **ctx_overrides)
    settlement = get_success_data(api_client.pay_settlement(settlement["id"], ADMIN))
    return provider, plan, promotion, account, purchase, settlement


# ─── Tier 4: Payments ──────────────────────────────────────────────────────
def post_payment(account, amount_cents, payment_type="MANUAL") -> dict:
    """Post a payment from the owning patient. Returns the POSTED Payment."""
    res = api_client.create_payment(
        create_payment_payload(account["id"], amount_cents, payment_type),
        make_patient_headers(account["id"]))
    return get_success_data(res)


# ─── Tier 5: Billing cycle / delinquency ──────────────────────────────────
def open_statement(account_id, period_start, period_end) -> dict:
    """Open a statement for an account over a closed interval. Returns the OPEN statement."""
    res = api_client.open_statement(
        open_statement_payload(account_id, period_start, period_end), ADMIN)
    return get_success_data(res)


def close_statement(account_id) -> dict:
    """Close an account's OPEN statement (computes minimum, drives delinquency, opens next).
    Returns the just-closed statement."""
    return get_success_data(api_client.close_statement(account_id, ADMIN))


def drive_unsatisfied_cycle(account_id, period_start, period_end, close_clock):
    """Open a statement, advance the clock to its end, and close it unsatisfied (no payment).
    Returns the closed statement."""
    open_statement(account_id, period_start, period_end)
    set_clock(close_clock)
    return close_statement(account_id)


def setup_delinquent_account(principal_cents=200_000, min_payment_factor=0.05,
                             deferred_period_months=24, promo_apr=0.2):
    """Drive an account to DELINQUENT (1 strike) via one unsatisfied statement close.
    Returns (provider, plan, promotion, account, purchase)."""
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=principal_cents, min_payment_factor=min_payment_factor,
        deferred_period_months=deferred_period_months, promo_apr=promo_apr,
        requested_limit_cents=500_000)
    drive_unsatisfied_cycle(
        account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z", "2026-01-31T00:00:00Z")
    return provider, plan, promotion, account, purchase


def setup_defaulted_account(principal_cents=100_000, min_payment_factor=0.05,
                            deferred_period_months=36, promo_apr=0.2,
                            with_autopay=False, applicant_full_name="Test Applicant"):
    """Drive an account to DEFAULTED via three consecutive unsatisfied statement closes.
    Returns (provider, plan, promotion, account, purchase, autopay_or_None)."""
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion = setup_provider_plan_promotion(
        deferred_period_months=deferred_period_months, promo_apr=promo_apr,
        min_payment_factor=min_payment_factor,
        effective_start="2026-01-01T00:00:00Z", effective_end="2030-01-01T00:00:00Z")
    account = create_active_account(
        requested_limit_cents=500_000, applicant_full_name=applicant_full_name)
    purchase = authorize_purchase(provider, account, promotion, principal_cents)

    autopay = None
    if with_autopay:
        autopay = get_success_data(api_client.create_autopay_enrollment(
            create_autopay_enrollment_payload(account["id"], draft_day_of_month=15),
            make_patient_headers(account["id"])))

    open_statement(account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    set_clock("2026-01-31T00:00:00Z")
    close_statement(account["id"])  # strike 1 -> DELINQUENT
    set_clock("2026-02-28T00:00:00Z")
    close_statement(account["id"])  # strike 2 -> DELINQUENT
    set_clock("2026-03-31T00:00:00Z")
    close_statement(account["id"])  # strike 3 -> DEFAULTED
    return provider, plan, promotion, account, purchase, autopay


# ─── Refund ────────────────────────────────────────────────────────────────
def apply_refund(provider_id, financed_purchase_id, refund_kind, amount_cents) -> dict:
    """Apply a VOID/REFUND from the owning provider. Returns the APPLIED Refund."""
    res = api_client.create_refund(
        create_refund_payload(financed_purchase_id, refund_kind, amount_cents),
        make_provider_headers(provider_id))
    return get_success_data(res)
