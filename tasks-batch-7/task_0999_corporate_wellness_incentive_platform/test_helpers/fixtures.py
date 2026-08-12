"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_activity_event_payload,
    create_adjustment_payload,
    create_challenge_payload,
    create_employee_payload,
    create_employer_payload,
    create_enrollment_payload,
    create_hra_payload,
    create_invoice_payload,
    create_participation_payload,
    create_program_payload,
    create_referral_payload,
    create_report_payload,
    create_screening_payload,
    create_screening_result_payload,
    create_session_payload,
    compute_awards_payload,
)
from .test_users import (
    TEST_USERS,
    make_coach_headers,
    make_employee_headers,
    make_vendor_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["benefits_admin_headers"]

SESSION_DATES = ["2026-04-02", "2026-04-09", "2026-04-16", "2026-04-23"]


# ─── Tier 1: State Progression ───────────────────────────────────────────────

def create_employer(**overrides):
    """Create an employer tenant. Returns the employer."""
    return get_success_data(
        api_client.create_employer(create_employer_payload(**overrides), ADMIN)
    )


def create_program(employer_id, **overrides):
    """Create a program (born DRAFT). Returns the program."""
    return get_success_data(
        api_client.create_program(create_program_payload(employer_id, **overrides), BA)
    )


def activate_program(program_id):
    """DRAFT -> ACTIVE. Returns the activated program."""
    return get_success_data(api_client.activate_program(program_id, BA))


def create_active_program(employer_id, **overrides):
    """Create + activate a program. Returns the ACTIVE program."""
    program = create_program(employer_id, **overrides)
    return activate_program(program["id"])


def close_program(program_id):
    """ACTIVE -> CLOSED. Returns the closed program."""
    return get_success_data(api_client.close_program(program_id, BA))


def set_clock(to_iso8601):
    """Advance the logical clock; applies the time sweeps of PRD §2.5."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


# ─── Tier 2: Entity Hierarchy ────────────────────────────────────────────────

def create_employee(employer_id, n=1, **overrides):
    """Create an employee of the employer. Returns the employee."""
    return get_success_data(
        api_client.create_employee(create_employee_payload(employer_id, n=n, **overrides), BA)
    )


def create_enrollment(program_id, employee_id, **overrides):
    """Enroll an employee (born INVITED/PENDING). Returns the enrollment."""
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(program_id, employee_id, **overrides), BA
        )
    )


def accept_enrollment(enrollment_id, employee_id):
    """Employee self-accept: INVITED -> ACTIVE. Returns the ACTIVE enrollment."""
    return get_success_data(
        api_client.accept_enrollment(enrollment_id, make_employee_headers(employee_id))
    )


def setup_employer_with_program(employer_overrides=None, program_overrides=None,
                                activate=True):
    """Employer + program (ACTIVE by default). Returns (employer, program)."""
    employer = create_employer(**(employer_overrides or {}))
    if activate:
        program = create_active_program(employer["id"], **(program_overrides or {}))
    else:
        program = create_program(employer["id"], **(program_overrides or {}))
    return employer, program


def setup_active_enrollment(employee_n=1, ra_eligible=None, tobacco_attested=None,
                            department="ENG", employer_overrides=None,
                            program_overrides=None):
    """Employer + ACTIVE program + employee + ACTIVE enrollment.

    Returns dict(employer, program, employee, enrollment).
    """
    employer, program = setup_employer_with_program(employer_overrides, program_overrides)
    employee_overrides = {"department": department}
    if tobacco_attested is not None:
        employee_overrides["tobacco_attested"] = tobacco_attested
    employee = create_employee(employer["id"], n=employee_n, **employee_overrides)
    enrollment_overrides = {}
    if ra_eligible is not None:
        enrollment_overrides["ra_eligible"] = ra_eligible
    enrollment = create_enrollment(program["id"], employee["id"], **enrollment_overrides)
    enrollment = accept_enrollment(enrollment["id"], employee["id"])
    return {
        "employer": employer,
        "program": program,
        "employee": employee,
        "enrollment": enrollment,
    }


def setup_cohort(size, department="ENG", accept=True, employer_overrides=None,
                 program_overrides=None, program=None, employer=None):
    """Build `size` employees each with an enrollment in the program.

    Returns dict(employer, program, employees, enrollments).
    """
    if program is None or employer is None:
        employer, program = setup_employer_with_program(employer_overrides, program_overrides)
    employees, enrollments = [], []
    for i in range(size):
        employee = create_employee(employer["id"], n=i + 1, department=department)
        enrollment = create_enrollment(program["id"], employee["id"])
        if accept:
            enrollment = accept_enrollment(enrollment["id"], employee["id"])
        employees.append(employee)
        enrollments.append(enrollment)
    return {
        "employer": employer,
        "program": program,
        "employees": employees,
        "enrollments": enrollments,
    }


# ─── Tier 3: Full Lifecycle Shortcuts ────────────────────────────────────────

def submit_hra(enrollment_id, employee_id, answers=None):
    """Submit and score an HRA as the member. Returns the HealthAssessment."""
    return get_success_data(
        api_client.create_hra(
            create_hra_payload(enrollment_id, answers), make_employee_headers(employee_id)
        )
    )


def setup_verified_enrollment(answers=None, **kwargs):
    """ACTIVE enrollment with a scored HRA (verification VERIFIED).

    Re-reads the enrollment after HRA submission so the returned context
    reflects the post-HRA verification axis (PRD §3.4: "Creating a member's
    first HealthAssessment moves `PENDING → VERIFIED` automatically").
    """
    ctx = setup_active_enrollment(**kwargs)
    ctx["hra"] = submit_hra(
        ctx["enrollment"]["id"], ctx["employee"]["id"], answers=answers
    )
    ctx["enrollment"] = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"], BA)
    )
    return ctx


def create_screening(enrollment_id, employee_id, **overrides):
    """Schedule a biometric screening as the member. Returns the screening."""
    return get_success_data(
        api_client.create_biometric_screening(
            create_screening_payload(enrollment_id, **overrides),
            make_employee_headers(employee_id),
        )
    )


def result_screening(screening_id, **result_overrides):
    """Enter results: SCHEDULED -> RESULTED. Returns the resulted screening."""
    return get_success_data(
        api_client.result_biometric_screening(
            screening_id, create_screening_result_payload(**result_overrides), BA
        )
    )


def create_challenge(program_id, publish=False, **overrides):
    """Create a challenge (DRAFT); optionally publish it. Returns the challenge."""
    challenge = get_success_data(
        api_client.create_challenge(create_challenge_payload(program_id, **overrides), BA)
    )
    if publish:
        challenge = get_success_data(api_client.publish_challenge(challenge["id"], BA))
    return challenge


def join_challenge(challenge_id, enrollment_id, employee_id):
    """Join a challenge as the member. Returns the participation."""
    return get_success_data(
        api_client.create_challenge_participation(
            create_participation_payload(challenge_id, enrollment_id),
            make_employee_headers(employee_id),
        )
    )


def post_activity(enrollment_id, employee_id, external_event_id, **overrides):
    """Ingest one device-sync activity event as the member. Returns the event."""
    return get_success_data(
        api_client.create_activity_event(
            create_activity_event_payload(enrollment_id, external_event_id, **overrides),
            make_employee_headers(employee_id),
        )
    )


def post_adjustment(enrollment_id, points_delta, reason, expected_enrollment_version):
    """Post a manual signed points adjustment. Returns the ledger entry."""
    return get_success_data(
        api_client.create_enrollment_adjustment(
            enrollment_id,
            create_adjustment_payload(points_delta, reason, expected_enrollment_version),
            BA,
        )
    )


def add_settled_points(enrollment_id, points, reason="manual credit"):
    """Post a POSTED adjustment of `points` against the enrollment.

    Re-reads the enrollment for the current OCC version. Returns the entry.
    """
    current = get_success_data(api_client.get_enrollment(enrollment_id, BA))
    return post_adjustment(enrollment_id, points, reason, current["version"])


def create_referral(enrollment_id, reason="HIGH_RISK"):
    """Create a MANUAL coaching referral. Returns the referral (REFERRED)."""
    return get_success_data(
        api_client.create_coaching_referral(create_referral_payload(enrollment_id, reason), BA)
    )


def engage_referral(referral_id, coach_id="coach-1"):
    """REFERRED -> ENGAGED; the engaging coach becomes assigned_coach_id."""
    return get_success_data(
        api_client.engage_coaching_referral(referral_id, make_coach_headers(coach_id))
    )


def log_sessions(referral_id, coach_id="coach-1", dates=None):
    """Log one coaching session per date as the assigned coach."""
    referral = None
    for date in (dates or SESSION_DATES):
        referral = get_success_data(
            api_client.log_coaching_session(
                referral_id, create_session_payload(session_date=date),
                make_coach_headers(coach_id),
            )
        )
    return referral


def discharge_referral(referral_id, coach_id="coach-1", outcome="GOALS_MET"):
    """ENGAGED -> DISCHARGED with the supplied outcome."""
    return get_success_data(
        api_client.discharge_coaching_referral(
            referral_id, {"outcome": outcome}, make_coach_headers(coach_id)
        )
    )


def setup_discharged_referral(reason="HIGH_RISK", outcome="GOALS_MET", sessions=None,
                              coach_id="coach-1", **enrollment_kwargs):
    """ACTIVE enrollment + referral walked REFERRED -> ENGAGED -> DISCHARGED.

    `sessions` defaults to the program's coaching_required_sessions dates.
    Returns dict(employer, program, employee, enrollment, referral).
    """
    ctx = setup_active_enrollment(**enrollment_kwargs)
    referral = create_referral(ctx["enrollment"]["id"], reason=reason)
    referral = engage_referral(referral["id"], coach_id)
    referral = log_sessions(
        referral["id"], coach_id,
        dates=(sessions if sessions is not None else SESSION_DATES),
    )
    referral = discharge_referral(referral["id"], coach_id, outcome)
    ctx["referral"] = referral
    return ctx


def compute_awards(program_id):
    """(Re)compute PROJECTED awards for the program. Returns the counts payload."""
    return get_success_data(
        api_client.compute_incentive_awards(compute_awards_payload(program_id), BA)
    )


def get_enrollment_award(enrollment_id):
    """Return the first award listed for the enrollment."""
    awards, _meta = _list(
        api_client.list_enrollment_incentive_awards(enrollment_id, BA)
    )
    assert awards, "expected at least one incentive award for the enrollment"
    return awards[0]


def setup_confirmed_award(**enrollment_kwargs):
    """Program CLOSED + award computed after close + CONFIRMED at the current clock.

    Returns dict(employer, program, employee, enrollment, award).
    """
    ctx = setup_active_enrollment(**enrollment_kwargs)
    close_program(ctx["program"]["id"])
    compute_awards(ctx["program"]["id"])
    award = get_enrollment_award(ctx["enrollment"]["id"])
    award = get_success_data(api_client.confirm_incentive_award(award["id"], BA))
    ctx["award"] = award
    return ctx


def create_invoice(program_id, **overrides):
    """Create a DRAFT vendor invoice with computed lines. Returns the invoice."""
    return get_success_data(
        api_client.create_vendor_invoice(
            create_invoice_payload(program_id, **overrides),
            TEST_USERS["vendor_manager_headers"],
        )
    )


def submit_invoice(invoice_id, submitter="ops-user-1"):
    """DRAFT -> SUBMITTED; records the caller's X-User-ID as submitted_by."""
    return get_success_data(
        api_client.submit_vendor_invoice(
            invoice_id, make_vendor_manager_headers(submitter)
        )
    )


def setup_submitted_invoice(submitter="ops-user-1", **enrollment_kwargs):
    """ACTIVE program + one ACTIVE enrollment + invoice DRAFT then SUBMITTED.

    Returns dict(employer, program, employee, enrollment, invoice).
    """
    ctx = setup_active_enrollment(**enrollment_kwargs)
    invoice = create_invoice(ctx["program"]["id"])
    invoice = submit_invoice(invoice["id"], submitter)
    ctx["invoice"] = invoice
    return ctx


def get_invoice(invoice_id):
    """Re-read an invoice through the program's invoice listing."""
    # VendorInvoice has no single-GET endpoint in PRD §4; read via program list.
    return invoice_by_id(invoice_id)


def invoice_by_id(invoice_id, program_id=None):
    """Find an invoice by id through the program listing (PRD §4 list endpoint)."""
    from prd_bench_local_runner.testing import validate_paginated

    if program_id is None:
        raise AssertionError("program_id is required to list invoices")
    data, _meta = validate_paginated(
        api_client.list_program_vendor_invoices(program_id, BA)
    )
    for invoice in data:
        if invoice["id"] == invoice_id:
            return invoice
    raise AssertionError(f"invoice {invoice_id} not found in program listing")


def _list(response):
    """Validate a list response and return (data, meta)."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)
