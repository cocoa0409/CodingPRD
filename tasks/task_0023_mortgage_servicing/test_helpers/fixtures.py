"""Composite setup helpers for multi-step mortgage-servicing test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints. The test harness restarts the API server before every individual
pytest test, so every fixture starts against an empty database.

Identity threading (PRD §2.1):
  * LoanServicer / ComplianceOfficer are identity:opaque — shared headers
    are safe.
  * Borrower is identity:entity_backed — `X-User-ID` must equal the actual
    Borrower.id. Use `make_borrower_headers(borrower_id)` for ownership-gated
    calls; never fall back to the shared constant.

Setup helpers use `get_success_data` so a failed setup surfaces as a clear
"setup failed" error rather than a misleading assertion deep inside a test.
"""
import uuid
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_borrower_payload,
    create_loan_payload,
    create_payment_payload,
    create_escrow_account_payload,
    create_disbursement_payload,
    create_escrow_analysis_payload,
    create_forbearance_plan_payload,
    create_pmi_removal_request_payload,
    create_mediation_session_payload,
)
from .test_users import (
    make_loan_servicer_headers,
    make_compliance_officer_headers,
)


# ── Clock ─────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> None:
    """Advance the simulated clock (PRD §2.4). Fires every auto-transition
    whose preconditions newly hold."""
    get_success_data(
        api_client.set_clock(to_iso8601, make_loan_servicer_headers())
    )


# ── Borrower / Loan primitives ────────────────────────────────────────────

def _unique_email(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}@example.com"


def create_borrower(
    email: Optional[str] = None,
    full_name: str = "Test Borrower",
    ssn_last4: str = "1234",
) -> dict:
    """Create a Borrower (PRD §3.1)."""
    payload = create_borrower_payload(
        email=email or _unique_email("b"),
        full_name=full_name,
        ssn_last4=ssn_last4,
    )
    return get_success_data(api_client.create_borrower(
        payload, make_loan_servicer_headers(),
    ))


def create_loan(
    borrower_id: str,
    origination_date: str = "2026-01-01T00:00:00Z",
    original_principal_cents: int = 30000000,
    original_property_value_cents: int = 35000000,
    interest_rate_bps: int = 600,
    term_months: int = 360,
    pmi_monthly_cents: int = 12500,
    **overrides,
) -> dict:
    """Originate a Loan (PRD §3.1). status=CURRENT, version=1."""
    payload = create_loan_payload(
        borrower_id=borrower_id,
        origination_date=origination_date,
        original_principal_cents=original_principal_cents,
        original_property_value_cents=original_property_value_cents,
        interest_rate_bps=interest_rate_bps,
        term_months=term_months,
        pmi_monthly_cents=pmi_monthly_cents,
        **overrides,
    )
    return get_success_data(api_client.create_loan(
        payload, make_loan_servicer_headers(),
    ))


def create_escrow_account(
    loan_id: str,
    annual_tax_cents: int = 480000,
    annual_insurance_cents: int = 120000,
    cushion_months: int = 2,
) -> dict:
    """Create an EscrowAccount tied to a Loan (PRD §3.6)."""
    payload = create_escrow_account_payload(
        loan_id=loan_id,
        annual_tax_cents=annual_tax_cents,
        annual_insurance_cents=annual_insurance_cents,
        cushion_months=cushion_months,
    )
    return get_success_data(api_client.create_escrow_account(
        payload, make_loan_servicer_headers(),
    ))


def post_payment(
    loan_id: str,
    amount_cents: int,
    received_at: str,
    posting_strategy: str = None,
) -> dict:
    """Post a payment (PRD §3.2)."""
    payload = create_payment_payload(
        amount_cents=amount_cents,
        received_at=received_at,
        posting_strategy=posting_strategy,
    )
    return get_success_data(api_client.post_payment(
        loan_id, payload, make_loan_servicer_headers(),
    ))


# ── Composite scenario builders ───────────────────────────────────────────

