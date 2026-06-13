"""Composite setup helpers for the Coding Bootcamp ISA API.

Each test starts against an empty database (the runner restarts the server
before every test), so every helper builds its preconditions from scratch using
only PRD-declared endpoints. Helpers use get_success_data() (lenient) internally
so setup failures surface as clear "Setup failed" errors.

The recurring preamble across the design indices is:
  set clock -> create cohort -> open -> create+admit applicant -> enroll
  -> advance clock -> start cohort -> record attendance -> graduate enrollment
  -> fetch the (now ACTIVE) ISA contract.
These helpers expose that chain at several useful stopping points.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_cohort_payload,
    create_applicant_payload,
    create_enrollment_payload,
    create_attendance_record_payload,
    create_income_report_payload,
)

ADMIN = TEST_USERS["admissions_officer_headers"]
SERVICING = TEST_USERS["servicing_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

# Default clock anchors used by the recurring preamble.
CLOCK_PRE_START = "2026-01-01T00:00:00Z"
CLOCK_AT_START = "2026-02-01T00:00:00Z"
CLOCK_AT_END = "2026-05-01T00:00:00Z"


def set_clock(to_iso8601, headers=ADMIN):
    get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Tier 1: State progression — cohorts and the admission funnel
# ---------------------------------------------------------------------------
def create_cohort(headers=ADMIN, clock=CLOCK_PRE_START, **overrides):
    """Create a PLANNING cohort with the clock anchored before its start_date."""
    if clock is not None:
        set_clock(clock, headers)
    return get_success_data(api_client.create_cohort(create_cohort_payload(**overrides), headers))


def create_open_cohort(headers=ADMIN, clock=CLOCK_PRE_START, **overrides):
    """Create a cohort and open it (PLANNING -> OPEN)."""
    cohort = create_cohort(headers=headers, clock=clock, **overrides)
    get_success_data(api_client.open_cohort(cohort["id"], headers))
    return get_success_data(api_client.get_cohort(cohort["id"], headers))


def admit_applicant(cohort_id, email="applicant@example.com", headers=ADMIN, **overrides):
    """Create an applicant in an OPEN cohort and admit it (APPLIED -> ADMITTED)."""
    applicant = get_success_data(
        api_client.create_applicant(
            create_applicant_payload(cohort_id, email=email, **overrides), headers
        )
    )
    get_success_data(api_client.admit_applicant(applicant["id"], headers))
    return get_success_data(api_client.get_applicant(applicant["id"], headers))


def enroll_admitted(applicant_id, financing_choice="ISA", headers=ADMIN, **overrides):
    """Enroll an ADMITTED applicant. Returns the ENROLLED enrollment."""
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(applicant_id, financing_choice, **overrides), headers
        )
    )


def setup_enrolled(financing_choice="ISA", email="enrolled@example.com", headers=ADMIN,
                   cohort_overrides=None, enroll_overrides=None):
    """OPEN cohort -> admitted applicant -> ENROLLED enrollment (cohort not yet started).

    Returns (cohort, applicant, enrollment).
    """
    cohort = create_open_cohort(headers=headers, **(cohort_overrides or {}))
    applicant = admit_applicant(cohort["id"], email=email, headers=headers)
    enrollment = enroll_admitted(
        applicant["id"], financing_choice, headers=headers, **(enroll_overrides or {})
    )
    return cohort, applicant, enrollment


def setup_active_enrollment(financing_choice="ISA", email="active@example.com", headers=ADMIN,
                            progress_pct=100, present=True, cohort_overrides=None,
                            enroll_overrides=None, start_clock=CLOCK_AT_START):
    """Walk to a RUNNING cohort with one ACTIVE enrollment and one attendance record.

    Returns (cohort, applicant, enrollment). progress_pct/present control the
    single recorded session, so callers can target dismissal / graduation guards.
    """
    cohort, applicant, enrollment = setup_enrolled(
        financing_choice, email, headers, cohort_overrides, enroll_overrides
    )
    set_clock(start_clock, headers)
    get_success_data(api_client.start_cohort(cohort["id"], headers))
    get_success_data(
        api_client.create_attendance_record(
            create_attendance_record_payload(
                enrollment["id"], present=present, cumulative_progress_pct=progress_pct
            ),
            headers,
        )
    )
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], headers))
    return cohort, applicant, enrollment


def get_isa_for_enrollment(enrollment_id, headers=SERVICING):
    """Return the ISAContract linked to an enrollment via FK filter."""
    data, _ = _paginated(api_client.list_isa_contracts(headers, params={"enrollment_id": enrollment_id}))
    assert data, f"no ISA contract found for enrollment {enrollment_id}"
    return data[0]


def _paginated(response):
    body = get_success_data(response)
    # get_success_data returns the data payload; for list endpoints that is the list.
    # The framework's validate_paginated is used by tests; fixtures only need the rows.
    if isinstance(body, list):
        return body, {}
    return body.get("data", body), {}


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle shortcut — graduated ISA enrollment with an ACTIVE contract
# ---------------------------------------------------------------------------
def setup_graduated_isa(email="grad@example.com", headers=ADMIN, cohort_overrides=None,
                        enroll_overrides=None):
    """Full chain to a GRADUATED ISA enrollment whose ISAContract is ACTIVE.

    Returns (cohort, applicant, enrollment, isa_contract).
    """
    cohort, applicant, enrollment = setup_active_enrollment(
        "ISA", email, headers, progress_pct=100, present=True,
        cohort_overrides=cohort_overrides, enroll_overrides=enroll_overrides,
    )
    get_success_data(api_client.graduate_enrollment(enrollment["id"], headers))
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], headers))
    isa = get_isa_for_enrollment(enrollment["id"], SERVICING)
    return cohort, applicant, enrollment, isa


def setup_graduated_upfront(email="gradup@example.com", headers=ADMIN, cohort_overrides=None):
    """Full chain to a GRADUATED UPFRONT enrollment (no ISA contract).

    Returns (cohort, applicant, enrollment).
    """
    cohort, applicant, enrollment = setup_active_enrollment(
        "UPFRONT", email, headers, progress_pct=100, present=True,
        cohort_overrides=cohort_overrides,
    )
    get_success_data(api_client.graduate_enrollment(enrollment["id"], headers))
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], headers))
    return cohort, applicant, enrollment


# ---------------------------------------------------------------------------
# Tier 4: Ledger / threshold targeting — drive an ISA to a known amount_paid_cents
# ---------------------------------------------------------------------------
def file_income_report(isa_id, period_start, period_end, gross_income_cents,
                       employment_status="EMPLOYED", headers=SERVICING):
    """File one income report; return the report dict (carries payment_id when owed)."""
    return get_success_data(
        api_client.create_income_report(
            create_income_report_payload(
                isa_id, period_start, period_end, gross_income_cents, employment_status
            ),
            headers,
        )
    )


def file_and_settle(isa_id, period_start, period_end, gross_income_cents, headers=SERVICING):
    """File an income report and settle the payment it spawns. Returns (report, payment)."""
    report = file_income_report(isa_id, period_start, period_end, gross_income_cents, "EMPLOYED", headers)
    pay_id = report.get("payment_id")
    assert pay_id, f"expected a payment to be created for gross {gross_income_cents}"
    payment = get_success_data(api_client.settle_payment(pay_id, headers))
    return report, payment


def setup_isa_with_settled_payment(gross_income_cents=600_000, email="ledger@example.com"):
    """ACTIVE ISA with a single SETTLED payment from one income report.

    Returns (isa_contract, report, payment). Default gross 600000 over the
    standard 0.17 share yields a 102000 obligation/settlement.
    """
    _, _, enrollment, isa = setup_graduated_isa(email=email)
    report, payment = file_and_settle(
        isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", gross_income_cents
    )
    isa = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    return isa, report, payment


def setup_isa_with_pending_payment(gross_income_cents=600_000, email="pending@example.com"):
    """ACTIVE ISA with a single PENDING (unsettled) payment.

    Returns (isa_contract, report, payment_id).
    """
    _, _, enrollment, isa = setup_graduated_isa(email=email)
    report = file_income_report(
        isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", gross_income_cents
    )
    pay_id = report.get("payment_id")
    assert pay_id, "expected a PENDING payment to be created"
    return isa, report, pay_id


def setup_deferred_isa(email="deferred@example.com"):
    """ACTIVE ISA driven to DEFERRED via an approved UNEMPLOYMENT deferment.

    Files a PENDING payment first (from an EMPLOYED report), then files an
    UNEMPLOYED report and approves a deferment so the contract is DEFERRED.
    Returns (isa_contract, pending_payment_id, deferment_id).
    """
    _, _, enrollment, isa = setup_graduated_isa(email=email)
    # PENDING payment from an over-threshold EMPLOYED report.
    rep = file_income_report(
        isa["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 600_000, "EMPLOYED"
    )
    pay_id = rep.get("payment_id")
    # Latest report is UNEMPLOYED, making an UNEMPLOYMENT deferment eligible.
    file_income_report(
        isa["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 0, "UNEMPLOYED"
    )
    dr = get_success_data(
        api_client.create_deferment_request(
            {
                "isa_contract_id": isa["id"],
                "reason": "UNEMPLOYMENT",
                "period_start": "2026-08-01T00:00:00Z",
                "period_end": "2026-10-31T00:00:00Z",
            },
            SERVICING,
        )
    )
    get_success_data(api_client.approve_deferment_request(dr["id"], SERVICING))
    isa = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    return isa, pay_id, dr["id"]


# ---------------------------------------------------------------------------
# Tier 2/5: Withdrawal + refund workflow
# ---------------------------------------------------------------------------
def setup_pending_refund(financing_choice="UPFRONT", refund_reason="WITHDRAWAL",
                         progress_pct=None, present=True, email="refund@example.com",
                         cohort_overrides=None):
    """Enroll, optionally record progress while ACTIVE, then withdraw to open a
    PENDING RefundRequest. Returns (cohort, enrollment, refund_request).

    If progress_pct is None the enrollment is withdrawn while still ENROLLED
    (cohort never started). Otherwise the cohort is started, one attendance
    record is written, and the ACTIVE enrollment is withdrawn.
    """
    if progress_pct is None:
        cohort, applicant, enrollment = setup_enrolled(
            financing_choice, email, ADMIN, cohort_overrides
        )
    else:
        cohort, applicant, enrollment = setup_active_enrollment(
            financing_choice, email, ADMIN, progress_pct=progress_pct, present=present,
            cohort_overrides=cohort_overrides,
        )
    get_success_data(
        api_client.withdraw_enrollment(enrollment["id"], ADMIN, {"refund_reason": refund_reason})
    )
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], ADMIN))
    refunds, _ = _paginated(
        api_client.list_refund_requests(COMPLIANCE, params={"enrollment_id": enrollment["id"]})
    )
    assert refunds, f"no refund request opened for enrollment {enrollment['id']}"
    return cohort, enrollment, refunds[0]


# ---------------------------------------------------------------------------
# CIRR reporting cohort with mixed terminal states
# ---------------------------------------------------------------------------
def setup_cirr_cohort():
    """Build a GRADUATED cohort with 4 graduates (3 CIRR-eligible placements),
    one DISMISSED and one WITHDRAWN enrollment, then graduate the cohort.

    Returns the cohort dict (in GRADUATED status). Counts:
      graduates_count=4, enrolled_count=6, placed_count=3.
    """
    cohort = create_open_cohort(capacity=10, name="CIRR Cohort")
    coh_id = cohort["id"]
    enr_ids = []
    for i in range(6):
        app = admit_applicant(coh_id, email=f"cirr{i}@example.com")
        e = enroll_admitted(app["id"], "UPFRONT")
        enr_ids.append(e["id"])

    set_clock(CLOCK_AT_START)
    get_success_data(api_client.start_cohort(coh_id, ADMIN))

    # First 4 reach progress 100; index 4 is dismissed, index 5 withdrawn.
    for i in range(4):
        get_success_data(
            api_client.create_attendance_record(
                create_attendance_record_payload(enr_ids[i], present=True, cumulative_progress_pct=100),
                ADMIN,
            )
        )
    # Index 4: low attendance -> dismissible.
    get_success_data(
        api_client.create_attendance_record(
            create_attendance_record_payload(enr_ids[4], present=False, cumulative_progress_pct=20),
            ADMIN,
        )
    )
    get_success_data(api_client.dismiss_enrollment(enr_ids[4], ADMIN))
    # Index 5: withdrawn.
    get_success_data(
        api_client.withdraw_enrollment(enr_ids[5], ADMIN, {"refund_reason": "WITHDRAWAL"})
    )
    # Graduate the first four directly.
    for i in range(4):
        get_success_data(api_client.graduate_enrollment(enr_ids[i], ADMIN))

    # Three CIRR-eligible placements (countable categories within window); one STILL_SEEKING.
    get_success_data(api_client.create_placement_outcome(
        {"enrollment_id": enr_ids[0], "category": "EMPLOYED_IN_FIELD",
         "reported_at": "2026-06-01T00:00:00Z", "annual_salary_cents": 9_000_000, "placement_days": 30},
        COMPLIANCE))
    get_success_data(api_client.create_placement_outcome(
        {"enrollment_id": enr_ids[1], "category": "EMPLOYED_OUT_OF_FIELD",
         "reported_at": "2026-06-01T00:00:00Z", "annual_salary_cents": 7_000_000, "placement_days": 90},
        COMPLIANCE))
    get_success_data(api_client.create_placement_outcome(
        {"enrollment_id": enr_ids[2], "category": "SELF_EMPLOYED",
         "reported_at": "2026-06-01T00:00:00Z", "placement_days": 120},
        COMPLIANCE))
    get_success_data(api_client.create_placement_outcome(
        {"enrollment_id": enr_ids[3], "category": "STILL_SEEKING",
         "reported_at": "2026-06-01T00:00:00Z"},
        COMPLIANCE))

    set_clock(CLOCK_AT_END)
    get_success_data(api_client.graduate_cohort(coh_id, ADMIN))
    return get_success_data(api_client.get_cohort(coh_id, ADMIN))
