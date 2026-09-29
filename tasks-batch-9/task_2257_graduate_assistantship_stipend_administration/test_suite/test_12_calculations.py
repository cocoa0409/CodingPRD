"""Derived money and effort figures, each pinned to one arithmetic rule.

The cases here isolate a single step of a single formula: a band selection, a
degree credit ceiling, a rounding direction, an input-set filter, a tier
breakpoint, an empty interval intersection and a variant restamp.
"""
import pytest

from test_helpers import (
    DEPT_ADMIN,
    GS_ADMIN,
    MONTHLY_PERIODS_AUTUMN_2026,
    SINGLE_PERIOD_AUTUMN_2026,
    allocations_of,
    api_client,
    assert_assessment_identity,
    build_assessment,
    build_funded_appointment,
    build_term_frame,
    fund_wholly_from,
    make_appointment,
    make_funding_source,
    make_student,
    read_appointment,
    read_student,
    validate_paginated,
    validate_success,
)

_TWO_PERIODS_SEP_TO_DEC = [
    (1, "2026-09-01", "2026-11-01", "2026-11-05"),
    (2, "2026-11-01", "2027-01-01", "2027-01-05"),
]


def test_thirty_three_percent_effort_gives_thirteen_point_two_hours_and_band_fifty():
    """One effort figure fixes the hours, the band and the insurance verdict.

    PRD: "The `weekly_hours` field is `effort_pct` divided by 100, multiplied by
    the 40 hours of a full-time week, rounded half up to one decimal place. The
    `duration_days` field is the count of whole days from `start_date` to
    `end_date` counting both endpoints — the difference in days plus one." PRD:
    "The boolean `insurance_eligible` is true only when both conditions hold:
    `effort_pct` is at least the policy's `insurance_min_effort_pct`, and
    `duration_days` is at least the policy's `min_insurance_duration_days`;
    otherwise it is false."

    Design: Corner/calculations/effort_profile_at_thirty_three_percent_yields_band_fifty
    """
    frame = build_term_frame(
        policy={"term_insurance_premium_cents": 600000},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
    )
    student = make_student(student_number="GS-1020")

    appointment = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=33, monthly_stipend_cents=200000,
    )

    assert float(appointment["weekly_hours"]) == pytest.approx(13.2, abs=0.01), (
        "33 percent of a 40-hour week is 13.2 hours"
    )
    assert appointment["duration_days"] == 122, (
        "2026-09-01 through 2026-12-31 inclusive is 122 days"
    )
    assert appointment["tuition_remission_pct"] == 50, (
        "33 is at least 25 and below 50"
    )
    assert appointment["insurance_eligible"] is False, (
        "33 percent effort misses the policy minimum of 50"
    )


def test_a_masters_students_remission_stops_at_nine_credits():
    """The degree ceiling binds before the policy ceiling ever comes into play.

    PRD: "The remitted credit count is the smaller of the student's
    `enrolled_credit_hours` and the degree ceiling, which is 9 credits for a
    `MASTERS` student and 12 credits for a `DOCTORAL` student. The gross remission
    is the remitted credit count multiplied by the policy's
    `per_credit_tuition_cents`, multiplied by the band percentage, divided by 100,
    rounded half up to a whole cent." PRD: "Finally, `tuition_remission_cents` is
    the smaller of the funded remission and the policy's
    `max_remission_cents_per_term`."

    Design: Corner/calculations/masters_credit_cap_limits_remission_to_nine_credits
    """
    world = build_funded_appointment(
        policy={"degree_level": "MASTERS", "per_credit_tuition_cents": 50000,
                "max_remission_cents_per_term": 900000,
                "term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1021", "full_name": "Mia Sloan",
                 "degree_level": "MASTERS", "cumulative_gpa": 3.40,
                 "enrolled_credit_hours": 12},
        advance_to="SUBMITTED",
    )

    appointment = read_appointment(world["appointment_id"])
    assert appointment["tuition_remission_pct"] == 100
    assert appointment["tuition_remission_cents"] == 450000, (
        "nine remitted credits at 50000 cents, at the 100 percent band"
    )
    assert appointment["tuition_remission_cents"] != 600000, (
        "all twelve enrolled credits would give 600000"
    )
    assert appointment["total_stipend_cents"] == 300000

    allocations = allocations_of(world["appointment_id"])
    assert len(allocations) == 1
    assert allocations[0]["allocated_remission_cents"] == 450000
    assert allocations[0]["allocated_stipend_cents"] == 300000


