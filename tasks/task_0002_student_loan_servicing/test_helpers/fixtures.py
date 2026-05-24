"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup step failed" errors rather than confusing assertion failures.

Each helper rebuilds its full preconditions from scratch — the harness restarts
the API process before every test, so the database is always empty and nothing
carries over between tests.
"""
from typing import Optional, Tuple, List, Dict
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_borrower_payload,
    create_loan_payload,
    create_servicing_event_payload,
    create_standard_10yr_plan_payload,
    create_idr_plan_payload,
    create_payment_payload,
    create_employment_certification_payload,
    create_pslf_tracker_payload,
    force_pslf_tracker_state_payload,
    create_discharge_application_payload,
    approve_discharge_payload,
    advance_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_servicer_headers,
    make_pslf_adjudicator_headers,
    make_va_officer_headers,
)


# ─── Low-level helpers ───────────────────────────────


def advance_clock(to_iso8601: str, headers=None):
    """Advance the simulation clock; idempotent setup primitive."""
    h = headers or TEST_USERS["servicer_headers"]
    return get_success_data(api_client.advance_clock(advance_clock_payload(to_iso8601), h))


def create_borrower(headers=None, **overrides) -> dict:
    h = headers or TEST_USERS["servicer_headers"]
    return get_success_data(api_client.create_borrower(
        create_borrower_payload(**overrides), h,
    ))


def create_loan(borrower_id: str, headers=None, **overrides) -> dict:
    h = headers or TEST_USERS["servicer_headers"]
    return get_success_data(api_client.create_loan(
        create_loan_payload(borrower_id, **overrides), h,
    ))


def fire_servicing_event(loan_id: str, event_type: str, effective_on: str,
                          reason_code: str = "OTHER", headers=None) -> dict:
    h = headers or TEST_USERS["servicer_headers"]
    return get_success_data(api_client.create_servicing_event(
        loan_id,
        create_servicing_event_payload(event_type, effective_on, reason_code),
        h,
    ))


def get_loan_version(loan_id: str, headers=None) -> int:
    """Read the loan's current version. Required between any two mutations that
    feed an OCC-guarded endpoint (POST /repayment-plans, POST /discharge-applications/{id}/approve)."""
    h = headers or TEST_USERS["servicer_headers"]
    loan = get_success_data(api_client.get_loan(loan_id, h))
    return loan["version"]


def get_loan(loan_id: str, headers=None) -> dict:
    h = headers or TEST_USERS["servicer_headers"]
    return get_success_data(api_client.get_loan(loan_id, h))


# ─── Tier 1 / Tier 2 — Loan to REPAYMENT with optional plan ───


def create_loan_in_grace(
    *,
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2026-06-01",
    loan_type: str = "DIRECT_UNSUBSIDIZED",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
    borrower_overrides: Optional[dict] = None,
) -> Tuple[dict, dict]:
    """Create a Borrower + Loan and walk the Loan IN_SCHOOL → GRACE.

    Returns (borrower, loan). The clock is NOT advanced here — callers control
    the clock to suit their own time-gated assertions.
    """
    borrower = create_borrower(**(borrower_overrides or {}))
    loan = create_loan(
        borrower["id"],
        loan_type=loan_type,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date,
    )
    fire_servicing_event(loan["id"], "GRACE_BEGIN", grace_begin_on, "OTHER")
    return borrower, loan


def create_loan_in_repayment(
    *,
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2026-06-01",
    repayment_begin_on: str = "2026-06-01",
    loan_type: str = "DIRECT_UNSUBSIDIZED",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
    borrower_overrides: Optional[dict] = None,
) -> Tuple[dict, dict]:
    """Create a Borrower + Loan and walk the Loan IN_SCHOOL → GRACE → REPAYMENT.

    Returns (borrower, loan_after_repayment_begin). The plan is NOT created
    here — callers attach a plan with the version they observe.
    """
    borrower, _loan = create_loan_in_grace(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        loan_type=loan_type,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        borrower_overrides=borrower_overrides,
    )
    fire_servicing_event(_loan["id"], "REPAYMENT_BEGIN", repayment_begin_on, "GRACE_EXPIRY")
    loan = get_loan(_loan["id"])
    return borrower, loan


def attach_standard_10yr_plan(loan_id: str, *, state_of_residence: str = "CONTIGUOUS",
                               headers=None) -> dict:
    """Attach a STANDARD_10YR plan to a loan in {GRACE, REPAYMENT, DEFERMENT, FORBEARANCE, DELINQUENT}.

    Reads the loan's current version to satisfy expected_loan_version.
    """
    h = headers or TEST_USERS["servicer_headers"]
    v = get_loan_version(loan_id, h)
    payload = create_standard_10yr_plan_payload(loan_id, v, state_of_residence)
    return get_success_data(api_client.create_repayment_plan(payload, h))


def attach_idr_plan(loan_id: str, plan_type: str, agi_cents: int, family_size: int,
                     *, state_of_residence: str = "CONTIGUOUS", headers=None) -> dict:
    h = headers or TEST_USERS["servicer_headers"]
    v = get_loan_version(loan_id, h)
    payload = create_idr_plan_payload(
        loan_id, plan_type, agi_cents, family_size, v, state_of_residence,
    )
    return get_success_data(api_client.create_repayment_plan(payload, h))


def setup_loan_in_repayment_with_standard_plan(
    *,
    clock_set_to: str = "2026-06-01T00:00:00Z",
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2026-06-01",
    repayment_begin_on: str = "2026-06-01",
    loan_type: str = "DIRECT_UNSUBSIDIZED",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
    state_of_residence: str = "CONTIGUOUS",
    borrower_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict]:
    """Full setup through REPAYMENT with an ACTIVE STANDARD_10YR plan.

    Returns (borrower, loan, plan). Advances the clock before any creation so
    that the loan/plan dates make sense relative to the clock.
    """
    advance_clock(clock_set_to)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        repayment_begin_on=repayment_begin_on,
        loan_type=loan_type,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        borrower_overrides=borrower_overrides,
    )
    plan = attach_standard_10yr_plan(loan["id"], state_of_residence=state_of_residence)
    return borrower, loan, plan


# ─── Tier 3 — Reach derived states (FORBEARANCE, PAID_OFF, DELINQUENT, DEFAULT, DISCHARGED) ───


def setup_loan_in_forbearance(
    *,
    clock_set_to: str = "2026-06-01T00:00:00Z",
    forbearance_begin_on: str = "2026-06-01",
    **kwargs,
) -> Tuple[dict, dict, dict]:
    """REPAYMENT → FORBEARANCE. Returns (borrower, loan_latest, plan)."""
    borrower, loan, plan = setup_loan_in_repayment_with_standard_plan(
        clock_set_to=clock_set_to, **kwargs,
    )
    fire_servicing_event(
        loan["id"], "FORBEARANCE_BEGIN", forbearance_begin_on, "ECONOMIC_HARDSHIP",
    )
    loan_after = get_loan(loan["id"])
    return borrower, loan_after, plan


def setup_loan_paid_off(
    *,
    clock_set_to: str = "2026-06-01T00:00:00Z",
    disbursement_date: str = "2025-12-01",
    grace_begin_on: str = "2025-12-01",
    repayment_begin_on: str = "2026-06-01",
    original_principal_cents: int = 100_000,
    interest_rate_bps: int = 0,
    payment_posted_on: str = "2026-06-01",
) -> Tuple[dict, dict]:
    """Full setup through PAID_OFF. Uses zero-interest small loan paid in one shot.

    Returns (borrower, loan_after_payoff).
    """
    advance_clock(clock_set_to)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        repayment_begin_on=repayment_begin_on,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    attach_standard_10yr_plan(loan["id"])
    get_success_data(api_client.create_payment(
        create_payment_payload(
            loan["id"], original_principal_cents, payment_posted_on, "ACH",
        ),
        TEST_USERS["servicer_headers"],
    ))
    loan_after = get_loan(loan["id"])
    return borrower, loan_after


def setup_loan_in_default(
    *,
    clock_initial: str = "2026-06-01T00:00:00Z",
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2025-06-01",
    repayment_begin_on: str = "2026-06-01",
    advance_to: str = "2027-03-28T00:00:00Z",
    original_principal_cents: int = 200_000,
    interest_rate_bps: int = 0,
) -> Tuple[dict, dict]:
    """Drive a loan into DEFAULT via clock-advance past 270 days delinquent.

    The clock advance from REPAYMENT (no payments made) crosses both the first
    missed scheduled due date (→ DELINQUENT, opens a DelinquencyRecord) and
    270 days after that (→ DEFAULT).
    Returns (borrower, loan_after_default).
    """
    advance_clock(clock_initial)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        repayment_begin_on=repayment_begin_on,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock(advance_to)
    loan_after = get_loan(loan["id"])
    return borrower, loan_after


def setup_loan_in_delinquent_via_clock(
    *,
    clock_initial: str = "2026-06-01T00:00:00Z",
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2025-06-01",
    repayment_begin_on: str = "2026-06-01",
    advance_to: str = "2026-07-17T00:00:00Z",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
) -> Tuple[dict, dict]:
    """Drive a loan into DELINQUENT (without yet crossing the 270-day boundary).

    Returns (borrower, loan_after_delinquent).
    """
    advance_clock(clock_initial)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        repayment_begin_on=repayment_begin_on,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    attach_standard_10yr_plan(loan["id"])
    advance_clock(advance_to)
    loan_after = get_loan(loan["id"])
    return borrower, loan_after


# ─── Tier 4 — Veteran discharge: borrower with a fully DISCHARGED roster ───


def setup_borrower_with_all_loans_discharged_veteran(
    *,
    clock_set_to: str = "2026-06-01T00:00:00Z",
    filed_on: str = "2026-06-01",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
    disbursement_date: str = "2025-06-01",
) -> Tuple[dict, dict, dict]:
    """Veteran borrower with one Loan, all driven to DISCHARGED via an approved
    VETERAN_TOTAL_PERMANENT_DISABILITY application. After this fixture every
    Loan for the borrower is in {DISCHARGED, PAID_OFF} so any further
    POST /v1/payments attempt must trip ERR_BORROWER_DISCHARGED per PRD §3.4.

    Returns (borrower, loan_after_discharge, application_after_approve).
    """
    advance_clock(clock_set_to)
    borrower = create_borrower(military_status="VETERAN")
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date,
    )
    app = get_success_data(api_client.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
            filed_on, va_certification_doc_id="VA-DOC-FIXTURE",
        ),
        TEST_USERS["servicer_headers"],
    ))
    get_success_data(api_client.begin_review_discharge_application(
        app["id"], TEST_USERS["va_officer_headers"],
    ))
    loan_version = get_loan_version(loan["id"])
    approved_app = get_success_data(api_client.approve_discharge_application(
        app["id"],
        approve_discharge_payload({loan["id"]: loan_version}),
        TEST_USERS["va_officer_headers"],
    ))
    loan_after = get_loan(loan["id"])
    return borrower, loan_after, approved_app


# ─── Tier 5 — PSLF tracker at threshold ──────────────


def setup_pslf_tracker_at_threshold(
    borrower_id: str,
    *,
    qualifying_payment_count: int = 120,
    status: str = "ELIGIBLE_FOR_FORGIVENESS",
    adjudicator_user_id: str = "adj-test-1",
) -> dict:
    """Initialize a PSLFTracker for the borrower and force it to
    {qualifying_payment_count, status} via the test-driving endpoint.

    Returns the tracker after force-state.
    """
    h_adj = make_pslf_adjudicator_headers(adjudicator_user_id)
    tracker = get_success_data(api_client.create_pslf_tracker(
        create_pslf_tracker_payload(borrower_id), h_adj,
    ))
    get_success_data(api_client.force_pslf_tracker_state(
        tracker["id"],
        force_pslf_tracker_state_payload(qualifying_payment_count, status),
        h_adj,
    ))
    return get_success_data(api_client.get_pslf_tracker(tracker["id"], h_adj))


def setup_pslf_discharge_ready(
    *,
    clock_initial: str = "2027-01-01T00:00:00Z",
    clock_advance_to: Optional[str] = "2030-01-01T00:00:00Z",
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2025-06-01",
    repayment_begin_on: str = "2026-02-01",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
    adjudicator_user_id: str = "adj-test-1",
    filed_on: str = "2030-01-01",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Full PSLF-discharge-ready scenario:

    1. Borrower + Loan in REPAYMENT with an IBR plan.
    2. PSLFTracker initialized and forced to ELIGIBLE_FOR_FORGIVENESS with count=120.
    3. PSLF_FORGIVENESS DischargeApplication created and moved to UNDER_REVIEW.
    4. Clock advanced to clock_advance_to (so filed_on is current).

    Returns (borrower, loan_latest, plan, tracker, application_in_under_review).
    """
    advance_clock(clock_initial)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        repayment_begin_on=repayment_begin_on,
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    plan = attach_idr_plan(loan["id"], "IBR", 3_000_000, 4)

    tracker = setup_pslf_tracker_at_threshold(
        borrower["id"], adjudicator_user_id=adjudicator_user_id,
    )

    if clock_advance_to:
        advance_clock(clock_advance_to)

    application = get_success_data(api_client.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "PSLF_FORGIVENESS", filed_on,
        ),
        TEST_USERS["servicer_headers"],
    ))
    application = get_success_data(api_client.begin_review_discharge_application(
        application["id"],
        make_pslf_adjudicator_headers(adjudicator_user_id),
    ))
    loan_latest = get_loan(loan["id"])
    return borrower, loan_latest, plan, tracker, application


