"""Composite setup helpers for the COBRA Administration API.

These encapsulate the multi-step API call sequences the difficulty and corner
test instances need to reach a specific system state, so test functions can
focus on the trigger + assertions. Every helper builds its preconditions from
scratch using only PRD-declared endpoints (the server starts empty before each
test) and uses get_success_data() so setup failures surface as clear
"Setup step failed" errors.

Identity threading (PRD §2.7): the QualifiedBeneficiary's elect and self-pay
calls are ownership-gated, so helpers always call make_beneficiary_headers with
the real beneficiary id rather than the shared constant.

Clock threading (PRD §2.5): time never advances on its own and every
server-stamped timestamp reads the simulated clock, so helpers set the clock
explicitly before each clock-sensitive step.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_plan_payload, create_beneficiary_payload, create_event_payload,
    create_invoice_payload, create_payment_payload, create_subsidy_payload,
    apply_disability_extension_payload, terminate_early_payload, refund_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_beneficiary_headers

_ADMIN = TEST_USERS["plan_administrator_headers"]
_SPONSOR = TEST_USERS["plan_sponsor_headers"]
_BILLING = TEST_USERS["billing_agent_headers"]


# ==========================================================================
# Clock control
# ==========================================================================
def set_clock(now_iso8601):
    """Set the global simulated clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(set_clock_payload(now_iso8601), _ADMIN))


# ==========================================================================
# Tier 1: primitives
# ==========================================================================
def create_plan(**overrides) -> dict:
    """Create one ACTIVE GroupHealthPlan (PRD §3.1)."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), _ADMIN))


def create_beneficiary(plan_id, **overrides) -> dict:
    """Register one ACTIVE_EMPLOYEE_COVERAGE beneficiary (PRD §3.1)."""
    payload = create_beneficiary_payload(plan_id, **overrides)
    return get_success_data(api_client.create_beneficiary(payload, _SPONSOR))


def create_event(plan_id, beneficiary_id, **overrides) -> dict:
    """Record one RECORDED qualifying event (PRD §3.2)."""
    payload = create_event_payload(plan_id, beneficiary_id, **overrides)
    return get_success_data(api_client.create_event(payload, _SPONSOR))


def send_notice(event_id) -> dict:
    """Issue the election notice; returns the created ElectionNotice (PRD §3.3)."""
    return get_success_data(api_client.send_notice(event_id, _ADMIN))


def elect(notice_id, beneficiary_id) -> dict:
    """Elect COBRA on the beneficiary's own notice; returns the enrollment
    (PRD §3.4). Ownership-gated, so uses the real beneficiary id."""
    return get_success_data(api_client.elect(notice_id, make_beneficiary_headers(beneficiary_id)))


def get_account_for_enrollment(enrollment_id) -> dict:
    """Fetch the single PremiumAccount created for an enrollment (PRD §3.4)."""
    accounts = get_success_data(
        api_client.list_accounts(_BILLING, params={"enrollment_id": enrollment_id})
    )
    assert accounts, f"no account found for enrollment {enrollment_id}"
    return accounts[0]


def create_invoice(account_id, coverage_month, **overrides) -> dict:
    """Generate one OPEN PremiumInvoice (PRD §3.5)."""
    payload = create_invoice_payload(coverage_month, **overrides)
    return get_success_data(api_client.create_invoice(account_id, payload, _BILLING))


def post_payment(account_id, amount_cents, target_coverage_month, *, beneficiary_id=None) -> dict:
    """Post one POSTED payment (PRD §3.6). When beneficiary_id is given the
    payment is made by the owning QualifiedBeneficiary; otherwise BillingAgent."""
    payload = create_payment_payload(amount_cents, target_coverage_month)
    headers = make_beneficiary_headers(beneficiary_id) if beneficiary_id else _BILLING
    return get_success_data(api_client.create_payment(account_id, payload, headers))


def grant_subsidy(enrollment_id, subsidy_pct, start_month, end_month) -> dict:
    """Grant one ACTIVE SubsidyGrant (PRD §3.7)."""
    payload = create_subsidy_payload(subsidy_pct, start_month, end_month)
    return get_success_data(api_client.create_subsidy(enrollment_id, payload, _ADMIN))


def apply_disability_extension(enrollment_id, determination_date) -> dict:
    """Apply an SSA disability extension; returns the updated enrollment (PRD §3.8)."""
    payload = apply_disability_extension_payload(determination_date)
    return get_success_data(api_client.apply_disability_extension(enrollment_id, payload, _ADMIN))


def terminate_early(enrollment_id, reason) -> dict:
    """Terminate an ACTIVE enrollment early (PRD §3.9)."""
    payload = terminate_early_payload(reason)
    return get_success_data(api_client.terminate_early(enrollment_id, payload, _ADMIN))


def issue_refund(account_id, refund_amount_cents, expected_account_version) -> dict:
    """Refund credit back to the beneficiary (PRD §3.11 / §2.8)."""
    payload = refund_payload(refund_amount_cents, expected_account_version)
    return get_success_data(api_client.refund(account_id, payload, _BILLING))


def account_version(account_id) -> int:
    """Read the account's current version (for OCC refund threading, PRD §2.8)."""
    return get_account(account_id)["version"]