def test_an_exact_half_cent_of_withholding_rounds_upward():
    """Twenty-two percent of 100025 is 22005.5, which must become 22006.

    PRD: "Whichever variant ran, `imputed_withholding_cents` is `taxable_cents`
    multiplied by an imputed withholding rate of 0.2200 — twenty-two percent —
    rounded half up to a whole cent." PRD: "Under **`TERM_PROVISIONAL`**, the cap
    is applied to the term in isolation: `exempt_cents` is the smaller of
    `benefit_cents` and the cap, and `taxable_cents` is `benefit_cents` minus
    `exempt_cents`."

    Design: Corner/calculations/imputed_withholding_rounds_half_up_at_exact_half_cent
    """
    world = build_funded_appointment(
        policy={"per_credit_tuition_cents": 100025,
                "max_remission_cents_per_term": 200000,
                "term_insurance_premium_cents": 0,
                "tuition_tax_exempt_cap_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1022", "enrolled_credit_hours": 1},
        advance_to="ACTIVE",
    )
    assert read_appointment(world["appointment_id"])[
        "tuition_remission_cents"] == 100025

    assessment = build_assessment(world["student_id"], world["term_id"])

    assert assessment["benefit_cents"] == 100025
    assert assessment["exempt_cents"] == 0, "the term's exemption cap is 0"
    assert assessment["taxable_cents"] == 100025
    assert assessment["imputed_withholding_cents"] == 22006, (
        "22005.5 rounds half up, never down"
    )
    assert assessment["imputed_withholding_cents"] != 22005
    assert_assessment_identity(assessment)


