"""The derivations that only show themselves on off-canonical inputs.

A three-quarter load whose tier rounds up past its own rate, a wholly online term
priced from the national rate, a covered amount taken from the report in force
alone, a change filed ahead of its effective date, the inclusive edges of the
protection window, and the inclusive edges of the certified period.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    certify_certification,
    create_certification,
    create_student,
    create_verified_student,
    price_certification,
    read_certification,
    read_student,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import BURSAR_HEADERS

THREE_QUARTER_CREDIT_HOURS = 9
THREE_QUARTER_RATE_PCT = 75
THREE_QUARTER_TIER_PCT = 80
THREE_QUARTER_MONTHLY_RATE_CENTS = 170960
THREE_QUARTER_TERM_TOTAL_CENTS = 621154
THREE_QUARTER_DAYS_CHARGED = 88

ONLINE_TERM_TOTAL_CENTS = 362061

CORRECTED_GROSS_CENTS = 3200000
UNRESTRICTED_AID_CENTS = 500000
CORRECTED_NET_COVERED_CENTS = 3150000
SUBTRACTING_UNRESTRICTED_AID_WOULD_GIVE_CENTS = 2650000

CHANGE_REPORTED_ON = "2026-09-05"
CHANGE_EFFECTIVE_DATE = "2026-10-15"
EXPECTED_DAYS_LATE = -40

LAST_PROTECTED_DAY = "2026-10-30"
FIRST_UNPROTECTED_DAY = "2026-10-31"

LATE_START = "2026-10-16"
LATE_START_DAYS = 57
SINGLE_DAY = "2026-08-24"


# ─── A three-quarter load ─────────────────────────────────────────────
def _three_quarter_certification(api, baseline):
    """A certified term carrying 9 of the program's 12 full-time credit hours."""
    return build_certified_certification(
        api,
        baseline,
        certification_overrides={"credit_hours_total": THREE_QUARTER_CREDIT_HOURS},
    )


def test_nine_of_twelve_credits_rounds_its_tier_up_past_its_own_rate(api, baseline):
    """A rate of 75 percent rounds to a tier of 80, not down to 70.

    PRD: "From that figure `rop_tier_pct` is derived by rounding the rate of
    pursuit half up to the nearest multiple of ten and then capping the outcome at
    100, so a rate of pursuit of 115 percent still yields a tier of 100."

    Design: Corner/calculations/three_quarter_time_enrollment_scales_the_housing_rate_and_the_entitlement_charge
    """
    scenario = _three_quarter_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "credit_hours_total": THREE_QUARTER_CREDIT_HOURS,
            "rate_of_pursuit_pct": THREE_QUARTER_RATE_PCT,
            "rop_tier_pct": THREE_QUARTER_TIER_PCT,
        },
    )


def test_the_training_time_band_is_read_off_the_unrounded_rate(api, baseline):
    """At a rate of exactly 75 the band is THREE_QUARTER even though the tier is 80.

    PRD: "It is `FULL_TIME` when `rate_of_pursuit_pct` is at least 100; otherwise
    `THREE_QUARTER` when it is at least 75; otherwise `HALF_TIME` when it is at
    least 50; otherwise `QUARTER_TIME` when it is at least 25; and otherwise
    `LESS_THAN_QUARTER`."

    Design: Corner/calculations/three_quarter_time_enrollment_scales_the_housing_rate_and_the_entitlement_charge
    """
    scenario = _three_quarter_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert certification["training_time"] == c.TRAINING_TIME_THREE_QUARTER


