"""Requests rigged to fail two checks at once, to pin down which one wins.

Each scenario arranges a single call that violates two rules from the fixed
system-wide evaluation sequence, and asserts both that the earlier rule's error
comes back and that the later rule's error does not.
"""
from test_helpers import (
    ApiErrorId,
    GRANT_ACCOUNTANT,
    DEPT_ADMIN,
    MONTHLY_PERIODS_AUTUMN_2026,
    allocations_of,
    api_client,
    build_funded_appointment,
    lock_term_payroll,
    make_appointment,
    make_department,
    make_funding_source,
    make_pay_periods,
    make_policy,
    make_student,
    make_term,
    open_term,
    read_appointment,
    read_source,
    read_student,
    set_funding_plan,
    validate_error,
)

# --------------------------------------------------------------------------- #
# Verify funding against a locked term whose grant is also too small
# --------------------------------------------------------------------------- #


def _build_underfunded_appointment_in_a_locked_term():
    """A submitted appointment needing 1200000 cents from a 1000000-cent grant,
    in a term whose payroll has since been locked."""
    world = build_funded_appointment(
        department={"code": "STAT", "name": "Statistics"},
        term={
            "term_code": "PRIO2026", "term_start": "2026-09-01",
            "term_end": "2026-12-31", "tax_calendar_year": 2026,
            "session_type": "IN_SESSION", "proration_method": "CALENDAR_DAY",
            "remission_drop_deadline": "2026-11-15",
        },
        policy={
            "assistantship_type": "RESEARCH", "degree_level": "DOCTORAL",
            "min_fte_monthly_stipend_cents": 400000,
            "per_credit_tuition_cents": 50000,
            "max_remission_cents_per_term": 500000,
            "term_insurance_premium_cents": 0,
        },
        pay_periods=MONTHLY_PERIODS_AUTUMN_2026,
        student={
            "student_number": "GS-PRIO-001", "full_name": "Prio Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.60,
            "enrolled_credit_hours": 0,
        },
        source={
            "source_code": "NSF-PRIO-01", "source_type": "GRANT",
            "authorized_amount_cents": 1000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-31",
            "monthly_stipend_cents": 300000,
        },
        advance_to="SUBMITTED",
    )
    lock_term_payroll(world["term_id"])
    return world


