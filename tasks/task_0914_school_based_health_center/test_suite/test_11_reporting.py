"""The aggregate report snapshot: empty-period behaviour, the two referral
closure-rate variants and the period-ordering guard."""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_rate_precision,
    assert_report,
    assert_same_date,
    close_referral,
    create_school,
    get_referral,
    log_outreach,
    raise_referral,
    report_back,
    set_clock,
    setup_enrolled_student,
    validate_error,
    validate_success,
)


def test_empty_period_returns_exactly_zero_for_both_closure_rate_variants(api):
    """PRD §2.8: "Referral closure rates in aggregate reports are carried to exactly
    4 decimal places, rounded half-up, and an empty denominator yields exactly
    0.0000 rather than an error or a null."
    PRD §3.12: "Both are rounded half-up to 4 decimal places, and both yield exactly
    0.0000 when their denominator is 0 rather than raising an error."

    Design: Difficulty/boundary_precision_check/report_rates_return_zero_on_empty_referral_and_visit_sets
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()

    resp = api.create_report(
        {
            "period_start_date": "2026-04-01",
            "period_end_date": "2026-04-30",
            "school_id": school["id"],
        },
        ADMIN,
    )
    report = validate_success(resp, 201)

    assert_report(report)
    assert report["referral_total_count"] == 0
    assert report["referral_closed_count"] == 0
    assert report["referral_lost_count"] == 0
    assert float(report["referral_closure_rate_all"]) == pytest.approx(0.0, abs=1e-9)
    assert float(report["referral_closure_rate_excluding_lost"]) == pytest.approx(0.0, abs=1e-9)
    assert_rate_precision(report["referral_closure_rate_all"])
    assert_rate_precision(report["referral_closure_rate_excluding_lost"])


def test_empty_period_returns_zero_visit_counts_and_zero_money_buckets(api):
    """PRD §3.12: "`total_visits` is the size of that set, and
    `scheduled_visit_count`, `in_progress_visit_count`, `completed_visit_count`,
    `cancelled_visit_count` and `no_show_visit_count` count the members in each
    clinical state. The five counts sum to `total_visits` exactly."
    PRD §3.12: "`gross_charge_total_cents`, `no_charge_total_cents`,
    `patient_responsibility_total_cents`, `write_off_total_cents` and
    `payer_billed_total_cents` on the report are the sums of the identically-named
    buckets on those encounters"

    Design: Difficulty/boundary_precision_check/report_rates_return_zero_on_empty_referral_and_visit_sets
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()

    report = validate_success(
        api.create_report(
            {
                "period_start_date": "2026-04-01",
                "period_end_date": "2026-04-30",
                "school_id": school["id"],
            },
            ADMIN,
        ),
        201,
    )

    assert report["total_visits"] == 0
    assert report["scheduled_visit_count"] == 0
    assert report["in_progress_visit_count"] == 0
    assert report["completed_visit_count"] == 0
    assert report["cancelled_visit_count"] == 0
    assert report["no_show_visit_count"] == 0
    assert report["gross_charge_total_cents"] == 0
    assert report["patient_responsibility_total_cents"] == 0
    assert report["payer_billed_total_cents"] == 0
    assert report["write_off_total_cents"] == 0
    assert report["no_charge_total_cents"] == 0


def test_the_two_closure_rate_variants_diverge_over_the_same_period(api):
    """PRD §3.12: "The first rate, `referral_closure_rate_all`, divides the closed
    count by the total count and keeps lost-to-follow-up referrals in the
    denominator. The second, `referral_closure_rate_excluding_lost`, divides the
    closed count by the total count less the lost count."
    PRD §3.12: "Two closed referrals out of four created, one of which was lost,
    therefore reports 0.5000 on the first rate and 0.6667 on the second."

    Design: Corner/calculations/referral_closure_rate_variants_diverge_over_the_same_period
    """
    ctx = setup_enrolled_student(consents=())
    student_id = ctx["student"]["id"]
    clinician_id = ctx["clinician"]["id"]

    closed_ids = []
    for specialty, reason, summary in (
        ("PRIMARY_CARE", "Referral one", "Seen and treated"),
        ("DENTISTRY", "Referral two", "Restoration completed"),
    ):
        referral = raise_referral(student_id, clinician_id, specialty=specialty, reason=reason)
        log_outreach(referral["id"], "REACHED")
        report_back(referral["id"], summary, "2026-05-04")
        close_referral(referral["id"], "Loop closed")
        closed_ids.append(referral["id"])

    lost = raise_referral(
        student_id, clinician_id, specialty="AUDIOLOGY", reason="Referral three"
    )
    for _ in range(3):
        log_outreach(lost["id"], "NO_ANSWER")

    still_open = raise_referral(
        student_id, clinician_id, specialty="NUTRITION", reason="Referral four"
    )

    for referral_id in closed_ids:
        assert get_referral(referral_id)["status"] == "CLOSED"
    assert get_referral(lost["id"])["status"] == "LOST_TO_FOLLOW_UP"
    assert get_referral(still_open["id"])["status"] == "OPEN"

    report = validate_success(
        api.create_report(
            {
                "period_start_date": "2026-05-01",
                "period_end_date": "2026-05-31",
                "school_id": ctx["school"]["id"],
            },
            ADMIN,
        ),
        201,
    )

    assert report["referral_total_count"] == 4
    assert report["referral_closed_count"] == 2
    assert report["referral_lost_count"] == 1
    assert float(report["referral_closure_rate_all"]) == pytest.approx(0.5000, abs=1e-9)
    assert float(report["referral_closure_rate_excluding_lost"]) == pytest.approx(
        0.6667, abs=1e-9
    )
    assert_rate_precision(report["referral_closure_rate_all"])
    assert_rate_precision(report["referral_closure_rate_excluding_lost"])


def test_inverted_period_is_refused_while_a_single_day_period_is_accepted(api):
    """PRD §2.6 rung 8: "`period_end_date` is the same as or later than
    `period_start_date` — equal dates describe a legitimate single-day period — on
    `POST /sbhc/reports`. Otherwise `ERR_INVALID_REPORT_PERIOD` (400)."
    PRD §3.12: "The end date must be the same as or later than the start date,
    otherwise `ERR_INVALID_REPORT_PERIOD` — equal dates describe a legitimate
    one-day period."

    Design: Corner/validations/report_period_end_before_start_returns_invalid_report_period
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()

    inverted = api.create_report(
        {
            "period_start_date": "2026-04-30",
            "period_end_date": "2026-04-01",
            "school_id": school["id"],
        },
        ADMIN,
    )
    validate_error(inverted, ApiErrorId.ERR_INVALID_REPORT_PERIOD.value, 400)

    single_day = validate_success(
        api.create_report(
            {
                "period_start_date": "2026-04-15",
                "period_end_date": "2026-04-15",
                "school_id": school["id"],
            },
            ADMIN,
        ),
        201,
    )

    assert_same_date(single_day["period_start_date"], "2026-04-15", "period_start_date")
    assert_same_date(single_day["period_end_date"], "2026-04-15", "period_end_date")
    assert single_day["total_visits"] == 0
