"""Composite setup helpers for multi-step test prerequisites.

Most PRD claims require the system to be in a specific state that takes
5-15 API calls to reach (an OPEN term with a rate card, an assessed
enrollment, a DEFAULTED payment plan, a COLLECTIONS account, ...). These
helpers encapsulate those preambles so tests can focus on assertions.
All helpers use get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_enrollment_payload,
    create_hold_payload,
    create_payment_payload,
    create_payment_plan_payload,
    create_sponsor_agreement_payload,
    create_sponsor_invoice_payload,
    create_student_payload,
    create_tax_form_payload,
    create_term_payload,
    create_tuition_rate_payload,
    create_waiver_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS

_REG = TEST_USERS["registrar_headers"]
_STAFF = TEST_USERS["bursar_staff_headers"]
_MGR = TEST_USERS["bursar_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock (PRD §2.4). Returns the clock payload."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), _STAFF)
    )


def make_student(external_ref: str, full_name: str = "Test Student",
                 residency_status: str = "IN_STATE", level: str = "UNDERGRADUATE") -> dict:
    """Register a student (PRD §3.1). Returns the created Student."""
    return get_success_data(api_client.create_student(
        create_student_payload(
            full_name=full_name, external_ref=external_ref,
            residency_status=residency_status, level=level,
        ),
        _REG,
    ))


def make_student_in_state(external_ref: str, full_name: str = "Test Student") -> dict:
    return make_student(external_ref, full_name)


# ---------------------------------------------------------------------------
# Tier 1: term + rate card state progression
# ---------------------------------------------------------------------------

def create_draft_term(**term_overrides) -> dict:
    """Create a term in DRAFT (PRD §3.1)."""
    return get_success_data(
        api_client.create_term(create_term_payload(**term_overrides), _REG)
    )


def create_open_term(**term_overrides) -> dict:
    """Create a term and transition it DRAFT -> OPEN (PRD §3.1)."""
    term = create_draft_term(**term_overrides)
    return get_success_data(
        api_client.transition_term(term["id"], {"action": "OPEN"}, _REG)
    )


def add_standard_rate(term_id: str, **rate_overrides) -> dict:
    """Attach the standard IN_STATE/UNDERGRADUATE rate card to a term."""
    return get_success_data(api_client.create_tuition_rate(
        create_tuition_rate_payload(term_id=term_id, **rate_overrides), _REG,
    ))


def setup_term_with_rate(**term_overrides):
    """OPEN term + standard rate card. Returns (term, rate)."""
    term = create_open_term(**term_overrides)
    rate = add_standard_rate(term["id"])
    return term, rate


# ---------------------------------------------------------------------------
# Tier 2: enrollment -> assessed account
# ---------------------------------------------------------------------------

def enroll(student_id: str, term_id: str, credit_hours: int = 12,
           effective_date: str = "2026-08-25") -> dict:
    """Enroll a student (PRD §3.2). Returns the Enrollment (carries account_id)."""
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(
            student_id=student_id, term_id=term_id,
            credit_hours=credit_hours, effective_date=effective_date,
        ),
        _REG,
    ))


def setup_account_with_enrollment(credit_hours: int = 12,
                                  external_ref: str = "S-1",
                                  effective_date: str = "2026-08-25",
                                  term_overrides: dict = None,
                                  rate_overrides: dict = None,
                                  student_overrides: dict = None) -> dict:
    """OPEN term + rate card + student + enrollment (assessment posted).

    Returns a context dict with term, rate, student, enrollment, account_id.
    """
    term, rate = setup_term_with_rate(**(term_overrides or {}))
    if rate_overrides:
        # replace standard card expectations by creating a distinct term/rate
        raise ValueError("use term_overrides; standard rate is fixed")
    student = make_student(external_ref, **(student_overrides or {}))
    enrollment = enroll(student["id"], term["id"], credit_hours, effective_date)
    return {
        "term": term,
        "rate": rate,
        "student": student,
        "enrollment": enrollment,
        "account_id": enrollment["account_id"],
    }


def read_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, _STAFF))


def account_version(account_id: str) -> int:
    return read_account(account_id)["version"]


def read_ledger(account_id: str) -> list:
    return get_success_data(api_client.get_account_ledger(account_id, _STAFF))


def make_payment(account_id: str, amount_cents: int, method: str = "CARD") -> dict:
    return get_success_data(api_client.create_payment(
        create_payment_payload(account_id=account_id, amount_cents=amount_cents,
                               method=method),
        _STAFF,
    ))


# ---------------------------------------------------------------------------
# Tier 3: payment plans & installments
# ---------------------------------------------------------------------------

def create_plan(account_id: str, installment_count: int = 2,
                first_due_date: str = "2026-09-01") -> dict:
    """Create a payment plan with a freshly-read OCC version (PRD §3.7)."""
    version = account_version(account_id)
    return get_success_data(api_client.create_payment_plan(
        create_payment_plan_payload(
            account_id=account_id, installment_count=installment_count,
            first_due_date=first_due_date, expected_account_version=version,
        ),
        _STAFF,
    ))


def get_installments(plan_id: str) -> list:
    """Installments of a plan ordered by sequence."""
    data = get_success_data(api_client.list_plan_installments(plan_id, _STAFF))
    return sorted(data, key=lambda i: i["sequence"])


def setup_plan_scenario(credit_hours: int = 9, installment_count: int = 4,
                        first_due_date: str = "2026-09-01",
                        prepay_cents: int = 0,
                        external_ref: str = "S-PLAN") -> dict:
    """Assessed account + (optional prepayment) + ACTIVE plan with installments.

    Returns context with term, student, enrollment, account_id, plan,
    installments (ordered by sequence).
    """
    ctx = setup_account_with_enrollment(credit_hours=credit_hours,
                                        external_ref=external_ref)
    if prepay_cents:
        make_payment(ctx["account_id"], prepay_cents)
    plan = create_plan(ctx["account_id"], installment_count, first_due_date)
    ctx["plan"] = plan
    ctx["installments"] = get_installments(plan["id"])
    return ctx


def run_billing_cycle_at(term_id: str, clock_iso: str) -> dict:
    """Advance the logical clock then run the billing cycle (PRD §3.8).
    Returns the cycle summary counts."""
    set_clock(clock_iso)
    return get_success_data(api_client.run_billing_cycle(term_id, _STAFF))


def pay_installment_exact(installment: dict) -> dict:
    """Pay exactly the remaining amount of an installment (PRD §3.7)."""
    remaining = installment["amount_cents"] - installment["paid_cents"]
    return get_success_data(api_client.pay_installment(
        installment["id"], {"amount_cents": remaining}, _STAFF,
    ))


# ---------------------------------------------------------------------------
# Tier 4: delinquency / collections accumulation
# ---------------------------------------------------------------------------

def setup_past_due_account(credit_hours: int = 9,
                           clock_iso: str = "2026-10-15",
                           external_ref: str = "S-PD") -> dict:
    """Assessed account aged past due by the billing cycle (no plan).
    Returns context with account re-read after the cycle."""
    ctx = setup_account_with_enrollment(credit_hours=credit_hours,
                                        external_ref=external_ref)
    ctx["cycle"] = run_billing_cycle_at(ctx["term"]["id"], clock_iso)
    ctx["account"] = read_account(ctx["account_id"])
    return ctx


def setup_collections_account(credit_hours: int = 9,
                              clock_iso: str = "2026-10-15",
                              external_ref: str = "S-COL") -> dict:
    """Account walked OPEN -> PAST_DUE -> COLLECTIONS with the five-percent
    collections fee posted (PRD §3.10)."""
    ctx = setup_past_due_account(credit_hours, clock_iso, external_ref)
    ctx["account"] = get_success_data(
        api_client.send_to_collections(ctx["account_id"], _STAFF)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3b: waivers
# ---------------------------------------------------------------------------

def award_waiver(account_id: str, kind: str = "WAIVER",
                 awarded_cents: int = 50000) -> dict:
    return get_success_data(api_client.create_waiver(
        create_waiver_payload(account_id=account_id, kind=kind,
                              awarded_cents=awarded_cents),
        _STAFF,
    ))


def post_waiver(waiver_id: str, account_id: str) -> dict:
    """Post an AWARDED waiver with a freshly-read OCC version (PRD §3.4)."""
    version = account_version(account_id)
    return get_success_data(api_client.post_waiver(
        waiver_id, {"expected_account_version": version}, _STAFF,
    ))


def create_posted_waiver(account_id: str, kind: str = "SCHOLARSHIP",
                         awarded_cents: int = 100000) -> dict:
    waiver = award_waiver(account_id, kind, awarded_cents)
    return post_waiver(waiver["id"], account_id)


# ---------------------------------------------------------------------------
# Tier 3c: sponsor agreements & invoices
# ---------------------------------------------------------------------------

def create_agreement(student_id: str, term_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_sponsor_agreement(
        create_sponsor_agreement_payload(student_id=student_id, term_id=term_id,
                                         **overrides),
        _STAFF,
    ))


def setup_sponsor_scenario(billing_basis: str = "GROSS",
                           cap_cents: int = 1000000,
                           credit_hours: int = 12,
                           waiver_amount: int = 0,
                           waiver_kind: str = "SCHOLARSHIP",
                           external_ref: str = "S-SPN",
                           **agreement_overrides) -> dict:
    """Assessed account + (optional posted waiver) + ACTIVE sponsor agreement.
    Returns context with term, student, enrollment, account_id, agreement.
    """
    ctx = setup_account_with_enrollment(credit_hours=credit_hours,
                                        external_ref=external_ref)
    if waiver_amount:
        ctx["waiver"] = create_posted_waiver(ctx["account_id"], waiver_kind,
                                             waiver_amount)
    ctx["agreement"] = create_agreement(
        ctx["student"]["id"], ctx["term"]["id"],
        billing_basis=billing_basis, cap_cents=cap_cents, **agreement_overrides,
    )
    return ctx


def create_draft_invoice(agreement_id: str) -> dict:
    return get_success_data(api_client.create_sponsor_invoice(
        create_sponsor_invoice_payload(agreement_id), _STAFF,
    ))


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.transition_sponsor_invoice(
        invoice_id, {"action": "ISSUE"}, _STAFF,
    ))


def setup_issued_invoice(billing_basis: str = "GROSS", cap_cents: int = 1000000,
                         credit_hours: int = 12, **agreement_overrides) -> dict:
    """Sponsor scenario with an ISSUED invoice. Adds invoice to context."""
    ctx = setup_sponsor_scenario(billing_basis=billing_basis, cap_cents=cap_cents,
                                 credit_hours=credit_hours, **agreement_overrides)
    ctx["invoice"] = issue_invoice(create_draft_invoice(ctx["agreement"]["id"])["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: refunds & tax forms
# ---------------------------------------------------------------------------

def refund_for_enrollment(enrollment_id: str) -> dict:
    """The single Refund created by a drop/withdraw of the enrollment."""
    data = get_success_data(
        api_client.list_refunds(_STAFF, params={"enrollment_id": enrollment_id})
    )
    assert len(data) == 1, f"expected exactly one refund, got {len(data)}"
    return data[0]


def setup_calculated_refund(credit_hours: int = 1, action: str = "withdraw",
                            effective_date: str = "2026-09-05",
                            term_overrides: dict = None,
                            external_ref: str = "S-REF") -> dict:
    """Enrollment exited via drop/withdraw; Refund in CALCULATED.
    Returns context with term, student, enrollment, account_id, refund."""
    ctx = setup_account_with_enrollment(credit_hours=credit_hours,
                                        external_ref=external_ref,
                                        term_overrides=term_overrides)
    if action == "withdraw":
        get_success_data(api_client.withdraw_enrollment(
            ctx["enrollment"]["id"], {"effective_date": effective_date}, _REG,
        ))
    else:
        get_success_data(api_client.drop_enrollment(
            ctx["enrollment"]["id"], {"effective_date": effective_date}, _REG,
        ))
    ctx["refund"] = refund_for_enrollment(ctx["enrollment"]["id"])
    return ctx


def create_tax_form(student_id: str, tax_year: int = 2026) -> dict:
    return get_success_data(api_client.create_tax_form(
        create_tax_form_payload(student_id, tax_year), _STAFF,
    ))


def place_manual_hold(account_id: str, hold_type: str = "REGISTRATION",
                      reason: str = "Advising stop") -> dict:
    return get_success_data(api_client.create_hold(
        create_hold_payload(account_id=account_id, hold_type=hold_type,
                            reason=reason),
        _STAFF,
    ))


def list_active_holds(account_id: str) -> list:
    return get_success_data(
        api_client.list_account_holds(account_id, _STAFF, params={"status": "ACTIVE"})
    )