def get_account(account_id) -> dict:
    return get_success_data(api_client.get_account(account_id, _BILLING))


def first_certificate_for_beneficiary(beneficiary_id, role_headers=None) -> dict:
    """Return the first HIPAA certificate listed for a beneficiary (PRD §3.10)."""
    headers = role_headers or _ADMIN
    certs = get_success_data(
        api_client.list_beneficiary_certificates(beneficiary_id, headers)
    )
    assert certs, f"no certificate found for beneficiary {beneficiary_id}"
    return certs[0]


# ==========================================================================
# Tier 2/3: the canonical "elected enrollment" chain
# ==========================================================================
def setup_elected_enrollment(
    *,
    applicable_premium_cents=60000,
    event_type="TERMINATION",
    relationship="EMPLOYEE",
    coverage_loss_date="2026-04-01T00:00:00.000Z",
    event_date="2026-03-31T00:00:00.000Z",
    notice_clock="2026-03-20T00:00:00.000Z",
    elect_clock="2026-04-10T00:00:00.000Z",
    plan_overrides=None,
):
    """Drive the canonical chain through election:

      set clock -> create plan -> register beneficiary -> record event ->
      send notice -> set clock (within window) -> elect -> fetch account.

    Returns a dict with plan, beneficiary, event, notice, enrollment, account.
    The enrollment is in PENDING_INITIAL_PREMIUM; no invoice exists yet.
    """
    set_clock(notice_clock)
    plan = create_plan(applicable_premium_cents=applicable_premium_cents, **(plan_overrides or {}))
    beneficiary = create_beneficiary(plan["id"], relationship=relationship)
    event = create_event(
        plan["id"], beneficiary["id"],
        event_type=event_type, event_date=event_date, coverage_loss_date=coverage_loss_date,
    )
    notice = send_notice(event["id"])
    set_clock(elect_clock)
    enrollment = elect(notice["id"], beneficiary["id"])
    account = get_account_for_enrollment(enrollment["id"])
    return {
        "plan": plan,
        "beneficiary": beneficiary,
        "event": event,
        "notice": notice,
        "enrollment": enrollment,
        "account": account,
    }


def setup_active_enrollment(
    *,
    applicable_premium_cents=60000,
    first_month="2026-04",
    first_payment_cents=61200,
    coverage_loss_date="2026-04-01T00:00:00.000Z",
    notice_clock="2026-03-20T00:00:00.000Z",
    elect_clock="2026-04-10T00:00:00.000Z",
    event_type="TERMINATION",
    relationship="EMPLOYEE",
):
    """Extend setup_elected_enrollment by invoicing and fully paying the first
    coverage month, which bubbles the enrollment to ACTIVE (PRD §3.6).

    Returns the same dict plus the first invoice (key 'first_invoice') and the
    re-read enrollment/account reflecting the ACTIVE / paid_through state.
    """
    ctx = setup_elected_enrollment(
        applicable_premium_cents=applicable_premium_cents,
        coverage_loss_date=coverage_loss_date,
        notice_clock=notice_clock,
        elect_clock=elect_clock,
        event_type=event_type,
        relationship=relationship,
    )
    acct_id = ctx["account"]["id"]
    invoice = create_invoice(acct_id, first_month)
    post_payment(acct_id, first_payment_cents, first_month)
    ctx["first_invoice"] = invoice
    ctx["enrollment"] = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"], _ADMIN)
    )
    ctx["account"] = get_account(acct_id)
    return ctx


def setup_overpaid_account(
    *,
    invoice_month="2026-04",
    payment_cents=70000,
):
    """Active enrollment with the first month overpaid, leaving a positive
    credit balance for refund tests (PRD §3.11). Returns the context dict; the
    account reflects the credit balance and current version."""
    ctx = setup_active_enrollment(first_month=invoice_month, first_payment_cents=payment_cents)
    ctx["account"] = get_account(ctx["account"]["id"])
    return ctx
