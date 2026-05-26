"""
Composite setup helpers for multi-step test prerequisites.

Each fixture builds preconditions from an empty database — the harness restarts
the API server (via start.sh) before every test, so nothing carries over from
a previous test. All setup helpers use get_success_data() (lenient validator)
so setup-step failures surface as clear 'setup failed' messages.

Identity threading: any Borrower-role call against an entity_backed:Borrower
operation MUST use make_borrower_headers(borrower["id"]) — never the shared
constant — because PRD §2.1 compares X-User-ID to the resource's borrower_id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_borrower_payload,
    create_loan_payload,
    create_repayment_plan_payload,
    create_income_certification_payload,
    create_qualifying_employment_payload,
    create_payment_payload,
    create_discharge_application_payload,
)
from .test_users import TEST_USERS, make_borrower_headers


LS = TEST_USERS["loan_servicer_headers"]
CA = TEST_USERS["collections_agent_headers"]


# ─── Tier 0: Clock primitive ──────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server clock. Used by every fixture to pin time deterministically."""
    return get_success_data(api_client.set_current_utc(to_iso8601, LS))


# ─── Tier 1: Borrower + Loan creation primitives ──────────

def create_borrower(full_name="Test Borrower", ssn_last4="0000", is_veteran=False):
    """Create a Borrower entity. Returns the full Borrower dict."""
    return get_success_data(api_client.create_borrower(
        create_borrower_payload(
            full_name=full_name, ssn_last4=ssn_last4, is_veteran=is_veteran),
        LS,
    ))


def create_loan(borrower_id, loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
                interest_rate_bps=500, disbursement_date="2026-06-01T00:00:00Z"):
    """Create a Loan in ORIGINATED. Returns the full Loan dict."""
    return get_success_data(api_client.create_loan(
        create_loan_payload(
            borrower_id,
            loan_type=loan_type,
            principal_cents=principal_cents,
            interest_rate_bps=interest_rate_bps,
            disbursement_date=disbursement_date,
        ),
        LS,
    ))


# ─── Tier 2: State Progression ────────────────────────────

def walk_loan_to_repayment(loan_id):
    """Walk a Loan ORIGINATED -> IN_SCHOOL -> GRACE -> REPAYMENT.
    Returns the REPAYMENT-state Loan dict."""
    get_success_data(api_client.enter_school(loan_id, LS))
    get_success_data(api_client.graduate(loan_id, LS))
    return get_success_data(api_client.start_repayment(loan_id, LS))


def setup_borrower_and_loan_in_repayment(
    clock_iso="2026-06-01T00:00:00Z",
    full_name="Repay B",
    ssn_last4="0100",
    is_veteran=False,
    loan_type="DIRECT_UNSUB",
    principal_cents=1_000_000,
    interest_rate_bps=500,
    disbursement_date=None,
):
    """
    Standard preamble: set clock, create borrower, create loan, walk loan
    ORIGINATED -> IN_SCHOOL -> GRACE -> REPAYMENT.

    Returns (borrower, loan_in_repayment).
    """
    set_clock(clock_iso)
    borrower = create_borrower(
        full_name=full_name, ssn_last4=ssn_last4, is_veteran=is_veteran)
    loan = create_loan(
        borrower["id"],
        loan_type=loan_type,
        principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date or clock_iso,
    )
    loan = walk_loan_to_repayment(loan["id"])
    return borrower, loan


def setup_borrower_and_loan_in_school(
    clock_iso="2026-06-01T00:00:00Z",
    full_name="IS B",
    ssn_last4="0101",
    loan_type="DIRECT_UNSUB",
    principal_cents=1_000_000,
    interest_rate_bps=500,
):
    """Set clock, create borrower, create loan, transition to IN_SCHOOL only.
    Returns (borrower, loan_in_school)."""
    set_clock(clock_iso)
    borrower = create_borrower(full_name=full_name, ssn_last4=ssn_last4)
    loan = create_loan(
        borrower["id"],
        loan_type=loan_type,
        principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=clock_iso,
    )
    loan = get_success_data(api_client.enter_school(loan["id"], LS))
    return borrower, loan


# ─── Tier 3: Income / Plan composite helpers ──────────────