def test_locked_term_outranks_insufficient_funding_on_verify_funding():
    """Check 11 rejects before check 36 is ever reached.

    PRD: "11. **Governing term open** — the governing term's `status` is `OPEN`,
    else `ERR_TERM_NOT_OPEN` (409). This guards declaring a stipend policy (which
    also accepts a `PLANNING` term), replacing a funding plan, and appointment
    submission, return, funding verification, approval, activation and payroll
    scheduling." PRD: "36. **Funding sufficiency** — `ERR_FUNDING_INSUFFICIENT`
    (422), guarding funding verification." PRD: "The server evaluates, in this
    exact sequence, stopping at the first failure".

    Design: Difficulty/priority_pair_validation_conflict/term_not_open_outranks_funding_insufficient_on_verify_funding
    """
    world = _build_underfunded_appointment_in_a_locked_term()

    response = api_client.verify_funding(world["appointment_id"], GRANT_ACCOUNTANT)

    error = validate_error(response, ApiErrorId.ERR_TERM_NOT_OPEN.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_FUNDING_INSUFFICIENT.value, (
        "the funding shortfall is real but sits at position 36 in the sequence"
    )


def test_rejected_verify_funding_leaves_the_appointment_and_ledger_untouched():
    """A rejection at check 11 commits nothing further down the chain.

    PRD: "Allocations in `PROPOSED` never encumber anything: a drafted funding
    plan has no fiscal effect until it is committed." Because the request stopped
    at the governing term check, the plan never moved to `COMMITTED` and the
    grant's balance triple is still the one it was created with.

    Design: Difficulty/priority_pair_validation_conflict/term_not_open_outranks_funding_insufficient_on_verify_funding
    """
    world = _build_underfunded_appointment_in_a_locked_term()

    api_client.verify_funding(world["appointment_id"], GRANT_ACCOUNTANT)

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "SUBMITTED"

    allocations = allocations_of(world["appointment_id"])
    assert len(allocations) == 1
    assert allocations[0]["status"] == "PROPOSED"

    source = read_source(world["source_id"])
    assert source["committed_amount_cents"] == 0
    assert source["available_amount_cents"] == 1000000


# --------------------------------------------------------------------------- #
# Submit an international student's over-hours appointment on a broken plan
# --------------------------------------------------------------------------- #


def _build_international_appointment_with_broken_shares():
    """An F-1 student at 30 weekly hours whose plan only totals 90.00 percent."""
    department = make_department(code="CSCI", name="Computer Science")
    term = make_term(
        term_code="INTL2026", term_start="2026-09-01", term_end="2026-12-31",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-11-15",
    )
    make_policy(
        term["id"], assistantship_type="RESEARCH", degree_level="MASTERS",
        min_fte_monthly_stipend_cents=400000,
        per_credit_tuition_cents=50000,
        max_remission_cents_per_term=500000,
        term_insurance_premium_cents=0,
    )
    make_pay_periods(term["id"], [(1, "2026-09-01", "2027-01-01", "2027-01-05")])
    open_term(term["id"])

    student = make_student(
        student_number="GS-INTL-001", full_name="Intl Student",
        degree_level="MASTERS", is_international=True, visa_type="F1",
        cumulative_gpa=3.60, enrolled_credit_hours=0, external_weekly_hours=0,
    )
    nsf = make_funding_source(
        department["id"], source_code="NSF-INTL-01", source_type="GRANT",
        authorized_amount_cents=5000000,
    )
    nih = make_funding_source(
        department["id"], source_code="NIH-INTL-01", source_type="GRANT",
        authorized_amount_cents=5000000,
    )
    appointment = make_appointment(
        student["id"], department["id"], term["id"],
        assistantship_type="RESEARCH", effort_pct=75,
        start_date="2026-09-01", end_date="2026-12-31",
        monthly_stipend_cents=300000,
    )
    set_funding_plan(appointment["id"], [
        (nsf["id"], 45.00, False),
        (nih["id"], 45.00, False),
    ])
    return {"appointment_id": appointment["id"], "student_id": student["id"]}


def test_international_hour_limit_outranks_invalid_allocation_shares_on_submit():
    """Check 14 rejects before check 28 is ever reached.

    PRD: "14. **International hour limit** —
    `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED` (422), as described in §2.9." PRD:
    "28. **Shares total** — `ERR_ALLOCATION_SHARES_INVALID` (422)." PRD: "when
    the student is international and the term's `session_type` is `IN_SESSION`,
    the student's `assigned_hours_per_week` computed with this appointment
    included, plus the student's `external_weekly_hours`, must not exceed 20.0
    hours; exactly 20.0 passes, more is
    `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/international_hour_limit_outranks_allocation_shares_invalid_on_submit
    """
    world = _build_international_appointment_with_broken_shares()

    response = api_client.submit_appointment(world["appointment_id"], DEPT_ADMIN)

    error = validate_error(
        response, ApiErrorId.ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED.value, 422
    )
    assert error["error_id"] != (
        ApiErrorId.ERR_ALLOCATION_SHARES_INVALID.value
    ), "the 90.00 percent plan is also invalid but sits at position 28"


def test_rejected_submission_computes_no_money_and_no_effort():
    """A submission that fails the battery performs none of its side effects.

    PRD: "Once the battery passes, the appointment's `lifecycle_status` becomes
    `SUBMITTED`, `submitted_by_user_id` records the acting `X-User-ID`, and
    `return_reason` is cleared to null. Four calculations then run, in this
    order, and together they populate every money field on the appointment and on
    its allocations." PRD: "Submission finally recomputes the student's
    `total_effort_pct` and `assigned_hours_per_week`".

    Design: Difficulty/priority_pair_validation_conflict/international_hour_limit_outranks_allocation_shares_invalid_on_submit
    """
    world = _build_international_appointment_with_broken_shares()

    api_client.submit_appointment(world["appointment_id"], DEPT_ADMIN)

    appointment = read_appointment(world["appointment_id"])
    assert appointment["lifecycle_status"] == "DRAFT"
    assert appointment["submitted_by_user_id"] is None
    assert appointment["total_stipend_cents"] == 0
    assert appointment["tuition_remission_cents"] == 0

    student = read_student(world["student_id"])
    assert student["total_effort_pct"] == 0
    assert float(student["assigned_hours_per_week"]) == 0.0