def test_the_tier_and_the_benefit_level_scale_the_monthly_housing_rate(api, baseline):
    """213700 at 100 percent benefit and an 80 percent tier gives 170960.

    PRD: "From the base, `mha_monthly_rate_cents` is obtained by multiplying the
    housing base by the student's `benefit_level_pct` and by `rop_tier_pct`,
    dividing by 10000, and rounding half up — a single rounding applied after
    **both** percentage multiplications, in that pinned order."

    Design: Corner/calculations/three_quarter_time_enrollment_scales_the_housing_rate_and_the_entitlement_charge
    """
    scenario = _three_quarter_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_integer_cents(certification, "mha_monthly_rate_cents")
    a.assert_fields(
        certification,
        {
            "mha_eligible": True,
            "mha_monthly_rate_cents": THREE_QUARTER_MONTHLY_RATE_CENTS,
        },
    )


def test_the_three_quarter_terms_segments_are_rounded_before_they_are_summed(
    api, baseline
):
    """The five segments of the fall term total 621154 cents at the reduced rate.

    PRD: "Each segment's amount is then the monthly rate multiplied by that
    segment's billable days, divided by 30, and **rounded half up at the segment
    level**."

    Design: Corner/calculations/three_quarter_time_enrollment_scales_the_housing_rate_and_the_entitlement_charge
    """
    scenario = _three_quarter_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_integer_cents(certification, "mha_term_total_cents")
    assert certification["mha_term_total_cents"] == THREE_QUARTER_TERM_TOTAL_CENTS


def test_the_entitlement_charge_uses_the_tier_rather_than_the_raw_rate(api, baseline):
    """110 days at tier 80 charges 88 whole days, not 82 or 110.

    PRD: "At certification, `entitlement_days_charged` is a single rounding over
    the whole inclusive period at a single tier: multiply `certified_days` by
    `rop_tier_pct`, divide by 100, and round half up."

    Design: Corner/calculations/three_quarter_time_enrollment_scales_the_housing_rate_and_the_entitlement_charge
    """
    scenario = _three_quarter_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_whole_days(certification, "entitlement_days_charged")
    a.assert_fields(
        certification,
        {
            "certified_days": c.CANONICAL_CERTIFIED_DAYS,
            "entitlement_days_charged": THREE_QUARTER_DAYS_CHARGED,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_entitlement_ledger_balances(student, THREE_QUARTER_DAYS_CHARGED)


# ─── A wholly online load ─────────────────────────────────────────────
def _online_certification(api, baseline):
    """A certified full-time term delivered entirely online."""
    return build_certified_certification(
        api,
        baseline,
        certification_overrides={"credit_hours_online": c.FULL_TIME_CREDIT_HOURS},
    )


def test_a_load_delivered_wholly_online_reads_as_online_only(api, baseline):
    """The online portion equalling the total is what selects the band.

    PRD: "The `modality` band is read off the credit split: it is `ONLINE_ONLY`
    when `credit_hours_online` equals `credit_hours_total`, otherwise
    `RESIDENTIAL` when `credit_hours_online` is exactly 0, and otherwise `MIXED`."

    Design: Corner/calculations/an_online_only_certification_uses_the_national_online_rate_not_the_campus_rate
    """
    scenario = _online_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "credit_hours_total": c.FULL_TIME_CREDIT_HOURS,
            "credit_hours_online": c.FULL_TIME_CREDIT_HOURS,
            "modality": c.MODALITY_ONLINE_ONLY,
        },
    )


def test_the_national_online_rate_replaces_the_campus_rate(api, baseline):
    """99650 cents is used where the campus rate would have been 213700.

    PRD: "When it is true and the `modality` is `ONLINE_ONLY`, the housing base is
    the nationally set online rate of 99650 cents per month, which is $996.50 and
    takes no account of where the campus is."

    Design: Corner/calculations/an_online_only_certification_uses_the_national_online_rate_not_the_campus_rate
    """
    scenario = _online_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "mha_eligible": True,
            "rate_of_pursuit_pct": 100,
            "rop_tier_pct": 100,
            "mha_monthly_rate_cents": c.ONLINE_MHA_MONTHLY_CENTS,
        },
    )
    assert certification["mha_monthly_rate_cents"] != c.CAMPUS_BAH_MONTHLY_CENTS


