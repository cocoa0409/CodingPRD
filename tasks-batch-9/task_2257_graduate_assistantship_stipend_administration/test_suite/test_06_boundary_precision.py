"""Values sitting exactly on a declared boundary, paired with the value below it.

Every threshold in this specification is inclusive, so each scenario asserts the
boundary value passes and the neighbouring value one unit below does not.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEPT_ADMIN,
    api_client,
    fund_wholly_from,
    make_appointment,
    make_department,
    make_funding_source,
    make_pay_periods,
    make_policy,
    make_student,
    make_term,
    open_term,
    read_appointment,
    read_student,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Effort exactly at the policy's insurance minimum
# --------------------------------------------------------------------------- #


def _build_insurance_boundary_pair():
    """Two identical appointments differing only by one percentage point of effort.

    The policy requires 50 percent effort and 90 days for insurance eligibility,
    and the 2026-09-01..2026-12-31 window is 122 days, so effort alone decides.
    """
    department = make_department(code="HIST", name="History")
    term = make_term(
        term_code="BND2026", term_start="2026-09-01", term_end="2026-12-31",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-11-15",
    )
    make_policy(
        term["id"], assistantship_type="RESEARCH", degree_level="DOCTORAL",
        min_fte_monthly_stipend_cents=380000,
        per_credit_tuition_cents=50000,
        max_remission_cents_per_term=500000,
        term_insurance_premium_cents=0,
        insurance_min_effort_pct=50,
        min_insurance_duration_days=90,
    )
    make_pay_periods(term["id"], [(1, "2026-09-01", "2027-01-01", "2027-01-05")])
    open_term(term["id"])

    at_boundary_student = make_student(
        student_number="GS-BND-050", full_name="Bnd Fifty",
        degree_level="DOCTORAL", cumulative_gpa=3.60, enrolled_credit_hours=0,
    )
    below_boundary_student = make_student(
        student_number="GS-BND-049", full_name="Bnd FortyNine",
        degree_level="DOCTORAL", cumulative_gpa=3.60, enrolled_credit_hours=0,
    )

    def _draft(student_id, effort_pct):
        return make_appointment(
            student_id, department["id"], term["id"],
            assistantship_type="RESEARCH", effort_pct=effort_pct,
            start_date="2026-09-01", end_date="2026-12-31",
            monthly_stipend_cents=200000,
        )

    return (_draft(at_boundary_student["id"], 50),
            _draft(below_boundary_student["id"], 49))


def test_effort_exactly_at_the_insurance_minimum_is_eligible():
    """Fifty percent effort meets a minimum of fifty and lands in the 75 band.

    PRD: "The boolean `insurance_eligible` is true only when both conditions
    hold: `effort_pct` is at least the policy's `insurance_min_effort_pct`, and
    `duration_days` is at least the policy's `min_insurance_duration_days`;
    otherwise it is false." PRD: "A value exactly equal to a cap passes the cap
    check; a value exactly equal to a minimum satisfies the minimum; a band whose
    lower bound is stated as "at least" admits the boundary value."

    Design: Difficulty/boundary_precision_check/effort_pct_exactly_at_insurance_minimum_is_eligible_with_band_seventy_five
    """
    at_boundary, _ = _build_insurance_boundary_pair()

    assert at_boundary["insurance_eligible"] is True
    assert at_boundary["tuition_remission_pct"] == 75, (
        "the band is 75 when effort_pct is at least 50 and below 75"
    )
    assert float(at_boundary["weekly_hours"]) == pytest.approx(20.0, abs=0.01)
    assert at_boundary["duration_days"] == 122
    assert at_boundary["lifecycle_status"] == "DRAFT"
    assert at_boundary["payroll_status"] == "NOT_SCHEDULED"


def test_effort_one_point_below_the_insurance_minimum_is_not_eligible():
    """Forty-nine percent misses the minimum and drops a remission band.

    PRD: "And `tuition_remission_pct` is selected from `effort_pct` by band: 0
    when `effort_pct` is below 25; 50 when `effort_pct` is at least 25 and below
    50; 75 when `effort_pct` is at least 50 and below 75; and 100 when
    `effort_pct` is at least 75." PRD: "Non-monetary rounding appears in exactly
    one place: weekly hours are carried to one decimal place, rounded half up."

    Design: Difficulty/boundary_precision_check/effort_pct_exactly_at_insurance_minimum_is_eligible_with_band_seventy_five
    """
    _, below_boundary = _build_insurance_boundary_pair()

    assert below_boundary["insurance_eligible"] is False
    assert below_boundary["tuition_remission_pct"] == 50, (
        "49 is at least 25 and below 50"
    )
    assert float(below_boundary["weekly_hours"]) == pytest.approx(19.6, abs=0.01), (
        "49 percent of 40 hours is 19.6"
    )
    assert below_boundary["duration_days"] == 122, (
        "the window is identical; only effort differs"
    )
    assert below_boundary["lifecycle_status"] == "DRAFT"
    assert below_boundary["payroll_status"] == "NOT_SCHEDULED"


# --------------------------------------------------------------------------- #
# Full-time-equivalent monthly rate exactly at the policy minimum
# --------------------------------------------------------------------------- #


def _build_stipend_minimum_boundary_pair():
    """Two appointments at 60 percent effort: one paying 240000, one 239999.

    At 60 percent effort, 240000 scales to exactly the policy's 400000 minimum,
    while 239999 scales to 399998.  The grant's effort cap is set to exactly 60
    so that it is met, not breached.
    """
    department = make_department(code="GEOL", name="Geology")
    term = make_term(
        term_code="BNDS2026", term_start="2026-09-01", term_end="2026-09-30",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-09-15",
    )
    make_policy(
        term["id"], assistantship_type="RESEARCH", degree_level="DOCTORAL",
        min_fte_monthly_stipend_cents=400000,
        per_credit_tuition_cents=50000,
        max_remission_cents_per_term=500000,
        term_insurance_premium_cents=0,
    )
    make_pay_periods(term["id"], [(1, "2026-09-01", "2026-10-01", "2026-10-05")])
    open_term(term["id"])

    source = make_funding_source(
        department["id"], source_code="NSF-BNDS-01", source_type="GRANT",
        authorized_amount_cents=5000000, grant_effort_cap_pct=60,
    )

    drafts = {}
    for label, student_number, monthly in (
        ("at", "GS-BNDS-A", 240000),
        ("below", "GS-BNDS-B", 239999),
    ):
        student = make_student(
            student_number=student_number, full_name=f"Bnds {label}",
            degree_level="DOCTORAL", cumulative_gpa=3.60,
            enrolled_credit_hours=0,
        )
        appointment = make_appointment(
            student["id"], department["id"], term["id"],
            assistantship_type="RESEARCH", effort_pct=60,
            start_date="2026-09-01", end_date="2026-09-30",
            monthly_stipend_cents=monthly,
        )
        fund_wholly_from(appointment["id"], source["id"])
        drafts[label] = {
            "appointment_id": appointment["id"], "student_id": student["id"],
        }
    return drafts


def test_fte_monthly_rate_exactly_at_the_policy_minimum_is_accepted():
    """A scaled rate exactly equal to the minimum satisfies the minimum.

    PRD: "The **stipend minimum** compares the appointment's full-time-equivalent
    monthly rate against policy: take `monthly_stipend_cents`, multiply by 100,
    divide by `effort_pct`, round the result half up to a whole cent, and require
    it to be at least the policy's `min_fte_monthly_stipend_cents`; a value
    exactly equal to the minimum passes, below it is `ERR_STIPEND_BELOW_MINIMUM`."

    Design: Difficulty/boundary_precision_check/fte_stipend_exactly_at_policy_minimum_passes_one_cent_below_rejected
    """
    drafts = _build_stipend_minimum_boundary_pair()

    submitted = validate_success(api_client.submit_appointment(
        drafts["at"]["appointment_id"], DEPT_ADMIN
    ))

    assert submitted["lifecycle_status"] == "SUBMITTED"
    assert submitted["total_stipend_cents"] == 240000
    assert submitted["projected_pay_period_count"] == 1
    assert float(submitted["weekly_hours"]) == pytest.approx(24.0, abs=0.01)
    assert submitted["tuition_remission_pct"] == 75


def test_fte_monthly_rate_one_cent_below_the_policy_minimum_is_rejected():
    """One cent less fails the minimum, and the grant cap is not the complaint.

    PRD: "34. **Stipend minimum** — `ERR_STIPEND_BELOW_MINIMUM` (422)." PRD: "The
    **grant effort cap** applies to each allocation whose source has
    `source_type` of `GRANT`: the effort that allocation draws from the grant is
    `effort_pct` multiplied by that allocation's `share_pct` divided by 100, and
    it must not exceed the source's `grant_effort_cap_pct`; exactly equal passes,
    above is `ERR_GRANT_EFFORT_CAP_EXCEEDED`." Sixty percent effort drawn wholly
    from a grant capped at 60 is exactly equal, so it passes.

    Design: Difficulty/boundary_precision_check/fte_stipend_exactly_at_policy_minimum_passes_one_cent_below_rejected
    """
    drafts = _build_stipend_minimum_boundary_pair()
    validate_success(api_client.submit_appointment(
        drafts["at"]["appointment_id"], DEPT_ADMIN
    ))

    response = api_client.submit_appointment(
        drafts["below"]["appointment_id"], DEPT_ADMIN
    )

    body = validate_error(
        response, ApiErrorId.ERR_STIPEND_BELOW_MINIMUM.value, 422
    )
    assert body["error_id"] != ApiErrorId.ERR_GRANT_EFFORT_CAP_EXCEEDED.value, (
        "60 percent effort exactly meets a grant cap of 60"
    )

    rejected = read_appointment(drafts["below"]["appointment_id"])
    assert rejected["lifecycle_status"] == "DRAFT"
    assert rejected["total_stipend_cents"] == 0

    student = read_student(drafts["below"]["student_id"])
    assert student["total_effort_pct"] == 0