def create_and_certify_income(borrower_id, agi_cents=6_000_000, family_size=2,
                              state_code="CA",
                              effective_date="2026-05-01T00:00:00Z"):
    """Borrower files an IncomeCertification, LoanServicer certifies it.
    Returns the CERTIFIED IncomeCertification dict."""
    ic = get_success_data(api_client.create_income_certification(
        create_income_certification_payload(
            borrower_id,
            agi_cents=agi_cents,
            family_size=family_size,
            state_code=state_code,
            effective_date=effective_date,
        ),
        make_borrower_headers(borrower_id),
    ))
    return get_success_data(
        api_client.certify_income_certification(ic["id"], LS)
    )


def create_repayment_plan(loan_id, expected_loan_version, plan_type="STANDARD",
                          effective_date="2026-06-01T00:00:00Z"):
    """Create a RepaymentPlan in PENDING. Returns the PENDING plan dict."""
    return get_success_data(api_client.create_repayment_plan(
        create_repayment_plan_payload(
            loan_id, expected_loan_version,
            plan_type=plan_type,
            effective_date=effective_date,
        ),
        LS,
    ))


def create_and_activate_plan(loan_id, expected_loan_version,
                             plan_type="STANDARD",
                             effective_date="2026-06-01T00:00:00Z"):
    """Create a PENDING plan, then activate it. Returns the ACTIVE plan dict."""
    plan = create_repayment_plan(
        loan_id, expected_loan_version,
        plan_type=plan_type, effective_date=effective_date)
    return get_success_data(api_client.activate_repayment_plan(plan["id"], LS))


# ─── Tier 4: Employment / PSLF helpers ────────────────────

def create_and_certify_qualifying_employment(
    borrower_id,
    employer_name="Public Library",
    employer_type="GOVERNMENT",
    period_start="2025-01-01T00:00:00Z",
    period_end="2027-12-31T00:00:00Z",
):
    """Borrower files QE, LoanServicer certifies. Returns CERTIFIED QE dict."""
    qe = get_success_data(api_client.create_qualifying_employment(
        create_qualifying_employment_payload(
            borrower_id,
            employer_name=employer_name,
            employer_type=employer_type,
            period_start=period_start,
            period_end=period_end,
        ),
        make_borrower_headers(borrower_id),
    ))
    return get_success_data(
        api_client.certify_qualifying_employment(qe["id"], LS)
    )


# ─── Tier 5: Payment lifecycle helpers ────────────────────

def post_payment(loan_id, borrower_id, amount_cents=10_000,
                 payment_date="2026-06-01T00:00:00Z"):
    """Borrower posts a Payment (PENDING). Returns the PENDING Payment dict."""
    return get_success_data(api_client.create_payment(
        create_payment_payload(
            loan_id, amount_cents=amount_cents, payment_date=payment_date),
        make_borrower_headers(borrower_id),
    ))


def post_and_apply_payment(loan_id, borrower_id, amount_cents=10_000,
                           payment_date="2026-06-01T00:00:00Z"):
    """Post a Payment then apply it. Returns the APPLIED Payment dict."""
    pay = post_payment(loan_id, borrower_id,
                       amount_cents=amount_cents,
                       payment_date=payment_date)
    return get_success_data(api_client.apply_payment(pay["id"], LS))


# ─── Tier 6: Discharge application helpers ────────────────

def file_discharge_application(loan_id, borrower_id,
                               discharge_type="VETERAN_TOTAL_DISABILITY"):
    """Borrower files a DischargeApplication (SUBMITTED).
    Returns SUBMITTED application dict."""
    return get_success_data(api_client.create_discharge_application(
        create_discharge_application_payload(
            loan_id, discharge_type=discharge_type),
        make_borrower_headers(borrower_id),
    ))


def file_and_begin_review_discharge(loan_id, borrower_id,
                                    discharge_type="VETERAN_TOTAL_DISABILITY"):
    """File + begin-review. Returns UNDER_REVIEW application dict."""
    app = file_discharge_application(
        loan_id, borrower_id, discharge_type=discharge_type)
    return get_success_data(api_client.begin_review_discharge(app["id"], LS))


# ─── Tier 7: Composite scenarios used by §1.8 + §1.9 ──────