def test_the_online_terms_housing_total_follows_the_online_rate(api, baseline):
    """The same 110-day term totals 362061 rather than 776444.

    PRD: "Only after every segment has been rounded are the segment amounts summed
    into `mha_term_total_cents`."

    Design: Corner/calculations/an_online_only_certification_uses_the_national_online_rate_not_the_campus_rate
    """
    scenario = _online_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_integer_cents(certification, "mha_term_total_cents")
    assert certification["mha_term_total_cents"] == ONLINE_TERM_TOTAL_CENTS


# ─── Which report and which aid feed the covered amount ───────────────
def _certified_after_a_reprice(api, baseline):
    """A certification priced twice, then submitted and certified on the later price."""
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    first_report_id, second_version = price_certification(
        api, certification_id, version
    )
    second_report = get_success_data(
        api.create_tuition_fee_report(
            f.tuition_fee_report_payload(
                certification_id,
                second_version,
                gross_tuition_cents=CORRECTED_GROSS_CENTS,
                non_tuition_aid_cents=UNRESTRICTED_AID_CENTS,
            ),
            BURSAR_HEADERS,
        ),
        expected_status=201,
    )
    submit_certification(api, baseline.sco_headers, certification_id)
    certify_certification(api, baseline.sup_headers, certification_id)
    return certification_id, first_report_id, second_report


def test_the_covered_amount_is_taken_from_the_report_in_force(api, baseline):
    """The superseded report's 2950000 is out of the input set.

    PRD: "Step one takes the covered amount straight from the tuition and fee
    report in force — add its `gross_tuition_cents` and `mandatory_fees_cents`,
    subtract its `tuition_specific_aid_cents`, floor at 0 — and stores it as the
    certification's `net_covered_cents`."

    Design: Corner/calculations/only_the_reported_tuition_report_and_only_tuition_specific_aid_feed_the_covered_amount
    """
    certification_id, first_report_id, second_report = _certified_after_a_reprice(
        api, baseline
    )

    certification = read_certification(api, baseline.sup_headers, certification_id)
    assert certification["net_covered_cents"] == CORRECTED_NET_COVERED_CENTS
    assert certification["net_covered_cents"] != c.CANONICAL_NET_COVERED_CENTS

    first_report = get_success_data(
        api.get_tuition_fee_report(first_report_id, BURSAR_HEADERS)
    )
    assert first_report["status"] == c.TUITION_REPORT_STATUS_SUPERSEDED
    assert second_report["status"] == c.TUITION_REPORT_STATUS_REPORTED


def test_unrestricted_aid_is_stored_but_never_subtracted(api, baseline):
    """500000 cents of unrestricted aid leaves the covered amount alone.

    PRD: "The exclusion of `non_tuition_aid_cents` is deliberate and load-bearing:
    aid that the donor did not restrict to tuition and fees does not reduce the
    portion VA covers, and it must not be subtracted here even though it is
    collected and stored."

    Design: Corner/calculations/only_the_reported_tuition_report_and_only_tuition_specific_aid_feed_the_covered_amount
    """
    certification_id, _first_id, second_report = _certified_after_a_reprice(
        api, baseline
    )

    a.assert_fields(
        second_report,
        {
            "non_tuition_aid_cents": UNRESTRICTED_AID_CENTS,
            "net_covered_cents": CORRECTED_NET_COVERED_CENTS,
        },
    )
    certification = read_certification(api, baseline.sup_headers, certification_id)
    assert (
        certification["net_covered_cents"]
        != SUBTRACTING_UNRESTRICTED_AID_WOULD_GIVE_CENTS
    )


