"""Values sitting exactly on a threshold and one step past it.

Housing eligibility turns on a strict comparison at 50 percent, reporting
timeliness turns on a non-strict comparison at 30 days, and the annual tuition
cap is tested at exact equality and at one cent above.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers.fixtures import (
    build_certified_certification,
    build_draft_certification,
    create_certification,
    read_certification,
    set_clock_to,
)
from test_helpers import factories as f

REDUCTION_EFFECTIVE_DATE = "2026-10-15"
THIRTIETH_DAY = "2026-11-14"
THIRTY_FIRST_DAY = "2026-11-15"

SECOND_STUDENT = {
    "student_number": c.SECOND_STUDENT_NUMBER,
    "full_name": c.SECOND_STUDENT_NAME,
    "delimiting_date": c.SECOND_DELIMITING_DATE,
}


# ─── The strict 50 percent housing threshold ──────────────────────────
def test_a_rate_of_pursuit_of_exactly_fifty_earns_no_housing_allowance(api, baseline):
    """Six of twelve credit hours is 50 percent, which is not strictly greater.

    PRD: "`mha_eligible` is true only when the student's `chapter` is `CH33`
    **and** their `rate_of_pursuit_pct` is strictly greater than 50 — the
    comparison is strict, so a student pursuing at exactly 50 percent earns no
    housing allowance at all, whereas one at 51 percent does."

    Design: Difficulty/boundary_precision_check/rate_of_pursuit_exactly_fifty_earns_no_housing_allowance
    """
    scenario = build_draft_certification(
        api, baseline, certification_overrides={"credit_hours_total": 6}
    )

    certification = read_certification(
        api, baseline.sco_headers, scenario.certification_id
    )
    a.assert_derived_enrollment_block(
        certification,
        certified_days=c.CANONICAL_CERTIFIED_DAYS,
        rate_of_pursuit_pct=50,
        rop_tier_pct=50,
        training_time=c.TRAINING_TIME_HALF,
        modality=c.MODALITY_RESIDENTIAL,
        mha_eligible=False,
        mha_monthly_rate_cents=0,
    )


def test_a_rate_of_pursuit_just_above_fifty_earns_the_half_tier_rate(api, baseline):
    """Six and a half credit hours is 54 percent, which clears the strict threshold.

    PRD: "From the base, `mha_monthly_rate_cents` is obtained by multiplying the
    housing base by the student's `benefit_level_pct` and by `rop_tier_pct`,
    dividing by 10000, and rounding half up — a single rounding applied after
    **both** percentage multiplications, in that pinned order."

    Design: Difficulty/boundary_precision_check/rate_of_pursuit_exactly_fifty_earns_no_housing_allowance
    """
    scenario = build_draft_certification(
        api, baseline, certification_overrides={"credit_hours_total": 6}
    )
    above_id, _version = create_certification(
        api,
        baseline.sco_headers,
        scenario.student_id,
        baseline.term_id,
        baseline.program_id,
        credit_hours_total=6.5,
    )

    certification = read_certification(api, baseline.sco_headers, above_id)
    a.assert_derived_enrollment_block(
        certification,
        certified_days=c.CANONICAL_CERTIFIED_DAYS,
        rate_of_pursuit_pct=54,
        rop_tier_pct=50,
        training_time=c.TRAINING_TIME_HALF,
        modality=c.MODALITY_RESIDENTIAL,
        mha_eligible=True,
        mha_monthly_rate_cents=106850,
    )


# ─── The non-strict 30-day reporting threshold ────────────────────────
def test_a_change_reported_on_the_thirtieth_day_is_still_timely(api, baseline):
    """30 days late is at most 30, so the student carries the overpayment.

    PRD: "The `reporting_status` is `TIMELY` when `days_late` is at most 30 and
    `LATE` otherwise — the comparison is non-strict, so reporting on exactly the
    thirtieth day after the effective date is still timely, and the thirty-first
    day is the first late day."

    Design: Difficulty/boundary_precision_check/change_report_thirtieth_day_is_timely_thirty_first_is_late
    """
    scenario = build_certified_certification(api, baseline)
    set_clock_to(api, THIRTIETH_DAY)

    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.credit_hour_reduction_payload(
                scenario.certification_id,
                REDUCTION_EFFECTIVE_DATE,
                new_credit_hours=7,
                new_credit_hours_online=0,
            ),
            baseline.sco_headers,
        )
    )
    a.assert_whole_days(change_report, "days_late")
    a.assert_fields(
        change_report,
        {
            "reported_on": THIRTIETH_DAY,
            "days_late": 30,
            "reporting_status": c.REPORTING_STATUS_TIMELY,
            "liability_party": c.LIABILITY_STUDENT,
        },
    )


def test_a_change_reported_on_the_thirty_first_day_is_late(api, baseline):
    """31 days late shifts the liability from the veteran to the institution.

    PRD: "From that, `liability_party` is `STUDENT` when the report is `TIMELY`
    and `SCHOOL` when it is `LATE`: an institution that missed the reporting
    deadline owes the resulting overpayment itself rather than passing it to the
    veteran."

    Design: Difficulty/boundary_precision_check/change_report_thirtieth_day_is_timely_thirty_first_is_late
    """
    scenario = build_certified_certification(
        api, baseline, student_overrides=SECOND_STUDENT
    )
    set_clock_to(api, THIRTY_FIRST_DAY)

    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.credit_hour_reduction_payload(
                scenario.certification_id,
                REDUCTION_EFFECTIVE_DATE,
                new_credit_hours=7,
                new_credit_hours_online=0,
            ),
            baseline.sco_headers,
        )
    )
    a.assert_fields(
        change_report,
        {
            "reported_on": THIRTY_FIRST_DAY,
            "days_late": 31,
            "reporting_status": c.REPORTING_STATUS_LATE,
            "liability_party": c.LIABILITY_SCHOOL,
        },
    )


# ─── The annual tuition cap at equality and one cent over ─────────────
def test_a_covered_amount_exactly_at_the_annual_cap_leaves_no_gap(api, baseline):
    """The capped base is the covered amount itself when the two are equal.

    PRD: "Step four takes the smaller of `net_covered_cents` and
    `ay_cap_remaining_before_cents` as the capped base."

    Design: Difficulty/boundary_precision_check/annual_tuition_cap_exact_equality_versus_one_cent_over
    """
    scenario = build_certified_certification(
        api,
        baseline,
        pricing_overrides={
            "gross_tuition_cents": c.ANNUAL_CAP_CENTS,
            "mandatory_fees_cents": 0,
            "tuition_specific_aid_cents": 0,
        },
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_covered_tuition_block(
        certification,
        net_covered_cents=2790000,
        ay_cap_remaining_before_cents=2790000,
        va_tuition_cents=2790000,
        cap_charged_cents=2790000,
        yr_gap_cents=0,
    )


def test_a_covered_amount_one_cent_over_the_cap_leaves_a_one_cent_gap(api, baseline):
    """The single cent above the cap falls straight into the Yellow Ribbon gap.

    PRD: "Step seven sets `yr_gap_cents` to `net_covered_cents` minus
    `va_tuition_cents` — the unmet tuition gap that Yellow Ribbon may later
    match."

    Design: Difficulty/boundary_precision_check/annual_tuition_cap_exact_equality_versus_one_cent_over
    """
    scenario = build_certified_certification(
        api,
        baseline,
        student_overrides=SECOND_STUDENT,
        pricing_overrides={
            "gross_tuition_cents": c.ANNUAL_CAP_CENTS + 1,
            "mandatory_fees_cents": 0,
            "tuition_specific_aid_cents": 0,
        },
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_covered_tuition_block(
        certification,
        net_covered_cents=2790001,
        ay_cap_remaining_before_cents=2790000,
        va_tuition_cents=2790000,
        cap_charged_cents=2790000,
        yr_gap_cents=1,
    )