def test_draft_and_returned_appointments_are_left_out_of_the_effort_aggregate():
    """A hundred percent of uncounted effort does not consume the student's cap.

    PRD: "The **counted lifecycle states** are `SUBMITTED`, `FUNDING_VERIFIED`,
    `APPROVED`, `ACTIVE` and `NON_RENEWAL_PENDING`; appointments in `DRAFT`,
    `RETURNED`, `COMPLETED`, `TERMINATED` and `CANCELLED` are excluded from every
    effort figure." PRD: "Then the **aggregate effort cap**: the student's
    `total_effort_pct` computed with this appointment included must not exceed the
    student's `effort_cap_pct`, with a value exactly equal to the cap passing and
    anything above rejected as `ERR_OVER_APPOINTMENT`."

    Design: Corner/calculations/effort_aggregate_excludes_draft_and_returned_appointments
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    source = make_funding_source(frame["department_id"])
    student = make_student(student_number="GS-1023")
    assert student["effort_cap_pct"] == 75

    drafted = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=50, monthly_stipend_cents=200000,
    )
    returned = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=50, monthly_stipend_cents=200000,
    )
    fund_wholly_from(returned["id"], source["id"])
    validate_success(api_client.submit_appointment(returned["id"], DEPT_ADMIN))
    validate_success(api_client.return_appointment(
        returned["id"], {"return_reason": "BUDGET_REWORK"}, GS_ADMIN
    ))
    candidate = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=75, monthly_stipend_cents=300000,
    )
    fund_wholly_from(candidate["id"], source["id"])

    submitted = validate_success(
        api_client.submit_appointment(candidate["id"], DEPT_ADMIN)
    )

    assert submitted["lifecycle_status"] == "SUBMITTED"
    aggregate = read_student(student["id"])
    assert aggregate["total_effort_pct"] == 75, (
        "the two uncounted appointments contribute nothing"
    )
    assert float(aggregate["assigned_hours_per_week"]) == pytest.approx(
        30.0, abs=0.01
    )
    assert read_appointment(drafted["id"])["lifecycle_status"] == "DRAFT"
    assert read_appointment(returned["id"])["lifecycle_status"] == "RETURNED"


def test_a_gross_of_exactly_twelve_thousand_dollars_takes_the_seventy_five_tier():
    """The tier reads the pre-offset gross, and its lower bound is inclusive.

    PRD: "The subsidy tier is selected from that **pre-offset gross**: 90 percent
    when the gross is below twelve thousand dollars (1200000 cents); 75 percent
    when the gross is at least 1200000 cents and below eighteen thousand dollars
    (1800000 cents); and 50 percent when the gross is at least 1800000 cents."
    PRD: "The tier is keyed on the gross from the first step and never on the net
    produced by the last, because keying it on the net would select a lower tier
    whenever the gross sits just above a breakpoint."

    Design: Corner/calculations/insurance_subsidy_tier_at_exact_low_breakpoint
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 600000},
        pay_periods=MONTHLY_PERIODS_AUTUMN_2026,
        student={"student_number": "GS-1024"},
        advance_to="SUBMITTED",
    )

    appointment = read_appointment(world["appointment_id"])
    assert appointment["projected_pay_period_count"] == 4
    assert appointment["total_stipend_cents"] == 1200000
    assert appointment["insurance_eligible"] is True
    assert appointment["insurance_subsidy_cents"] == 450000, (
        "75 percent of a 600000-cent premium"
    )
    assert appointment["insurance_subsidy_cents"] != 540000, (
        "the 90 percent tier belongs to a gross below 1200000"
    )
    assert appointment["employee_premium_cents"] == 150000
    assert appointment["net_term_stipend_cents"] == 1050000


def test_the_lowest_remission_band_opens_at_twenty_five_percent_effort():
    """Twenty-four percent earns nothing; twenty-five earns half.

    PRD: "And `tuition_remission_pct` is selected from `effort_pct` by band: 0
    when `effort_pct` is below 25; 50 when `effort_pct` is at least 25 and below
    50; 75 when `effort_pct` is at least 50 and below 75; and 100 when `effort_pct`
    is at least 75." PRD: "Non-monetary rounding appears in exactly one place:
    weekly hours are carried to one decimal place, rounded half up."

    Design: Corner/calculations/remission_band_is_zero_below_twenty_five_and_fifty_at_twenty_five
    """
    frame = build_term_frame(pay_periods=SINGLE_PERIOD_AUTUMN_2026)
    student = make_student(student_number="GS-1025", enrolled_credit_hours=9)

    below_band = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=24, monthly_stipend_cents=96000,
    )
    at_band = make_appointment(
        student["id"], frame["department_id"], frame["term_id"],
        effort_pct=25, monthly_stipend_cents=100000,
    )

    assert below_band["tuition_remission_pct"] == 0
    assert float(below_band["weekly_hours"]) == pytest.approx(9.6, abs=0.01)
    assert at_band["tuition_remission_pct"] == 50
    assert float(at_band["weekly_hours"]) == pytest.approx(10.0, abs=0.01)