# ─── A change filed ahead of its effective date ───────────────────────
def _change_filed_forty_days_early(api, baseline):
    """A credit-hour reduction filed on 2026-09-05 to take effect on 2026-10-15."""
    scenario = build_certified_certification(api, baseline)
    set_clock_to(api, CHANGE_REPORTED_ON)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.credit_hour_reduction_payload(
                scenario.certification_id, CHANGE_EFFECTIVE_DATE, 9
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    return scenario, change_report


def test_a_change_filed_ahead_of_its_effective_date_stores_a_negative_lateness(
    api, baseline
):
    """Forty days of advance notice is stored as -40 rather than clamped to 0.

    PRD: "`days_late` is the whole number of days from `effective_date` to
    `reported_on`, which is negative when the change is reported in advance of
    taking effect."

    Design: Corner/calculations/a_change_reported_before_its_effective_date_yields_negative_days_late
    """
    _scenario, change_report = _change_filed_forty_days_early(api, baseline)

    a.assert_whole_days(change_report, "days_late")
    a.assert_fields(
        change_report,
        {
            "reported_on": CHANGE_REPORTED_ON,
            "effective_date": CHANGE_EFFECTIVE_DATE,
            "days_late": EXPECTED_DAYS_LATE,
        },
    )


def test_a_negative_lateness_satisfies_the_non_strict_timeliness_test(api, baseline):
    """-40 is at most 30, so the report is timely.

    PRD: "The `reporting_status` is `TIMELY` when `days_late` is at most 30 and
    `LATE` otherwise — the comparison is non-strict, so reporting on exactly the
    thirtieth day after the effective date is still timely, and the thirty-first
    day is the first late day."

    Design: Corner/calculations/a_change_reported_before_its_effective_date_yields_negative_days_late
    """
    _scenario, change_report = _change_filed_forty_days_early(api, baseline)

    assert change_report["reporting_status"] == c.REPORTING_STATUS_TIMELY


def test_a_timely_report_leaves_the_liability_with_the_student(api, baseline):
    """Both fields flip together, so a timely filing keeps the student liable.

    PRD: "From that, `liability_party` is `STUDENT` when the report is `TIMELY` and
    `SCHOOL` when it is `LATE`: an institution that missed the reporting deadline
    owes the resulting overpayment itself rather than passing it to the veteran."

    Design: Corner/calculations/a_change_reported_before_its_effective_date_yields_negative_days_late
    """
    _scenario, change_report = _change_filed_forty_days_early(api, baseline)

    assert change_report["liability_party"] == c.LIABILITY_STUDENT


# ─── The edges of the protection window ───────────────────────────────
def test_the_protection_window_still_covers_its_last_day(api, baseline):
    """On 2026-10-30 the clock is on the boundary day and the student is protected.

    PRD: "The service reduces that statute to a three-part predicate that must all
    hold at once for a student to count as protected: their `coe_status` is
    `VERIFIED`; the current logical clock date is on or before their
    `protected_until`, with the boundary day itself still inside the window; and at
    least one enrollment certification exists for that student whose `status` is
    `CERTIFIED` or `AMENDMENT_PENDING` and whose `tuition_payment_posted_on` is
    still null."

    Design: Corner/calculations/the_ninety_day_penalty_shield_covers_its_last_day_and_lapses_the_next
    """
    scenario = build_certified_certification(api, baseline)
    set_clock_to(api, LAST_PROTECTED_DAY)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {
            "protected_until": LAST_PROTECTED_DAY,
            "benefit_payment_protected": True,
        },
    )
    assert (
        read_certification(api, baseline.sup_headers, scenario.certification_id)[
            "tuition_payment_posted_on"
        ]
        is None
    )


def test_the_protection_lapses_the_day_after_the_window(api, baseline):
    """Advancing the clock one further day rewrites the snapshot to false.

    PRD: "Accordingly, every operation capable of changing any of the three
    conjuncts rewrites the snapshot for the affected student or students: verifying
    a certificate, expiring a certificate, certifying an enrollment, recording VA's
    disbursement against a certification, and advancing the logical clock — the
    last of which rewrites it for every student in the system, since the clock's
    movement can push any of them past their `protected_until`."

    Design: Corner/calculations/the_ninety_day_penalty_shield_covers_its_last_day_and_lapses_the_next
    """
    scenario = build_certified_certification(api, baseline)
    set_clock_to(api, LAST_PROTECTED_DAY)
    set_clock_to(api, FIRST_UNPROTECTED_DAY)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {
            "protected_until": LAST_PROTECTED_DAY,
            "benefit_payment_protected": False,
        },
    )


