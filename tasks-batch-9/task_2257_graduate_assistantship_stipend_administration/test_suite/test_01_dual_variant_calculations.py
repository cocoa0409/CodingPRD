"""Both proration variants and both taxation variants, driven side by side.

Each of these scenarios builds two otherwise-identical worlds that differ in
exactly one declared switch, so the divergence the PRD promises is observable as
a difference between two numbers rather than as a single absolute figure.
"""
import pytest

from test_helpers import (
    MONTHLY_PERIODS_AUTUMN_2026,
    MONTHLY_PERIODS_SUMMER_2026,
    build_assessment,
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
    read_assessment,
    read_student,
    submit,
)

# --------------------------------------------------------------------------- #
# Proration: one CALENDAR_DAY term and one WORKDAY term, same money, same dates
# --------------------------------------------------------------------------- #

_PRORATION_POLICY = {
    "assistantship_type": "RESEARCH",
    "degree_level": "DOCTORAL",
    "min_fte_monthly_stipend_cents": 300000,
    "per_credit_tuition_cents": 50000,
    "max_remission_cents_per_term": 500000,
    "term_insurance_premium_cents": 0,
    "insurance_min_effort_pct": 50,
    "min_insurance_duration_days": 90,
    "tuition_tax_exempt_cap_cents": 525000,
}

# September and October 2026 as whole calendar months.
_SEP_OCT_2026 = [
    (1, "2026-09-01", "2026-10-01", "2026-10-05"),
    (2, "2026-10-01", "2026-11-01", "2026-11-05"),
]


def _submit_prorated_appointment(department_id, term_code, proration_method,
                                 student_number, full_name, source_code):
    """One term under the named proration method, with one submitted appointment.

    The appointment runs 2026-09-01 through 2026-10-15, so it covers the first
    pay period whole and the second one only part way — the only place the two
    proration methods can disagree.
    """
    term = make_term(
        term_code=term_code,
        term_start="2026-09-01",
        term_end="2026-12-15",
        tax_calendar_year=2026,
        session_type="IN_SESSION",
        proration_method=proration_method,
        remission_drop_deadline="2026-11-15",
    )
    make_policy(term["id"], **_PRORATION_POLICY)
    make_pay_periods(term["id"], _SEP_OCT_2026)
    open_term(term["id"])

    student = make_student(
        student_number=student_number,
        full_name=full_name,
        degree_level="DOCTORAL",
        is_international=False,
        cumulative_gpa=3.50,
        enrolled_credit_hours=0,
    )
    source = make_funding_source(
        department_id,
        source_code=source_code,
        source_type="GRANT",
        authorized_amount_cents=5000000,
        budget_period_start="2026-07-01",
        budget_period_end="2027-06-30",
        allows_tuition_remission=True,
        sponsor_code="NSF",
        grant_effort_cap_pct=100,
        auto_reinstate_threshold_cents=0,
    )
    appointment = make_appointment(
        student["id"], department_id, term["id"],
        assistantship_type="RESEARCH",
        effort_pct=75,
        start_date="2026-09-01",
        end_date="2026-10-15",
        monthly_stipend_cents=250000,
        supervisor_user_id="user-fac-7",
    )
    fund_wholly_from(appointment["id"], source["id"])
    return submit(appointment["id"])


def _submit_both_proration_variants():
    department = make_department(code="CHEM", name="Chemistry")
    calendar_day = _submit_prorated_appointment(
        department["id"], "CALPRO2026", "CALENDAR_DAY",
        "GS-CAL-001", "Cal Student", "NSF-CAL-01",
    )
    workday = _submit_prorated_appointment(
        department["id"], "WRKPRO2026", "WORKDAY",
        "GS-WRK-001", "Wrk Student", "NSF-WRK-01",
    )
    return calendar_day, workday


def test_calendar_day_and_workday_proration_diverge_on_a_partial_period():
    """The two proration variants pay a partial window differently.

    PRD: "Under `CALENDAR_DAY`, the covered count is the whole days from the
    overlap start up to but excluding the overlap end, and the period count is
    the whole days from `period_start` up to but excluding
    `period_end_exclusive`. Under `WORKDAY`, both counts instead tally only
    Monday-through-Friday dates in those same half-open ranges — which is why a
    weekend-heavy partial window pays a different amount under the two methods
    for otherwise identical inputs." The 2026-10-01 through 2026-10-15 tail of
    the window holds 15 calendar days out of the period's 31, but 11 workdays
    out of the period's 22.

    Design: Difficulty/dual_variant_calc/proration_variant_calendar_day_vs_workday_diverge
    """
    calendar_day, workday = _submit_both_proration_variants()

    assert calendar_day["total_stipend_cents"] == 370968, (
        "CALENDAR_DAY pays 250000 for the whole September period plus "
        "250000 * 15 / 31 rounded half up for the October tail"
    )
    assert workday["total_stipend_cents"] == 375000, (
        "WORKDAY pays 250000 for the whole September period plus "
        "250000 * 11 / 22 for the October tail"
    )
    assert workday["total_stipend_cents"] - calendar_day["total_stipend_cents"] == 4032