def setup_borrower_loan_escrow(
    clock_iso: str = "2026-01-01T00:00:00Z",
    origination_date: Optional[str] = None,
    original_principal_cents: int = 30000000,
    original_property_value_cents: int = 35000000,
    interest_rate_bps: int = 600,
    term_months: int = 360,
    pmi_monthly_cents: int = 12500,
    annual_tax_cents: int = 480000,
    annual_insurance_cents: int = 120000,
    cushion_months: int = 2,
    with_escrow: bool = True,
) -> dict:
    """One-call helper for "Borrower + Loan + (optional) EscrowAccount".

    Returns a dict with keys: borrower, loan, escrow_account (or None).
    """
    set_clock(clock_iso)
    borrower = create_borrower()
    loan = create_loan(
        borrower_id=borrower["id"],
        origination_date=origination_date or clock_iso,
        original_principal_cents=original_principal_cents,
        original_property_value_cents=original_property_value_cents,
        interest_rate_bps=interest_rate_bps,
        term_months=term_months,
        pmi_monthly_cents=pmi_monthly_cents,
    )
    escrow_account = None
    if with_escrow:
        escrow_account = create_escrow_account(
            loan_id=loan["id"],
            annual_tax_cents=annual_tax_cents,
            annual_insurance_cents=annual_insurance_cents,
            cushion_months=cushion_months,
        )
    return {
        "borrower": borrower,
        "loan": loan,
        "escrow_account": escrow_account,
    }


def setup_delinquent_loan(
    clock_iso: str = "2026-01-01T00:00:00Z",
    after_grace_iso: str = "2026-02-20T00:00:00Z",
    **loan_overrides,
) -> dict:
    """Bring a fresh loan into DELINQUENT by advancing the clock past
    next_due_date + GRACE_DAYS (PRD §3.3). Returns {borrower, loan,
    escrow_account}."""
    ctx = setup_borrower_loan_escrow(
        clock_iso=clock_iso, **loan_overrides,
    )
    set_clock(after_grace_iso)
    return ctx


def setup_foreclosure_filed(
    clock_iso: str = "2025-06-01T00:00:00Z",
    after_120_days_iso: str = "2025-11-01T00:00:00Z",
    **loan_overrides,
) -> dict:
    """Bring a loan into FORECLOSURE with its case in MEDIATION_REQUIRED
    (PRD §3.5)."""
    ctx = setup_borrower_loan_escrow(
        clock_iso=clock_iso, with_escrow=False, **loan_overrides,
    )
    set_clock(after_120_days_iso)
    loan_after = get_success_data(
        api_client.get_loan(ctx["loan"]["id"], make_loan_servicer_headers())
    )
    foreclosure = get_success_data(api_client.file_foreclosure(
        ctx["loan"]["id"], loan_after["version"],
        make_loan_servicer_headers(),
    ))
    ctx["loan"] = loan_after
    ctx["foreclosure_case"] = foreclosure
    return ctx


def setup_proposed_forbearance(
    clock_iso: str = "2025-06-01T00:00:00Z",
    after_grace_iso: str = "2025-07-25T00:00:00Z",
    start_date: str = "2025-08-01T00:00:00Z",
    end_date: str = "2025-10-31T00:00:00Z",
    reduced_payment_cents: int = 50000,
    **loan_overrides,
) -> dict:
    """Loan in DELINQUENT with a ForbearancePlan in PROPOSED."""
    ctx = setup_delinquent_loan(
        clock_iso=clock_iso, after_grace_iso=after_grace_iso,
        **loan_overrides,
    )
    plan = get_success_data(api_client.create_forbearance_plan(
        ctx["loan"]["id"],
        create_forbearance_plan_payload(
            start_date=start_date, end_date=end_date,
            reduced_payment_cents=reduced_payment_cents,
        ),
        make_loan_servicer_headers(),
    ))
    ctx["forbearance_plan"] = plan
    return ctx


def setup_active_forbearance(**kwargs) -> dict:
    """Loan in FORBEARANCE with a ForbearancePlan in ACTIVE (PRD §3.4)."""
    ctx = setup_proposed_forbearance(**kwargs)
    plan = get_success_data(api_client.activate_forbearance_plan(
        ctx["forbearance_plan"]["id"], make_loan_servicer_headers(),
    ))
    ctx["forbearance_plan"] = plan
    return ctx