# ─── The edges of the certified period ────────────────────────────────
def _three_periods_for_one_student(api, baseline):
    """One student with three draft certifications of very different lengths."""
    student_id = create_student(api, baseline.sco_headers)
    periods = {
        "full": (c.TERM_START, c.TERM_END),
        "late": (LATE_START, c.TERM_END),
        "one_day": (SINGLE_DAY, SINGLE_DAY),
    }
    drafts = {}
    for label, (start, end) in periods.items():
        certification_id, _version = create_certification(
            api,
            baseline.sco_headers,
            student_id,
            baseline.term_id,
            baseline.program_id,
            term_start_certified=start,
            term_end_certified=end,
        )
        drafts[label] = certification_id
    return student_id, drafts


@pytest.mark.parametrize(
    "label,expected_days",
    [
        ("full", c.CANONICAL_CERTIFIED_DAYS),
        ("late", LATE_START_DAYS),
        ("one_day", 1),
    ],
)
def test_the_certified_day_count_includes_both_endpoints(
    api, baseline, label, expected_days
):
    """A period whose start and end fall on the same day counts as one day.

    PRD: "First, `certified_days` is the inclusive count of days in the certified
    period: the whole number of days from `term_start_certified` to
    `term_end_certified`, plus one, so that a period whose start and end fall on
    the same day counts as one day."

    Design: Corner/calculations/certified_days_counts_both_endpoints_of_the_certified_period
    """
    _student_id, drafts = _three_periods_for_one_student(api, baseline)

    certification = read_certification(api, baseline.sco_headers, drafts[label])
    a.assert_whole_days(certification, "certified_days")
    assert certification["certified_days"] == expected_days


def test_only_the_day_count_differs_across_the_three_periods(api, baseline):
    """The credit load is identical, so the rate of pursuit is identical.

    PRD: "Next, `rate_of_pursuit_pct` expresses the load as an integer percentage
    of the program's own definition of full time — take `credit_hours_total`,
    multiply by 100, divide by the program's `full_time_credit_hours`, and round
    the result half up to a whole percent."

    Design: Corner/calculations/certified_days_counts_both_endpoints_of_the_certified_period
    """
    _student_id, drafts = _three_periods_for_one_student(api, baseline)

    for certification_id in drafts.values():
        certification = read_certification(
            api, baseline.sco_headers, certification_id
        )
        a.assert_fields(
            certification,
            {
                "rate_of_pursuit_pct": 100,
                "rop_tier_pct": 100,
                "training_time": c.TRAINING_TIME_FULL,
                "mha_monthly_rate_cents": c.CAMPUS_BAH_MONTHLY_CENTS,
            },
        )


def test_three_drafts_charge_no_entitlement_at_all(api, baseline):
    """The ledger is only debited when a certification is certified.

    PRD: "That figure is what the seventh precondition above tests against
    `entitlement_days_remaining`, and once the certification succeeds the student's
    `entitlement_days_remaining` is debited by exactly it, leaving remaining
    entitlement equal to granted entitlement minus everything currently charged."

    Design: Corner/calculations/certified_days_counts_both_endpoints_of_the_certified_period
    """
    student_id, _drafts = _three_periods_for_one_student(api, baseline)

    student = read_student(api, baseline.sco_headers, student_id)
    a.assert_entitlement_ledger_balances(student, 0)
    assert student["entitlement_days_remaining"] == c.ENTITLEMENT_DAYS_GRANTED