# ─── Tier 6 — Veteran-discharge-ready ───────────────


def setup_veteran_discharge_ready(
    *,
    clock_set_to: str = "2026-06-01T00:00:00Z",
    filed_on: str = "2026-06-01",
    original_principal_cents: int = 2_000_000,
    interest_rate_bps: int = 533,
    disbursement_date: str = "2025-06-01",
    discharge_count: int = 1,
) -> Tuple[dict, dict, List[dict]]:
    """Veteran borrower + Loan + N pending VETERAN_TOTAL_PERMANENT_DISABILITY
    applications, each moved into UNDER_REVIEW.

    Returns (borrower, loan_latest, [applications_under_review]).
    """
    advance_clock(clock_set_to)
    borrower = create_borrower(military_status="VETERAN")
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=original_principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date,
    )
    applications: List[dict] = []
    for i in range(discharge_count):
        app = get_success_data(api_client.create_discharge_application(
            create_discharge_application_payload(
                borrower["id"], "VETERAN_TOTAL_PERMANENT_DISABILITY",
                filed_on, va_certification_doc_id=f"VA-DOC-{i + 1:03d}",
            ),
            TEST_USERS["servicer_headers"],
        ))
        app = get_success_data(api_client.begin_review_discharge_application(
            app["id"], TEST_USERS["va_officer_headers"],
        ))
        applications.append(app)
    loan_latest = get_loan(loan["id"])
    return borrower, loan_latest, applications