def setup_case_in_mediation(
    clock_iso: str = "2025-06-01T00:00:00Z",
    after_120_days_iso: str = "2025-11-01T00:00:00Z",
    mediation_clock_iso: str = "2025-11-01T00:00:00Z",
    mediation_scheduled_for: str = "2025-11-15T00:00:00Z",
    **loan_overrides,
) -> dict:
    """Loan in FORECLOSURE with a scheduled MediationSession (case IN_MEDIATION).

    PRD §3.5: scheduled_for must be at or after current_utc + 14 days.
    """
    ctx = setup_foreclosure_filed(
        clock_iso=clock_iso, after_120_days_iso=after_120_days_iso,
        **loan_overrides,
    )
    set_clock(mediation_clock_iso)
    session = get_success_data(api_client.schedule_mediation_session(
        ctx["foreclosure_case"]["id"],
        create_mediation_session_payload(scheduled_for=mediation_scheduled_for),
        make_loan_servicer_headers(),
    ))
    ctx["mediation_session"] = session
    return ctx


def setup_pmi_request_pending(
    clock_iso: str = "2025-06-01T00:00:00Z",
    original_principal_cents: int = 32000000,
    original_property_value_cents: int = 40000000,
    pmi_monthly_cents: int = 13000,
    **loan_overrides,
) -> dict:
    """Loan + PMI removal request in PENDING (PRD §3.8)."""
    ctx = setup_borrower_loan_escrow(
        clock_iso=clock_iso,
        original_principal_cents=original_principal_cents,
        original_property_value_cents=original_property_value_cents,
        interest_rate_bps=loan_overrides.pop("interest_rate_bps", 600),
        term_months=loan_overrides.pop("term_months", 360),
        pmi_monthly_cents=pmi_monthly_cents,
        with_escrow=False,
        **loan_overrides,
    )
    pmi_req = get_success_data(api_client.create_pmi_removal_request(
        create_pmi_removal_request_payload(loan_id=ctx["loan"]["id"]),
        make_loan_servicer_headers(),
    ))
    ctx["pmi_request"] = pmi_req
    return ctx


def setup_loan_paid_off_with_scheduled_disbursement(
    clock_iso: str = "2025-12-01T00:00:00Z",
    original_principal_cents: int = 12000000,
    disbursement_amount_cents: int = 360000,
    disbursement_scheduled_for: str = "2026-04-15T00:00:00Z",
) -> dict:
    """Loan with very small balance + one SCHEDULED disbursement; then paid
    off in full (PRD §3.2 / §3.6).

    Returns ctx with keys borrower, loan, escrow_account, disbursement.
    """
    ctx = setup_borrower_loan_escrow(
        clock_iso=clock_iso,
        original_principal_cents=original_principal_cents,
        original_property_value_cents=30000000,
        interest_rate_bps=0,
        term_months=120,
        pmi_monthly_cents=0,
        annual_tax_cents=360000,
        annual_insurance_cents=60000,
    )
    disbursement = get_success_data(api_client.create_disbursement(
        ctx["escrow_account"]["id"],
        create_disbursement_payload(
            kind="TAX",
            amount_cents=disbursement_amount_cents,
            scheduled_for=disbursement_scheduled_for,
        ),
        make_loan_servicer_headers(),
    ))
    ctx["disbursement"] = disbursement
    return ctx


def fetch_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_loan(
        loan_id, make_loan_servicer_headers(),
    ))


def fetch_escrow_account(escrow_id: str) -> dict:
    return get_success_data(api_client.get_escrow_account(
        escrow_id, make_loan_servicer_headers(),
    ))


def fetch_disbursement(disbursement_id: str) -> dict:
    return get_success_data(api_client.get_disbursement(
        disbursement_id, make_loan_servicer_headers(),
    ))


def fetch_pmi_request(request_id: str) -> dict:
    return get_success_data(api_client.get_pmi_removal_request(
        request_id, make_loan_servicer_headers(),
    ))


def fetch_forbearance_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_forbearance_plan(
        plan_id, make_loan_servicer_headers(),
    ))


def fetch_foreclosure_case(case_id: str) -> dict:
    return get_success_data(api_client.get_foreclosure_case(
        case_id, make_loan_servicer_headers(),
    ))


def fetch_mediation_session(session_id: str) -> dict:
    return get_success_data(api_client.get_mediation_session(
        session_id, make_loan_servicer_headers(),
    ))