def test_proration_variant_does_not_disturb_the_effort_profile():
    """Only the money diverges: the derived effort profile is variant-blind.

    PRD: "The `weekly_hours` field is `effort_pct` divided by 100, multiplied by
    the 40 hours of a full-time week, rounded half up to one decimal place. The
    `duration_days` field is the count of whole days from `start_date` to
    `end_date` counting both endpoints — the difference in days plus one." That
    derivation reads neither the term's `proration_method` nor its calendar, and
    "The appointment's `projected_pay_period_count` is the number of periods not
    skipped" counts the same two periods under either method.

    Design: Difficulty/dual_variant_calc/proration_variant_calendar_day_vs_workday_diverge
    """
    calendar_day, workday = _submit_both_proration_variants()

    for appointment, label in ((calendar_day, "CALENDAR_DAY"),
                               (workday, "WORKDAY")):
        assert appointment["projected_pay_period_count"] == 2, (
            f"{label}: both pay periods intersect the window"
        )
        assert float(appointment["weekly_hours"]) == pytest.approx(30.0, abs=0.01), (
            f"{label}: 75 percent of a 40-hour week is 30.0 hours"
        )
        assert appointment["duration_days"] == 45, (
            f"{label}: 2026-09-01 through 2026-10-15 inclusive is 45 days"
        )
        assert appointment["tuition_remission_cents"] == 0, (
            f"{label}: a student enrolled in 0 credits earns no remission"
        )


# --------------------------------------------------------------------------- #
# Taxation: the same 400000-cent benefit under both assessment variants
# --------------------------------------------------------------------------- #

_TAX_POLICY = {
    "assistantship_type": "RESEARCH",
    "degree_level": "DOCTORAL",
    "min_fte_monthly_stipend_cents": 400000,
    "per_credit_tuition_cents": 50000,
    "max_remission_cents_per_term": 500000,
    "term_insurance_premium_cents": 0,
    "tuition_tax_exempt_cap_cents": 525000,
}


def _build_two_benefit_bearing_terms():
    """A summer term and an autumn term in the same tax year, each conferring
    400000 cents of tuition benefit on one student through an ACTIVE
    appointment."""
    department = make_department(code="BIOL", name="Biology")

    summer = make_term(
        term_code="SUM2026", term_start="2026-05-01", term_end="2026-08-31",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-06-15",
    )
    make_policy(summer["id"], **_TAX_POLICY)
    make_pay_periods(summer["id"], MONTHLY_PERIODS_SUMMER_2026)
    open_term(summer["id"])

    autumn = make_term(
        term_code="AUT2026", term_start="2026-09-01", term_end="2026-12-31",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-11-15",
    )
    make_policy(autumn["id"], **_TAX_POLICY)
    make_pay_periods(autumn["id"], MONTHLY_PERIODS_AUTUMN_2026)
    open_term(autumn["id"])

    student = make_student(
        student_number="GS-TAX-001", full_name="Tax Student",
        degree_level="DOCTORAL", is_international=False,
        cumulative_gpa=3.60, enrolled_credit_hours=8,
    )
    source = make_funding_source(
        department["id"], source_code="NIH-TAX-01", source_type="GRANT",
        authorized_amount_cents=10000000,
        budget_period_start="2026-01-01", budget_period_end="2027-06-30",
        allows_tuition_remission=True,
    )

    for term, start, end in (
        (summer, "2026-05-01", "2026-08-31"),
        (autumn, "2026-09-01", "2026-12-31"),
    ):
        appointment = make_appointment(
            student["id"], department["id"], term["id"],
            assistantship_type="RESEARCH", effort_pct=75,
            start_date=start, end_date=end, monthly_stipend_cents=300000,
        )
        fund_wholly_from(appointment["id"], source["id"])
        drive_appointment(appointment["id"], "ACTIVE")

    return {
        "student_id": student["id"],
        "summer_term_id": summer["id"],
        "autumn_term_id": autumn["id"],
    }