# ─── Tier 7 — PSLF SoD priority-conflict scenario ────


def setup_pslf_sod_violation_scenario(
    *,
    shared_user_id: str = "svc-shared",
    clean_adjudicator_user_id: str = "adj-clean-1",
    clock_initial: str = "2026-10-15T00:00:00Z",
    clock_after_cert: str = "2026-11-15T00:00:00Z",
    clock_final: str = "2027-01-15T00:00:00Z",
    disbursement_date: str = "2026-02-01",
    repayment_begin_on: str = "2026-10-15",
    monthly_payment_cents: int = 21_537,
    filed_on: str = "2027-01-15",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Build the precise SoD-violation scenario from the difficulty design:

    - Borrower with a $20k UNSUBSIDIZED loan @ 5.33%, REPAYMENT, STANDARD_10YR plan.
    - APPROVED EmploymentCertification (GOVERNMENT_FEDERAL, 40 hrs/wk, covers payment).
    - One qualifying Payment (amount=21537 = scheduled monthly) recorded by
      X-User-ID = shared_user_id (this is the SoD-poisoning step).
    - PSLFTracker forced to ELIGIBLE_FOR_FORGIVENESS with count=120 by a CLEAN
      adjudicator (so the tracker's own actor doesn't shadow the SoD test).
    - PSLF_FORGIVENESS DischargeApplication created and moved to UNDER_REVIEW.
    - Note: the eventual approve attempt is made by the caller, using the
      SAME shared_user_id as the adjudicator — that's what triggers ERR_SOD_VIOLATION.

    Returns (borrower, loan_latest, payment, tracker, application_under_review).
    """
    h_shared = make_servicer_headers(shared_user_id)
    h_clean_adj = make_pslf_adjudicator_headers(clean_adjudicator_user_id)
    h_shared_adj = make_pslf_adjudicator_headers(shared_user_id)

    # Clock + Borrower + Loan + REPAYMENT + STANDARD_10YR plan
    advance_clock(clock_initial, headers=h_shared)
    borrower = create_borrower(headers=h_shared)
    loan = create_loan(
        borrower["id"],
        loan_type="DIRECT_UNSUBSIDIZED",
        original_principal_cents=2_000_000,
        interest_rate_bps=533,
        disbursement_date=disbursement_date,
        headers=h_shared,
    )
    fire_servicing_event(loan["id"], "GRACE_BEGIN", disbursement_date, "OTHER",
                          headers=h_shared)
    fire_servicing_event(loan["id"], "REPAYMENT_BEGIN", repayment_begin_on,
                          "GRACE_EXPIRY", headers=h_shared)
    attach_standard_10yr_plan(loan["id"], headers=h_shared)

    # APPROVED EmploymentCertification covering the about-to-be-recorded payment
    cert = get_success_data(api_client.create_employment_certification(
        create_employment_certification_payload(
            borrower["id"],
            employer_type="GOVERNMENT_FEDERAL",
            period_start_on="2026-10-01",
            period_end_on="2099-12-31",
            weekly_hours=40,
        ),
        h_shared,
    ))
    get_success_data(api_client.approve_employment_certification(
        cert["id"], h_shared,
    ))

    # Advance to first scheduled-due-date and record a qualifying payment
    advance_clock(clock_after_cert, headers=h_shared)
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(loan["id"], monthly_payment_cents,
                                "2026-11-15", "ACH"),
        h_shared,
    ))

    # PSLFTracker forced to ELIGIBLE_FOR_FORGIVENESS by a CLEAN adjudicator.
    # The tracker is created AFTER the payment, so the payment-time recount
    # was a no-op (no tracker yet). We force an explicit recount here to
    # stamp pslf_qualifying=True on the contributing payment per the normal
    # PRD §3.6 recount machinery; only then do we force-state to count=120.
    # The forced count is what makes the tracker ELIGIBLE_FOR_FORGIVENESS
    # (skipping the need for 120 actual payments per PRD §3.6 last paragraph);
    # the recount-derived flag on the one real payment is what makes the
    # PRD §2.6 SoD check find a contributing payment recorded by the shared
    # X-User-ID.
    tracker = get_success_data(api_client.create_pslf_tracker(
        create_pslf_tracker_payload(borrower["id"]), h_clean_adj,
    ))
    get_success_data(api_client.recount_pslf_tracker(
        tracker["id"], h_clean_adj,
    ))
    get_success_data(api_client.force_pslf_tracker_state(
        tracker["id"],
        force_pslf_tracker_state_payload(120, "ELIGIBLE_FOR_FORGIVENESS"),
        h_clean_adj,
    ))

    # Advance clock and file the PSLF discharge under shared user as the servicer
    advance_clock(clock_final, headers=h_shared)
    application = get_success_data(api_client.create_discharge_application(
        create_discharge_application_payload(
            borrower["id"], "PSLF_FORGIVENESS", filed_on,
        ),
        h_shared,
    ))
    application = get_success_data(api_client.begin_review_discharge_application(
        application["id"], h_shared_adj,
    ))

    loan_latest = get_loan(loan["id"], headers=h_shared)
    return borrower, loan_latest, payment, tracker, application


# ─── Tier 8 — PSLF cert-then-payments-then-cert scenario ───


def setup_payments_then_cert_for_relaxed_lookback(
    *,
    clock_initial: str = "2026-10-15T00:00:00Z",
    repayment_begin_on: str = "2026-10-15",
    disbursement_date: str = "2026-02-01",
    monthly_payment_cents: int = 21_537,
    payment_dates: Optional[List[str]] = None,
    cert_period_start: str = "2026-10-01",
    cert_period_end: str = "2099-12-31",
    adjudicator_user_id: str = "adj-test-1",
) -> Tuple[dict, dict, dict, List[dict], dict]:
    """Set up the scenario that distinguishes relaxed-lookback from strict-at-POSTED:

    1. REPAYMENT loan with ACTIVE STANDARD_10YR plan (monthly_payment_cents = 21537).
    2. PSLFTracker initialized (count=0).
    3. TWO POSTED payments at the scheduled due dates (relaxed-lookback variant
       requires payments to exist BEFORE the certification approves).
    4. ONE EmploymentCertification submitted (GOVERNMENT_FEDERAL, 40 hrs) whose
       period covers both payment dates — NOT yet approved.

    Returns (borrower, loan, tracker, payments, certification_pending).

    Caller approves the certification to trigger the relaxed-lookback recount
    and then GETs the tracker to read qualifying_payment_count.
    """
    if payment_dates is None:
        payment_dates = ["2026-11-15", "2026-12-15"]

    advance_clock(clock_initial)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=disbursement_date,
        repayment_begin_on=repayment_begin_on,
    )
    attach_standard_10yr_plan(loan["id"])

    tracker = get_success_data(api_client.create_pslf_tracker(
        create_pslf_tracker_payload(borrower["id"]),
        make_pslf_adjudicator_headers(adjudicator_user_id),
    ))

    payments: List[dict] = []
    for d in payment_dates:
        # Advance the clock to the payment's posted_on so the date is valid.
        advance_clock(f"{d}T00:00:00Z")
        pay = get_success_data(api_client.create_payment(
            create_payment_payload(loan["id"], monthly_payment_cents, d, "ACH"),
            TEST_USERS["servicer_headers"],
        ))
        payments.append(pay)

    # Advance clock to the cert submission date and submit the certification
    advance_clock("2027-01-15T00:00:00Z")
    cert = get_success_data(api_client.create_employment_certification(
        create_employment_certification_payload(
            borrower["id"],
            employer_type="GOVERNMENT_FEDERAL",
            period_start_on=cert_period_start,
            period_end_on=cert_period_end,
            weekly_hours=40,
        ),
        TEST_USERS["servicer_headers"],
    ))
    loan_latest = get_loan(loan["id"])
    return borrower, loan_latest, tracker, payments, cert


# ─── Tier 9 — Bulk qualifying payments for invariant test ────


def setup_borrower_with_n_qualifying_payments(
    *,
    n_payments: int = 5,
    clock_initial: str = "2026-06-01T00:00:00Z",
    disbursement_date: str = "2025-06-01",
    grace_begin_on: str = "2025-06-01",
    repayment_begin_on: str = "2026-06-01",
    adjudicator_user_id: str = "adj-test-1",
    monthly_payment_cents: int = 21_537,
) -> Tuple[dict, dict, dict, List[dict]]:
    """Build a borrower with N POSTED qualifying payments and an APPROVED
    EmploymentCertification, ready for tracker recount.

    Returns (borrower, loan, tracker, payments).
    The first payment posts on the month after repayment_begin_on (the first
    scheduled due_date) and subsequent payments one month apart, each on
    the scheduled due date so all qualify.

    Defaults are aligned so that repayment_begin_on == clock_initial date,
    so the loop's subsequent advance_clock calls always step forward (which
    the implementation requires per PRD §3.5: "to_iso8601 must be strictly
    greater than current clock"). Each payment then posts on the cycle's
    scheduled due date (cycle k due = plan_activation + k months), which
    keeps payments inside the PRD §3.6 on-time window [due, due + 15d]
    and (after a clock-driven DELINQUENT transition that fires at each
    due date on advance) is large enough (>= monthly_payment_cents) to
    cure the new arrears back to REPAYMENT per PRD §3.4.
    """
    advance_clock(clock_initial)
    borrower, loan = create_loan_in_repayment(
        disbursement_date=disbursement_date,
        grace_begin_on=grace_begin_on,
        repayment_begin_on=repayment_begin_on,
    )
    attach_standard_10yr_plan(loan["id"])

    # Tracker (count starts at 0)
    h_adj = make_pslf_adjudicator_headers(adjudicator_user_id)
    tracker = get_success_data(api_client.create_pslf_tracker(
        create_pslf_tracker_payload(borrower["id"]), h_adj,
    ))

    # APPROVED EmploymentCertification covering all payments
    cert = get_success_data(api_client.create_employment_certification(
        create_employment_certification_payload(
            borrower["id"],
            employer_type="GOVERNMENT_FEDERAL",
            period_start_on="2026-01-01",
            period_end_on="2099-12-31",
            weekly_hours=40,
        ),
        TEST_USERS["servicer_headers"],
    ))
    get_success_data(api_client.approve_employment_certification(
        cert["id"], TEST_USERS["servicer_headers"],
    ))

    payments: List[dict] = []
    # Start on the month following repayment_begin_on; assume monthly cadence
    # on the same day-of-month as repayment_begin_on.
    year, month, day = [int(p) for p in repayment_begin_on.split("-")]
    for i in range(1, n_payments + 1):
        # Compute the next month (handles wrap-around).
        m = month + i
        y = year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        date_str = f"{y:04d}-{m:02d}-{day:02d}"
        advance_clock(f"{date_str}T00:00:00Z")
        pay = get_success_data(api_client.create_payment(
            create_payment_payload(loan["id"], monthly_payment_cents,
                                    date_str, "ACH"),
            TEST_USERS["servicer_headers"],
        ))
        payments.append(pay)

    # Force a recount so qualifying_payment_count reflects the n_payments.
    get_success_data(api_client.recount_pslf_tracker(tracker["id"], h_adj))
    tracker_after = get_success_data(api_client.get_pslf_tracker(
        tracker["id"], h_adj,
    ))
    return borrower, get_loan(loan["id"]), tracker_after, payments
