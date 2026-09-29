"""Invariants that must survive a mutation and its compensating reversal.

A paid disbursement that is reversed, and a finalized tax assessment that is
amended after its appointment is terminated, both have to leave the system's
running totals exactly where they started — with no drift of a cent.
"""
from test_helpers import (
    GS_ADMIN,
    MONTHLY_PERIODS_AUTUMN_2026,
    MONTHLY_PERIODS_SUMMER_2026,
    allocations_of,
    api_client,
    assert_assessment_identity,
    assert_funding_conservation,
    build_assessment,
    build_funded_appointment,
    disbursements_of,
    drive_appointment,
    fund_wholly_from,
    make_appointment,
    make_department,
    make_funding_source,
    make_pay_periods,
    make_policy,
    make_student,
    make_term,
    open_term,
    pay,
    read_appointment,
    read_assessment,
    read_source,
    read_student,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Paying and then reversing one disbursement
# --------------------------------------------------------------------------- #


def _build_payable_disbursement():
    """A four-period appointment with payroll scheduled and the term locked.

    Locking payroll is what makes a pay period `LOCKED`, and only a locked period
    may be paid.
    """
    world = build_funded_appointment(
        department={"code": "CHEM", "name": "Chemistry"},
        term={
            "term_code": "CONS2026", "term_start": "2026-09-01",
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
            "student_number": "GS-CONS-001", "full_name": "Cons Student",
            "degree_level": "DOCTORAL", "cumulative_gpa": 3.60,
            "enrolled_credit_hours": 8,
        },
        source={
            "source_code": "NSF-CONS-01", "source_type": "GRANT",
            "authorized_amount_cents": 5000000,
        },
        appointment={
            "assistantship_type": "RESEARCH", "effort_pct": 75,
            "start_date": "2026-09-01", "end_date": "2026-12-31",
            "monthly_stipend_cents": 300000,
        },
        advance_to="PAYROLL_SCHEDULED",
        lock_payroll_after=True,
    )
    world["allocation_id"] = allocations_of(
        world["appointment_id"], status="COMMITTED"
    )[0]["id"]
    world["first_disbursement_id"] = disbursements_of(
        world["appointment_id"], status="SCHEDULED"
    )[0]["id"]
    return world


def test_paying_a_disbursement_moves_committed_to_expended_without_freeing_budget():
    """The COMMITTED to EXPENDED direction leaves available untouched.

    PRD: "Payment moves money along the ledger: for each element of
    `allocation_split`, the named allocation's `disbursed_amount_cents` is
    increased by that element's `amount_cents`, and the corresponding source's
    `committed_amount_cents` falls while its `expended_amount_cents` rises by that
    same amount." PRD: "The conservation identity that must hold at all times is
    that `authorized_amount_cents` equals `available_amount_cents` plus
    `committed_amount_cents` plus `expended_amount_cents`."

    Design: Difficulty/compensating_invariant/funding_conservation_invariant_holds_across_pay_then_reverse
    """
    world = _build_payable_disbursement()

    before = read_source(world["source_id"])
    assert before["authorized_amount_cents"] == 5000000
    assert before["committed_amount_cents"] == 1600000, (
        "1200000 of stipend plus 400000 of remission"
    )
    assert before["expended_amount_cents"] == 0
    assert before["available_amount_cents"] == 3400000
    assert_funding_conservation(before)

    pay(world["first_disbursement_id"])

    after = read_source(world["source_id"])
    assert after["committed_amount_cents"] == 1300000
    assert after["expended_amount_cents"] == 300000
    assert after["available_amount_cents"] == 3400000, (
        "payment does not return money to available"
    )
    assert_funding_conservation(after)

    allocation = validate_success(
        api_client.get_funding_allocation(world["allocation_id"], GS_ADMIN)
    )
    assert allocation["disbursed_amount_cents"] == 300000

    appointment = read_appointment(world["appointment_id"])
    assert appointment["payroll_status"] == "PARTIALLY_DISBURSED"


def test_reversing_the_payment_restores_every_balance_to_its_prior_value():
    """The reversal is an exact undo, with no drift in any of the four integers.

    PRD: "It undoes the ledger movement exactly: for each element of
    `allocation_split`, the named allocation's `disbursed_amount_cents` is
    decreased by that element's `amount_cents`, and the source's
    `expended_amount_cents` falls while its `committed_amount_cents` rises by the
    same amount — so `authorized_amount_cents` still equals available plus
    committed plus expended." PRD: "The appointment's `payroll_status` is then
    recomputed: `PARTIALLY_DISBURSED` when at least one sibling disbursement of
    the appointment is still `PAID`, and `SCHEDULED` when none is."

    Design: Difficulty/compensating_invariant/funding_conservation_invariant_holds_across_pay_then_reverse
    """
    world = _build_payable_disbursement()
    pay(world["first_disbursement_id"])

    reversed_row = validate_success(api_client.reverse_stipend_disbursement(
        world["first_disbursement_id"],
        {"reversal_reason": "PAYROLL_KEYED_TO_WRONG_PERIOD"},
        GS_ADMIN,
    ))

    assert reversed_row["status"] == "REVERSED"
    assert reversed_row["reversal_reason"] == "PAYROLL_KEYED_TO_WRONG_PERIOD"
    assert reversed_row["gross_amount_cents"] == 300000, (
        "the reversed row keeps its amount"
    )

    source = read_source(world["source_id"])
    assert source["committed_amount_cents"] == 1600000
    assert source["expended_amount_cents"] == 0
    assert source["available_amount_cents"] == 3400000
    assert_funding_conservation(source)

    allocation = validate_success(
        api_client.get_funding_allocation(world["allocation_id"], GS_ADMIN)
    )
    assert allocation["status"] == "COMMITTED"
    assert allocation["disbursed_amount_cents"] == 0
    assert allocation["allocated_stipend_cents"] == 1200000
    assert allocation["allocated_remission_cents"] == 400000

    appointment = read_appointment(world["appointment_id"])
    assert appointment["payroll_status"] == "SCHEDULED"
    assert appointment["lifecycle_status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Terminating an appointment and amending its already-final assessment
# --------------------------------------------------------------------------- #

_INVARIANT_POLICY = {
    "assistantship_type": "RESEARCH", "degree_level": "DOCTORAL",
    "min_fte_monthly_stipend_cents": 400000,
    "per_credit_tuition_cents": 50000,
    "max_remission_cents_per_term": 500000,
    "term_insurance_premium_cents": 0,
    "tuition_tax_exempt_cap_cents": 525000,
}


def _build_two_finalized_assessments():
    """Two terms in tax year 2026, each finalized, together consuming the cap.

    The summer term takes 400000 exempt; the autumn term then has only 125000 of
    the 525000 annual cap left, so 275000 of its benefit is taxable.
    """
    department = make_department(code="PHIL", name="Philosophy")
    source = make_funding_source(
        department["id"], source_code="NSF-INV-01", source_type="GRANT",
        authorized_amount_cents=10000000,
        budget_period_start="2026-01-01", budget_period_end="2027-06-30",
    )
    student = make_student(
        student_number="GS-INV-001", full_name="Inv Student",
        degree_level="DOCTORAL", cumulative_gpa=3.60, enrolled_credit_hours=8,
    )

    world = {"student_id": student["id"]}
    for label, code, start, end, deadline, periods in (
        ("summer", "SUMC2026", "2026-05-01", "2026-08-31", "2026-06-15",
         MONTHLY_PERIODS_SUMMER_2026),
        ("autumn", "AUTC2026", "2026-09-01", "2026-12-31", "2026-11-15",
         MONTHLY_PERIODS_AUTUMN_2026),
    ):
        term = make_term(
            term_code=code, term_start=start, term_end=end,
            tax_calendar_year=2026, session_type="IN_SESSION",
            proration_method="CALENDAR_DAY", remission_drop_deadline=deadline,
        )
        make_policy(term["id"], **_INVARIANT_POLICY)
        make_pay_periods(term["id"], periods)
        open_term(term["id"])
        appointment = make_appointment(
            student["id"], department["id"], term["id"],
            assistantship_type="RESEARCH", effort_pct=75,
            start_date=start, end_date=end, monthly_stipend_cents=300000,
        )
        fund_wholly_from(appointment["id"], source["id"])
        drive_appointment(appointment["id"], "ACTIVE")
        world[f"{label}_term_id"] = term["id"]
        world[f"{label}_appointment_id"] = appointment["id"]

    world["summer_assessment_id"] = build_assessment(
        student["id"], world["summer_term_id"], finalize=True
    )["id"]
    world["autumn_assessment_id"] = build_assessment(
        student["id"], world["autumn_term_id"], finalize=True
    )["id"]
    return world


def _terminate_autumn_and_amend(world):
    validate_success(api_client.terminate_appointment(
        world["autumn_appointment_id"],
        {"termination_reason": "ADVISOR_FUNDING_ENDED"},
        GS_ADMIN,
    ))
    return validate_success(api_client.amend_tax_assessment(
        world["autumn_assessment_id"],
        {"amendment_reason":
            "APPOINTMENT_TERMINATED_BEFORE_REMISSION_DROP_DEADLINE"},
        GS_ADMIN,
    ))


def test_amending_after_termination_zeroes_the_benefit_and_its_derived_fields():
    """Losing the remission empties all four money fields of the assessment.

    PRD: "when `termination_date` falls before the term's
    `remission_drop_deadline`, `tuition_remission_cents` is set to 0". PRD: "It
    requires the assessment to be `FINAL`, and it requires the recomputation under
    `CALENDAR_YEAR_FINAL` to yield a `benefit_cents` different from the stored
    value; when nothing has actually changed the amendment is refused with
    `ERR_NO_ASSESSMENT_DELTA`. On success all four money fields are recomputed,
    `status` becomes `AMENDED`".

    Design: Difficulty/compensating_invariant/tuition_benefit_cap_released_with_zero_drift_after_terminate_and_amend
    """
    world = _build_two_finalized_assessments()

    before = read_assessment(world["autumn_assessment_id"])
    assert before["benefit_cents"] == 400000
    assert before["exempt_cents"] == 125000
    assert before["taxable_cents"] == 275000
    assert before["imputed_withholding_cents"] == 60500

    amended = _terminate_autumn_and_amend(world)

    terminated = read_appointment(world["autumn_appointment_id"])
    assert terminated["lifecycle_status"] == "TERMINATED"
    assert terminated["tuition_remission_cents"] == 0

    assert amended["status"] == "AMENDED"
    assert amended["benefit_cents"] == 0
    assert amended["exempt_cents"] == 0
    assert amended["taxable_cents"] == 0
    assert amended["imputed_withholding_cents"] == 0
    assert_assessment_identity(amended)


def test_the_amendment_releases_the_cap_it_had_consumed_without_drift():
    """The freed exemption returns to the year, and the untouched term is intact.

    PRD: "Two invariants hold: `benefit_cents` always equals `exempt_cents` plus
    `taxable_cents`, and the sum of `exempt_cents` over a student's `FINAL`
    assessments within one `tax_calendar_year` never exceeds the cap." PRD:
    "`tuition_benefit_ytd_cents`, the sum of `benefit_cents` over the student's
    `FINAL` tax assessments in the current `tax_calendar_year`; and
    `taxable_tuition_benefit_ytd_cents`, the corresponding sum of
    `taxable_cents`."

    Design: Difficulty/compensating_invariant/tuition_benefit_cap_released_with_zero_drift_after_terminate_and_amend
    """
    world = _build_two_finalized_assessments()

    _terminate_autumn_and_amend(world)

    summer = read_assessment(world["summer_assessment_id"])
    assert summer["status"] == "FINAL", "the summer assessment was never addressed"
    assert summer["benefit_cents"] == 400000
    assert summer["exempt_cents"] == 400000
    assert summer["taxable_cents"] == 0
    assert_assessment_identity(summer)

    assessments, _ = validate_paginated(api_client.list_tax_assessments(
        GS_ADMIN,
        {"student_id": world["student_id"], "status": "FINAL",
         "limit": 10, "offset": 0},
    ))
    exempt_total = sum(
        a["exempt_cents"] for a in assessments
        if a["tax_calendar_year"] == 2026
    )
    assert exempt_total == 400000, (
        "only the summer term still consumes the annual exemption"
    )

    student = read_student(world["student_id"])
    assert student["tuition_benefit_ytd_cents"] == 400000
    assert student["taxable_tuition_benefit_ytd_cents"] == 0
    assert student["total_effort_pct"] == 75, (
        "the surviving summer appointment still carries its effort"
    )