def setup_idr_certified_borrower_in_repayment(
    clock_iso="2026-06-01T00:00:00Z",
    full_name="IDR B", ssn_last4="0200", is_veteran=False,
    loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
    interest_rate_bps=533, disbursement_date="2023-06-01T00:00:00Z",
    agi_cents=6_000_000, family_size=2, state_code="CA",
    income_effective_date="2026-05-01T00:00:00Z",
):
    """
    Borrower with CERTIFIED IncomeCertification + Loan in REPAYMENT, ready
    for an IDR plan to be created against them.

    Returns (borrower, loan_in_repayment, certified_income).
    """
    set_clock(clock_iso)
    borrower = create_borrower(
        full_name=full_name, ssn_last4=ssn_last4, is_veteran=is_veteran)
    loan = create_loan(
        borrower["id"],
        loan_type=loan_type, principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date,
    )
    get_success_data(api_client.enter_school(loan["id"], LS))
    get_success_data(api_client.graduate(loan["id"], LS))
    loan = get_success_data(api_client.start_repayment(loan["id"], LS))
    ic = create_and_certify_income(
        borrower["id"],
        agi_cents=agi_cents, family_size=family_size,
        state_code=state_code, effective_date=income_effective_date,
    )
    return borrower, loan, ic


def setup_loan_with_active_standard_plan(
    clock_iso="2026-06-01T00:00:00Z",
    full_name="StdPlan B", ssn_last4="0210", is_veteran=False,
    loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
    interest_rate_bps=533, disbursement_date="2025-01-01T00:00:00Z",
    plan_effective_date="2026-01-01T00:00:00Z",
):
    """
    Loan in REPAYMENT with an ACTIVE STANDARD plan.

    Returns (borrower, loan_in_repayment, active_plan).
    """
    set_clock(clock_iso)
    borrower = create_borrower(
        full_name=full_name, ssn_last4=ssn_last4, is_veteran=is_veteran)
    loan = create_loan(
        borrower["id"],
        loan_type=loan_type, principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=disbursement_date,
    )
    get_success_data(api_client.enter_school(loan["id"], LS))
    get_success_data(api_client.graduate(loan["id"], LS))
    loan = get_success_data(api_client.start_repayment(loan["id"], LS))
    plan = create_and_activate_plan(
        loan["id"], loan["version"],
        plan_type="STANDARD", effective_date=plan_effective_date,
    )
    return borrower, loan, plan


def setup_discharge_application_under_review(
    clock_iso="2026-06-01T00:00:00Z",
    is_veteran=True,
    discharge_type="VETERAN_TOTAL_DISABILITY",
    full_name="DA B", ssn_last4="0220",
    loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
    interest_rate_bps=500,
):
    """
    Veteran borrower + Loan in REPAYMENT + DischargeApplication in UNDER_REVIEW.

    Returns (borrower, loan, application_under_review).
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso=clock_iso, full_name=full_name, ssn_last4=ssn_last4,
        is_veteran=is_veteran,
        loan_type=loan_type, principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps,
    )
    app = file_and_begin_review_discharge(
        loan["id"], borrower["id"], discharge_type=discharge_type)
    return borrower, loan, app


def setup_loan_in_default(
    clock_start_iso="2025-06-01T00:00:00Z",
    clock_after_iso="2026-03-10T00:00:00Z",
    full_name="Def B", ssn_last4="0230",
    loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
    interest_rate_bps=500,
):
    """
    Loan in DEFAULT (no post-default payments). Reaches default by:
    1. Set clock to clock_start_iso, create borrower + loan, walk to REPAYMENT.
    2. Advance clock to clock_after_iso (>= 270 days after start-repayment).
    3. CollectionsAgent declares default.

    Returns (borrower, loan_in_default).
    """
    set_clock(clock_start_iso)
    borrower = create_borrower(full_name=full_name, ssn_last4=ssn_last4)
    loan = create_loan(
        borrower["id"],
        loan_type=loan_type, principal_cents=principal_cents,
        interest_rate_bps=interest_rate_bps,
        disbursement_date=clock_start_iso,
    )
    walk_loan_to_repayment(loan["id"])
    set_clock(clock_after_iso)
    loan_after = get_success_data(api_client.declare_default(loan["id"], CA))
    return borrower, loan_after
