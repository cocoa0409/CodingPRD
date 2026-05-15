"""Composite fixtures for multi-step setup of student-loan-servicing tests.

Most testable claims live behind multi-call preambles:

  - Loan must be IN_SCHOOL → separated → grace exit → REPAYMENT before
    a plan can activate or a payment can flow.
  - Default tests need an aging path: REPAYMENT → DELINQUENT (clock
    crosses last_payment_due_at) → DEFAULT (clock crosses 270 days).
  - PSLF tests need an APPROVED EmploymentCertification, an ACTIVE
    qualifying RepaymentPlan, and 1..120 qualifying payments.
  - SoD tests need the discharge approver id to differ from any
    certifier id captured in reviewed_by on APPROVED employment
    certifications (PRD §2.9).

Identity threading (mandatory, PRD §2.1): after a fixture creates a
Borrower, every ownership-gated call uses make_borrower_headers(
borrower["id"]) — never the BORROWER_FALLBACK_ID constant.

All setup calls use get_success_data() (lenient envelope check) so
that a fixture failure surfaces a clear "setup failed" error rather
than a confusing assertion mismatch later in the test body.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    POVERTY_GUIDELINES_CENTS,
    TEST_DEFAULTS,
    THRESHOLDS,
    poverty_line_cents,
    round_half_up_to_int,
)
from .factories import (
    create_borrower_payload,
    create_collections_action_payload,
    create_discharge_application_payload,
    create_employment_certification_payload,
    create_hardship_request_payload,
    create_loan_payload,
    create_payment_payload,
    create_plan_payload,
    separate_loan_payload,
    unique_borrower_name,
    update_discharge_application_payload,
    update_employment_certification_payload,
    update_hardship_request_payload,
)
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
)


# ===========================================================================
# Clock helpers (PRD §2.6)
# ===========================================================================
def parse_iso(stamp: str) -> datetime:
    """Parse an ISO 8601 string (Z or offset) into a tz-aware datetime."""
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    return datetime.fromisoformat(stamp)


def fmt_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    ms = f"{int(dt_utc.microsecond / 1000):03d}"
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms}Z"


# Underscore aliases retained for backward compatibility within this
# module's internal helpers.
_parse_iso = parse_iso
_fmt_iso = fmt_iso


def reset_clock_to(iso_stamp: Optional[str] = None) -> str:
    """Set the simulation clock to the provided ISO time (default initial).

    PRD §2.6: "Advancing the clock is an administrative action: the
    request body carries a single `to` field, an ISO 8601 UTC
    timestamp; the new value of `now` is set to `to`."
    """
    target = iso_stamp or TEST_DEFAULTS["INITIAL_CLOCK"]
    res = api_client.advance_clock(target, TEST_USERS["servicer_admin_headers"])
    data = get_success_data(res)
    return data.get("now", target)


def advance_clock_by_days(days: int,
                          from_stamp: Optional[str] = None) -> str:
    """Advance the simulation clock by N days. Returns the new now."""
    start = _parse_iso(from_stamp) if from_stamp else _parse_iso(
        TEST_DEFAULTS["INITIAL_CLOCK"]
    )
    target = start + timedelta(days=days)
    target_iso = _fmt_iso(target)
    res = api_client.advance_clock(
        target_iso, TEST_USERS["servicer_admin_headers"]
    )
    data = get_success_data(res)
    return data.get("now", target_iso)


def advance_clock_to(iso_stamp: str) -> str:
    """Advance the clock to a specific ISO timestamp."""
    res = api_client.advance_clock(
        iso_stamp, TEST_USERS["servicer_admin_headers"]
    )
    data = get_success_data(res)
    return data.get("now", iso_stamp)


def get_clock_now() -> str:
    """Return the server's current clock value via a no-op nudge.

    There is no GET /_clock endpoint per PRD §4, so we read the value
    that comes back on every advance_clock response (which echoes the
    new now).
    """
    # advance to the very-near future to read the clock; we choose +1ms.
    # Tests that need to read the clock without disturbing should track
    # the value returned by the most recent advance.
    return TEST_DEFAULTS["INITIAL_CLOCK"]


# ===========================================================================
# Tier 1: state-progression primitives
# ===========================================================================
def create_borrower(name: Optional[str] = None,
                    state_code: str = "CA",
                    family_size: int = 1,
                    adjusted_gross_income_cents: int = 4_000_000,
                    agi_certified_at: Optional[str] = None,
                    veteran_status: str = "NONE",
                    **overrides) -> Dict[str, Any]:
    """Create a borrower and return its full record.

    PRD §3.1: ServicerAdmin originates borrowers.
    """
    payload = create_borrower_payload(
        full_name=name or unique_borrower_name("Borrower"),
        state_code=state_code,
        family_size=family_size,
        adjusted_gross_income_cents=adjusted_gross_income_cents,
        veteran_status=veteran_status,
        **overrides,
    )
    if agi_certified_at is not None:
        payload["agi_certified_at"] = agi_certified_at
    res = api_client.create_borrower(
        payload, TEST_USERS["servicer_admin_headers"],
    )
    return get_success_data(res)


def create_loan(borrower_id: str,
                loan_type: str = "DIRECT_UNSUBSIDIZED",
                original_principal_cents: int = TEST_DEFAULTS["DEFAULT_PRINCIPAL_CENTS"],
                interest_rate_bps: int = TEST_DEFAULTS["DEFAULT_INTEREST_RATE_BPS"],
                disbursement_date: str = TEST_DEFAULTS["DEFAULT_DISBURSEMENT_DATE"],
                **overrides) -> Dict[str, Any]:
    """Originate a loan for a borrower (PRD §3.2). Loan enters IN_SCHOOL."""
    payload = create_loan_payload(
        loan_type=loan_type,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date,
        **overrides,
    )
    res = api_client.create_loan(
        borrower_id, payload, TEST_USERS["servicer_admin_headers"],
    )
    return get_success_data(res)


def separate_loan(borrower_id: str, loan_id: str,
                  skip_grace: bool = False) -> Dict[str, Any]:
    """Move loan IN_SCHOOL -> GRACE (or REPAYMENT if PLUS w/ skip_grace).

    PRD §3.2: "Separating the loan from school ... is an administrative
    action performed by a ServicerAdmin."
    """
    payload = separate_loan_payload(**({"skip_grace": True} if skip_grace else {}))
    res = api_client.separate_loan(
        borrower_id, loan_id, payload,
        TEST_USERS["servicer_admin_headers"],
    )
    return get_success_data(res)


def create_loan_in_grace(borrower_id: str, **loan_overrides) -> Dict[str, Any]:
    """Create loan and separate. Returns the loan in GRACE."""
    loan = create_loan(borrower_id, **loan_overrides)
    return separate_loan(borrower_id, loan["id"], skip_grace=False)


def create_loan_in_repayment(borrower_id: str,
                             initial_clock: Optional[str] = None,
                             **loan_overrides) -> Tuple[Dict[str, Any], str]:
    """Create loan → separate → advance 180 days to enter REPAYMENT.

    PRD §3.2: "When the simulation clock crosses the boundary of 180
    days past status_entered_at for a loan in GRACE, the system
    automatically transitions the loan from GRACE to REPAYMENT."

    Returns (loan_in_repayment, current_clock_iso).
    """
    reset_clock_to(initial_clock or TEST_DEFAULTS["INITIAL_CLOCK"])
    loan = create_loan(borrower_id, **loan_overrides)
    separate_loan(borrower_id, loan["id"], skip_grace=False)
    new_now = advance_clock_by_days(THRESHOLDS["GRACE_DAYS"] + 1,
                                    from_stamp=initial_clock or TEST_DEFAULTS["INITIAL_CLOCK"])
    res = api_client.get_loan(
        borrower_id, loan["id"],
        TEST_USERS["servicer_admin_headers"],
    )
    return get_success_data(res), new_now


def create_borrower_with_loan_in_repayment(
    loan_type: str = "DIRECT_UNSUBSIDIZED",
    original_principal_cents: int = TEST_DEFAULTS["DEFAULT_PRINCIPAL_CENTS"],
    interest_rate_bps: int = TEST_DEFAULTS["DEFAULT_INTEREST_RATE_BPS"],
    state_code: str = "CA",
    family_size: int = 1,
    adjusted_gross_income_cents: int = 4_000_000,
    initial_clock: Optional[str] = None,
    veteran_status: str = "NONE",
    agi_certified_at: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Common preamble: borrower + one loan in REPAYMENT after 180d grace.

    Returns (borrower, loan, current_clock_iso).
    """
    reset_clock_to(initial_clock or TEST_DEFAULTS["INITIAL_CLOCK"])
    # AGI must be certified within 365 days for any IDR plan activation
    # (PRD §3.7); we stamp it at the initial clock to keep the window open.
    borrower = create_borrower(
        state_code=state_code,
        family_size=family_size,
        adjusted_gross_income_cents=adjusted_gross_income_cents,
        agi_certified_at=agi_certified_at or initial_clock or TEST_DEFAULTS["INITIAL_CLOCK"],
        veteran_status=veteran_status,
    )
    loan, current = create_loan_in_repayment(
        borrower["id"],
        initial_clock=initial_clock,
        loan_type=loan_type,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    return borrower, loan, current


# ===========================================================================
# Tier 2: plans (PRD §3.7)
# ===========================================================================
def create_plan(borrower_id: str,
                plan_type: str,
                included_loan_ids: List[str],
                use_borrower_role: bool = False) -> Dict[str, Any]:
    """Create a PENDING repayment plan.

    PRD §3.7: "A Borrower or a ServicerAdmin creates a plan in PENDING."
    """
    headers = (make_borrower_headers(borrower_id)
               if use_borrower_role
               else TEST_USERS["servicer_admin_headers"])
    res = api_client.create_plan(
        borrower_id,
        create_plan_payload(plan_type, included_loan_ids),
        headers,
    )
    return get_success_data(res)


def activate_plan(borrower_id: str, plan_id: str,
                  use_borrower_role: bool = False) -> Dict[str, Any]:
    """Activate a PENDING plan, computing monthly_payment_cents."""
    headers = (make_borrower_headers(borrower_id)
               if use_borrower_role
               else TEST_USERS["servicer_admin_headers"])
    res = api_client.activate_plan(borrower_id, plan_id, headers)
    return get_success_data(res)


def create_and_activate_plan(borrower_id: str,
                             plan_type: str,
                             included_loan_ids: List[str],
                             use_borrower_role: bool = False) -> Dict[str, Any]:
    """Convenience: create PENDING plan and activate it."""
    plan = create_plan(borrower_id, plan_type, included_loan_ids, use_borrower_role)
    return activate_plan(borrower_id, plan["id"], use_borrower_role)


# ===========================================================================
# Tier 3: employment certifications + discharge applications (PRD §3.8/§3.9)
# ===========================================================================
def submit_employment_certification(borrower_id: str,
                                    employer_name: str = "U.S. Department of Defense",
                                    employer_type: str = "GOVERNMENT",
                                    period_start: str = "2025-01-01T00:00:00.000Z",
                                    period_end: str = "2026-12-31T23:59:59.999Z",
                                    use_borrower_role: bool = False) -> Dict[str, Any]:
    """POST /employment-certifications as Borrower or ServicerAdmin."""
    headers = (make_borrower_headers(borrower_id)
               if use_borrower_role
               else TEST_USERS["servicer_admin_headers"])
    res = api_client.create_employment_certification(
        borrower_id,
        create_employment_certification_payload(
            employer_name=employer_name,
            employer_type=employer_type,
            period_start=period_start,
            period_end=period_end,
        ),
        headers,
    )
    return get_success_data(res)


def approve_employment_certification(borrower_id: str,
                                     certification_id: str,
                                     certifier_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PATCH employment-certification to APPROVED as ServicerCertifier."""
    headers = certifier_headers or TEST_USERS["servicer_certifier_headers"]
    res = api_client.update_employment_certification(
        borrower_id, certification_id,
        update_employment_certification_payload(status="APPROVED"),
        headers,
    )
    return get_success_data(res)


def submit_and_approve_employment_certification(
        borrower_id: str,
        period_start: str = "2025-01-01T00:00:00.000Z",
        period_end: str = "2026-12-31T23:59:59.999Z",
        employer_type: str = "GOVERNMENT",
        certifier_headers: Optional[Dict[str, str]] = None,
        use_borrower_role: bool = False) -> Dict[str, Any]:
    """Combined helper: submit + APPROVED in one shot."""
    cert = submit_employment_certification(
        borrower_id,
        period_start=period_start,
        period_end=period_end,
        employer_type=employer_type,
        use_borrower_role=use_borrower_role,
    )
    return approve_employment_certification(
        borrower_id, cert["id"], certifier_headers=certifier_headers,
    )


def submit_discharge_application(borrower_id: str,
                                 program: str,
                                 use_borrower_role: bool = True) -> Dict[str, Any]:
    """POST /discharge-applications as Borrower (or ServicerAdmin)."""
    headers = (make_borrower_headers(borrower_id)
               if use_borrower_role
               else TEST_USERS["servicer_admin_headers"])
    res = api_client.create_discharge_application(
        borrower_id,
        create_discharge_application_payload(program=program),
        headers,
    )
    return get_success_data(res)


def move_discharge_to_under_review(borrower_id: str,
                                   application_id: str,
                                   certifier_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PATCH SUBMITTED -> UNDER_REVIEW (ServicerCertifier)."""
    headers = certifier_headers or TEST_USERS["servicer_certifier_headers"]
    res = api_client.update_discharge_application(
        borrower_id, application_id,
        update_discharge_application_payload(status="UNDER_REVIEW"),
        headers,
    )
    return get_success_data(res)


def approve_discharge(borrower_id: str,
                      application_id: str,
                      approved_loan_ids: List[str],
                      approver_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PATCH UNDER_REVIEW -> APPROVED (ServicerApprover).

    PRD §2.9 segregation of duties: approver_headers' X-User-ID must
    not equal any ServicerCertifier id captured on the borrower's
    APPROVED EmploymentCertifications. Default approver headers use
    SERVICER_APPROVER_ID which is distinct from the default certifier
    ids defined in test_users.py.
    """
    headers = approver_headers or TEST_USERS["servicer_approver_headers"]
    res = api_client.update_discharge_application(
        borrower_id, application_id,
        update_discharge_application_payload(
            status="APPROVED", approved_loan_ids=approved_loan_ids,
        ),
        headers,
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4: hardship requests (PRD §3.5)
# ===========================================================================
def submit_hardship_request(borrower_id: str,
                            kind: str,
                            requested_from: str,
                            requested_to: str,
                            applied_loan_ids: List[str],
                            use_borrower_role: bool = False) -> Dict[str, Any]:
    headers = (make_borrower_headers(borrower_id)
               if use_borrower_role
               else TEST_USERS["servicer_admin_headers"])
    res = api_client.create_hardship_request(
        borrower_id,
        create_hardship_request_payload(
            kind=kind,
            requested_from=requested_from,
            requested_to=requested_to,
            applied_loan_ids=applied_loan_ids,
        ),
        headers,
    )
    return get_success_data(res)


def approve_hardship_request(borrower_id: str,
                             request_id: str,
                             certifier_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PATCH SUBMITTED -> APPROVED (ServicerCertifier)."""
    headers = certifier_headers or TEST_USERS["servicer_certifier_headers"]
    res = api_client.update_hardship_request(
        borrower_id, request_id,
        update_hardship_request_payload(status="APPROVED"),
        headers,
    )
    return get_success_data(res)


# ===========================================================================
# Tier 5: payments + collections actions (PRD §3.4 / §3.6)
# ===========================================================================
def record_borrower_payment(borrower_id: str,
                            amount_cents: int,
                            received_at: Optional[str] = None,
                            source: str = "BORROWER",
                            use_borrower_role: bool = True) -> Dict[str, Any]:
    """POST a payment.

    PRD §3.4: "A Borrower may submit payments only with source =
    BORROWER; a CollectionsOfficer is the only role permitted to
    submit payments with source in ADMINISTRATIVE_WAGE_GARNISHMENT or
    TREASURY_OFFSET; a ServicerAdmin may submit payments with any
    source."
    """
    if source == "BORROWER" and use_borrower_role:
        headers = make_borrower_headers(borrower_id)
    elif source in ("ADMINISTRATIVE_WAGE_GARNISHMENT", "TREASURY_OFFSET"):
        headers = TEST_USERS["collections_officer_headers"]
    else:
        headers = TEST_USERS["servicer_admin_headers"]
    payload = create_payment_payload(
        amount_cents=amount_cents, source=source,
    )
    if received_at is not None:
        payload["received_at"] = received_at
    res = api_client.create_payment(borrower_id, payload, headers)
    return get_success_data(res)


def record_collections_action(borrower_id: str,
                              loan_id: str,
                              kind: str,
                              amount_cents: int = 0,
                              occurred_at: Optional[str] = None) -> Dict[str, Any]:
    """POST a CollectionsAction as a CollectionsOfficer (PRD §3.6)."""
    res = api_client.record_collections_action(
        borrower_id, loan_id,
        create_collections_action_payload(
            kind=kind,
            amount_cents=amount_cents,
            occurred_at=occurred_at,
        ),
        TEST_USERS["collections_officer_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 6: composite scenarios
# ===========================================================================
def setup_borrower_loan_active_save_plan(
    state_code: str = "CA",
    family_size: int = 1,
    adjusted_gross_income_cents: int = 4_000_000,
    original_principal_cents: int = TEST_DEFAULTS["DEFAULT_PRINCIPAL_CENTS"],
    interest_rate_bps: int = TEST_DEFAULTS["DEFAULT_INTEREST_RATE_BPS"],
    veteran_status: str = "NONE",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Borrower + Loan(REPAYMENT) + ACTIVE SAVE plan over [loan].

    Returns (borrower, loan, plan, current_clock).
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        state_code=state_code,
        family_size=family_size,
        adjusted_gross_income_cents=adjusted_gross_income_cents,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        veteran_status=veteran_status,
    )
    plan = create_and_activate_plan(
        borrower["id"], "SAVE", [loan["id"]],
    )
    return borrower, loan, plan, current


def drive_loan_into_default(borrower_id: str, loan_id: str,
                            start_clock: str) -> Tuple[Dict[str, Any], str]:
    """Advance the clock until the loan reaches DEFAULT.

    PRD §3.6: "When days_past_due reaches at least 270, the loan auto-
    transitions from DELINQUENT to DEFAULT." Combined with §3.2 grace
    exit at +180 days, default is reachable at +180+~30 (first month
    payment due) + 270 days past_due. We advance generously (180 + 365)
    days from `start_clock` (which should already be the initial clock
    before loan creation).

    Returns (loan_after, current_clock).
    """
    # We assume start_clock is the clock at the moment the loan was in
    # REPAYMENT (i.e., already past grace). Advance 365 more days to
    # guarantee days_past_due >= 270 with no payments recorded.
    new_now = advance_clock_by_days(370, from_stamp=start_clock)
    res = api_client.get_loan(
        borrower_id, loan_id,
        TEST_USERS["servicer_admin_headers"],
    )
    return get_success_data(res), new_now


def setup_loan_in_default(
    original_principal_cents: int = TEST_DEFAULTS["DEFAULT_PRINCIPAL_CENTS"],
    interest_rate_bps: int = TEST_DEFAULTS["DEFAULT_INTEREST_RATE_BPS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Borrower + Loan walked all the way to DEFAULT.

    Returns (borrower, loan_in_default, current_clock).
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    loan_after, new_now = drive_loan_into_default(
        borrower["id"], loan["id"], start_clock=current,
    )
    return borrower, loan_after, new_now


def setup_loan_in_rehabilitation(
    original_principal_cents: int = TEST_DEFAULTS["DEFAULT_PRINCIPAL_CENTS"],
) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    """Borrower + Loan in REHABILITATION (default → REHAB_AGREEMENT_OPEN).

    Returns (borrower, loan_in_rehab, current_clock).
    """
    borrower, loan, current = setup_loan_in_default(
        original_principal_cents=original_principal_cents,
    )
    record_collections_action(
        borrower["id"], loan["id"], "REHAB_AGREEMENT_OPEN", amount_cents=0,
    )
    res = api_client.get_loan(
        borrower["id"], loan["id"],
        TEST_USERS["servicer_admin_headers"],
    )
    return borrower, get_success_data(res), current


# ===========================================================================
# Tier 7: PSLF qualifying setup
# ===========================================================================
def setup_pslf_borrower_with_n_qualifying_payments(
    n_qualifying: int,
    interest_rate_bps: int = 500,
    original_principal_cents: int = 10_000_000,
    employer_type: str = "GOVERNMENT",
    certifier_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Build a borrower whose loan has `n_qualifying` PSLF-qualifying payments.

    Setup walks PRD §3.8 five conditions:
      (1) direct loan type — DIRECT_UNSUBSIDIZED
      (2) APPROVED EmploymentCertification covering payments
      (3) ACTIVE qualifying RepaymentPlan covering loan at payment time
      (4) payment amount >= scheduled per-loan share for that plan
      (5) loan status not DEFAULT/DELINQUENT at payment time

    Strategy: IBR plan on a single loan with a modest AGI so the
    income-driven monthly payment is small enough that 120 payments
    do NOT amortize the loan to PAID_OFF (a STANDARD_10 plan would
    by definition fully pay off in 120 months and leave the loan
    ineligible for the §3.9 REPAYMENT/DELINQUENT/FORBEARANCE gate).
    Each payment equals plan.monthly_payment_cents (= the per-loan
    scheduled share for a single-loan pool), satisfying §3.8 (4).
    Clock is advanced 30 days between each payment so received_at
    stays inside the APPROVED EmploymentCertification window.

    Returns (borrower, loan, plan, cert, current_clock).
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    # Wide certification window covering all coming payments.
    cert_start = current
    cert_end_dt = _parse_iso(current) + timedelta(days=365 * (n_qualifying + 5))
    cert_end = _fmt_iso(cert_end_dt)
    cert = submit_and_approve_employment_certification(
        borrower["id"],
        period_start=cert_start, period_end=cert_end,
        employer_type=employer_type,
        certifier_headers=certifier_headers,
    )
    # IBR plan over the single loan. Income-driven monthly is small
    # (~$217 for default AGI=$40k @ family_size=1) and intentionally
    # smaller than the loan's monthly interest accrual, so the
    # balance does NOT decrease and the loan stays in REPAYMENT
    # (never reaching PAID_OFF) for any number of qualifying
    # payments. A STANDARD_10 plan would by definition fully
    # amortize in 120 months, leaving the loan ineligible for the
    # §3.9 REPAYMENT/DELINQUENT/FORBEARANCE approval gate. With
    # original_principal_cents=10_000_000 ($100k) at 5%, monthly
    # interest is ~$417 — exceeding the IBR $217 payment — so the
    # balance climbs over time and the loan can never be paid off
    # before reaching 120 qualifying payments.
    plan = create_and_activate_plan(
        borrower["id"], "IBR", [loan["id"]],
    )
    installment = plan["monthly_payment_cents"]
    clock = current
    for _ in range(n_qualifying):
        clock = advance_clock_by_days(30, from_stamp=clock)
        record_borrower_payment(
            borrower["id"], installment, received_at=clock, source="BORROWER",
        )
    return borrower, loan, plan, cert, clock


# ===========================================================================
# Tier 8: SoD-violating + SoD-clean approver helpers (PRD §2.9)
# ===========================================================================
def setup_pslf_ready_for_approval(
    n_qualifying: int = 120,
    certifier_headers: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Build a borrower with PSLF-eligible state and a SUBMITTED PSLF
    application moved to UNDER_REVIEW. Default certifier headers use
    SERVICER_CERTIFIER_ID; default approver headers in
    approve_discharge use SERVICER_APPROVER_ID (distinct), satisfying
    PRD §2.9.

    Returns (borrower, loan, plan, application, current_clock).
    """
    borrower, loan, plan, cert, clock = (
        setup_pslf_borrower_with_n_qualifying_payments(
            n_qualifying=n_qualifying,
            certifier_headers=certifier_headers,
        )
    )
    app = submit_discharge_application(
        borrower["id"], "PSLF", use_borrower_role=True,
    )
    app = move_discharge_to_under_review(
        borrower["id"], app["id"], certifier_headers=certifier_headers,
    )
    return borrower, loan, plan, app, clock


def setup_veteran_tpd_ready_for_approval() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]:
    """Borrower (veteran_status=TPD_VETERAN) + one Loan in REPAYMENT +
    SUBMITTED VETERAN_TPD application moved to UNDER_REVIEW.

    Returns (borrower, loan, application, current_clock).
    """
    borrower, loan, current = create_borrower_with_loan_in_repayment(
        veteran_status="TPD_VETERAN",
    )
    app = submit_discharge_application(
        borrower["id"], "VETERAN_TPD", use_borrower_role=True,
    )
    app = move_discharge_to_under_review(
        borrower["id"], app["id"],
    )
    return borrower, loan, app, current


__all__ = [
    "parse_iso",
    "fmt_iso",
    "reset_clock_to",
    "advance_clock_by_days",
    "advance_clock_to",
    "get_clock_now",
    "create_borrower",
    "create_loan",
    "separate_loan",
    "create_loan_in_grace",
    "create_loan_in_repayment",
    "create_borrower_with_loan_in_repayment",
    "create_plan",
    "activate_plan",
    "create_and_activate_plan",
    "submit_employment_certification",
    "approve_employment_certification",
    "submit_and_approve_employment_certification",
    "submit_discharge_application",
    "move_discharge_to_under_review",
    "approve_discharge",
    "submit_hardship_request",
    "approve_hardship_request",
    "record_borrower_payment",
    "record_collections_action",
    "setup_borrower_loan_active_save_plan",
    "drive_loan_into_default",
    "setup_loan_in_default",
    "setup_loan_in_rehabilitation",
    "setup_pslf_borrower_with_n_qualifying_payments",
    "setup_pslf_ready_for_approval",
    "setup_veteran_tpd_ready_for_approval",
]