def test_a_pay_period_the_appointment_never_touches_produces_no_disbursement():
    """An empty overlap is skipped by both the projection and the materialisation.

    PRD: "For each period, the overlap start is the later of the period's
    `period_start` and the appointment's `start_date`, and the overlap end is the
    earlier of the period's `period_end_exclusive` and the day after the
    appointment's `end_date`; if the overlap end falls on or before the overlap
    start, the period is skipped entirely and contributes nothing." PRD: "That
    period's gross is `monthly_stipend_cents` multiplied by the covered count,
    divided by the period count, rounded half up to a whole cent."

    Design: Corner/calculations/pay_period_with_empty_intersection_produces_no_disbursement
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 600000},
        pay_periods=_TWO_PERIODS_SEP_TO_DEC,
        student={"student_number": "GS-1026"},
        appointment={"end_date": "2026-10-31"},
        advance_to="PAYROLL_SCHEDULED",
    )
    first_period_id = world["pay_periods"][0]["id"]
    second_period_id = world["pay_periods"][1]["id"]

    appointment = read_appointment(world["appointment_id"])
    assert appointment["duration_days"] == 61
    assert appointment["insurance_eligible"] is False, (
        "61 days misses the policy minimum of 90"
    )
    assert appointment["projected_pay_period_count"] == 1
    assert appointment["total_stipend_cents"] == 300000
    assert appointment["net_term_stipend_cents"] == 300000, (
        "an ineligible appointment carries no premium at all"
    )

    rows, meta = validate_paginated(api_client.list_stipend_disbursements(
        GS_ADMIN,
        {"appointment_id": world["appointment_id"], "limit": 10, "offset": 0},
    ))
    assert meta["total_count"] == 1
    assert rows[0]["pay_period_id"] == first_period_id
    assert rows[0]["covered_units"] == 61
    assert rows[0]["period_units"] == 61
    assert rows[0]["gross_amount_cents"] == 300000
    assert all(row["pay_period_id"] != second_period_id for row in rows), (
        "the November period was never intersected"
    )


def test_finalizing_restamps_the_assessment_under_the_calendar_year_variant():
    """One row carries the provisional variant, then the final one, in place.

    PRD: "The assessment copies the term's `tax_calendar_year` at creation, is
    born `PROVISIONAL` with `variant_applied` of `TERM_PROVISIONAL` and
    `amendment_reason` null, and increments the student's `version` by one." PRD:
    "Finalization recomputes `benefit_cents`, `exempt_cents`, `taxable_cents` and
    `imputed_withholding_cents` under the `CALENDAR_YEAR_FINAL` variant, sets
    `status` to `FINAL` and `variant_applied` to `CALENDAR_YEAR_FINAL`, and then
    recomputes the student's `tuition_benefit_ytd_cents` and
    `taxable_tuition_benefit_ytd_cents` and increments the student's `version`."

    Design: Corner/calculations/assessment_variant_switches_from_term_provisional_to_calendar_year_final
    """
    world = build_funded_appointment(
        policy={"term_insurance_premium_cents": 0},
        pay_periods=SINGLE_PERIOD_AUTUMN_2026,
        student={"student_number": "GS-1027", "enrolled_credit_hours": 9},
        advance_to="ACTIVE",
    )

    provisional = build_assessment(world["student_id"], world["term_id"])
    assert provisional["status"] == "PROVISIONAL"
    assert provisional["variant_applied"] == "TERM_PROVISIONAL"
    assert provisional["amendment_reason"] is None
    assert provisional["tax_calendar_year"] == 2026
    assert provisional["benefit_cents"] == 450000
    assert provisional["exempt_cents"] == 450000
    assert provisional["taxable_cents"] == 0
    assert provisional["imputed_withholding_cents"] == 0

    finalized = validate_success(
        api_client.finalize_tax_assessment(provisional["id"], GS_ADMIN)
    )

    assert finalized["id"] == provisional["id"]
    assert finalized["status"] == "FINAL"
    assert finalized["variant_applied"] == "CALENDAR_YEAR_FINAL"
    assert finalized["benefit_cents"] == 450000
    assert finalized["exempt_cents"] == 450000, (
        "the year total of 450000 stays under the 525000 cap"
    )
    assert finalized["taxable_cents"] == 0
    assert_assessment_identity(finalized)

    student = read_student(world["student_id"])
    assert student["tuition_benefit_ytd_cents"] == 450000
    assert student["taxable_tuition_benefit_ytd_cents"] == 0