def test_term_provisional_variant_applies_the_cap_to_the_term_in_isolation():
    """A provisional assessment shields the whole term benefit on its own.

    PRD: "Under **`TERM_PROVISIONAL`**, the cap is applied to the term in
    isolation: `exempt_cents` is the smaller of `benefit_cents` and the cap, and
    `taxable_cents` is `benefit_cents` minus `exempt_cents`. Two terms each
    conferring 400000 cents of benefit therefore both report `taxable_cents` of
    0 while provisional, because neither term alone reaches the 525000-cent
    cap."

    Design: Difficulty/dual_variant_calc/tax_variant_term_provisional_vs_calendar_year_final_diverge
    """
    world = _build_two_benefit_bearing_terms()
    build_assessment(world["student_id"], world["summer_term_id"], finalize=True)

    provisional = build_assessment(
        world["student_id"], world["autumn_term_id"], finalize=False
    )

    assert provisional["variant_applied"] == "TERM_PROVISIONAL"
    assert provisional["status"] == "PROVISIONAL"
    assert provisional["benefit_cents"] == 400000
    assert provisional["exempt_cents"] == 400000, (
        "400000 is below the 525000 cap, so the term is exempt in isolation"
    )
    assert provisional["taxable_cents"] == 0
    assert provisional["imputed_withholding_cents"] == 0


def test_calendar_year_final_variant_taxes_the_benefit_past_the_year_remainder():
    """Finalizing the second term consumes only the cap the first term left.

    PRD: "The remaining cap is the larger of zero and the year exemption minus
    the sum of `exempt_cents` over those prior finals. This row's `exempt_cents`
    is then the smaller of its own `benefit_cents` and that remaining cap —
    clamped so it can never exceed the term's own benefit — and `taxable_cents`
    is `benefit_cents` minus `exempt_cents`, and therefore never negative. The
    same pair of 400000-cent terms now reports `taxable_cents` of 275000 on the
    second term once both are final, which is precisely the divergence from the
    provisional variant." PRD: "`imputed_withholding_cents` is `taxable_cents`
    multiplied by an imputed withholding rate of 0.2200 — twenty-two percent —
    rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/tax_variant_term_provisional_vs_calendar_year_final_diverge
    """
    world = _build_two_benefit_bearing_terms()
    summer = build_assessment(
        world["student_id"], world["summer_term_id"], finalize=True
    )

    final = build_assessment(
        world["student_id"], world["autumn_term_id"], finalize=True
    )

    assert final["variant_applied"] == "CALENDAR_YEAR_FINAL"
    assert final["status"] == "FINAL"
    assert final["benefit_cents"] == 400000
    assert final["exempt_cents"] == 125000, (
        "the year exemption of 525000 less the 400000 the summer term already "
        "used leaves 125000"
    )
    assert final["taxable_cents"] == 275000
    assert final["imputed_withholding_cents"] == 60500, "275000 * 0.2200"

    assert summer["benefit_cents"] == 400000
    assert summer["exempt_cents"] == 400000, (
        "the first term to finalize took the whole of its own benefit exempt"
    )
    assert summer["taxable_cents"] == 0


def test_year_to_date_totals_and_the_exempt_sum_respect_the_annual_cap():
    """The student's year-to-date figures and the cap invariant agree.

    PRD: "`tuition_benefit_ytd_cents`, the sum of `benefit_cents` over the
    student's `FINAL` tax assessments in the current `tax_calendar_year`; and
    `taxable_tuition_benefit_ytd_cents`, the corresponding sum of
    `taxable_cents`." PRD: "the sum of `exempt_cents` over a student's `FINAL`
    assessments within one `tax_calendar_year` never exceeds the cap."

    Design: Difficulty/dual_variant_calc/tax_variant_term_provisional_vs_calendar_year_final_diverge
    """
    world = _build_two_benefit_bearing_terms()
    summer = build_assessment(
        world["student_id"], world["summer_term_id"], finalize=True
    )
    autumn = build_assessment(
        world["student_id"], world["autumn_term_id"], finalize=True
    )

    student = read_student(world["student_id"])
    assert student["tuition_benefit_ytd_cents"] == 800000, "400000 from each term"
    assert student["taxable_tuition_benefit_ytd_cents"] == 275000

    summer = read_assessment(summer["id"])
    autumn = read_assessment(autumn["id"])
    assert summer["status"] == "FINAL" and autumn["status"] == "FINAL"
    assert summer["exempt_cents"] + autumn["exempt_cents"] == 525000, (
        "the two finals together consume the annual cap exactly and no more"
    )
