"""
Two-variant computations that read the same inputs through different clocks.

Interpretation timeliness carries a calendar figure and a reading-window
coverage figure over the identical pair of instants, and only the coverage
figure decides the service level. Capture sufficiency carries a clamped
retrospective index and an unclamped prospective index over the identical
marking data, and only the retrospective index gates the clinical dimension.
"""

from test_helpers import (
    assert_admission_dimensions,
    assert_capture_value,
    assert_instant_equals,
    assert_ledger,
    assert_turnaround_value,
    factories as f,
    fixtures,
    validate_success,
)
from test_helpers.constants import (
    AUTH_STATE_ACTIVE,
    CLINICAL_ADMITTED,
    EVENT_CLINICAL_SEIZURE,
    REPORT_PRELIM_ISSUED,
    RISK_MODERATE,
    SETTING_INPATIENT,
)
from test_helpers.test_users import COORDINATOR, EPILEPTOLOGIST, as_epileptologist

# The interpretation timeline used by the turnaround tests: acquisition closes at
# 12:00 UTC and the preliminary read lands 22 calendar hours later, of which the
# 08:00-18:00 UTC reading window covers 6 hours on the completion day and 2 on
# the issuance day.
T_STUDY_COMPLETED = "2026-08-04T12:00:00Z"
T_PRELIM_ISSUED = "2026-08-05T10:00:00Z"
PRELIM_AUTHOR_USER_ID = "epi-prelim-1"

# The capture timeline used by the adequacy tests.
T_SEGMENT_CLOSED = "2026-08-03T00:00:00Z"
T_TWO_DAYS_IN = "2026-08-04T00:00:00Z"
ONSET_FIRST = "2026-08-02T06:00:00Z"
ONSET_SECOND = "2026-08-02T12:00:00Z"


def _stay_with_completed_study_and_report(api):
    """An inpatient stay whose 32-channel study completed at 2026-08-04T12:00:00Z."""
    baseline = fixtures.build_acquiring_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=RISK_MODERATE,
        setting=SETTING_INPATIENT,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        max_concurrent_studies=2,
        channel_count=32,
    )
    fixtures.complete_study(api, baseline.study_id, at=T_STUDY_COMPLETED)
    report = fixtures.report_of_study(api, baseline.study_id)
    return baseline, report


def _stay_with_two_adjudicated_seizures(api):
    """An admitted stay banking two clinical-seizure weights against a target of 4."""
    baseline = fixtures.build_acquiring_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=RISK_MODERATE,
        setting=SETTING_INPATIENT,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        max_concurrent_studies=2,
        channel_count=32,
    )
    fixtures.pause_study(api, baseline.study_id, at=T_SEGMENT_CLOSED)
    fixtures.create_marking(
        api,
        baseline.study_id,
        ONSET_FIRST,
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=90,
        adjudicate=True,
    )
    fixtures.create_marking(
        api,
        baseline.study_id,
        ONSET_SECOND,
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=75,
        adjudicate=True,
    )
    fixtures.set_clock(api, T_TWO_DAYS_IN)
    return baseline


def test_prelim_issuance_diverges_calendar_and_coverage_turnaround(api):
    """The same completion-to-issuance interval produces two different turnaround figures.

    PRD §3.8: "The calendar figure on `turnaround_calendar_hours` counts every
    elapsed hour between those two instants, nights and non-reading hours
    included, rounded half up to 2 decimal places."
    PRD §3.8: "The coverage figure on `turnaround_coverage_hours` counts only the
    minutes that fall inside the unit's daily reading window, which runs from
    08:00:00 UTC up to but not including 18:00:00 UTC."

    Design: Difficulty/dual_variant_calc/report_turnaround_calendar_vs_coverage_clock_divergence
    """
    _, report = _stay_with_completed_study_and_report(api)
    fixtures.set_clock(api, T_PRELIM_ISSUED)

    data = validate_success(
        api.issue_prelim(
            report["id"],
            f.issue_prelim_payload("LEFT_TEMPORAL"),
            as_epileptologist(PRELIM_AUTHOR_USER_ID),
        )
    )

    assert data["status"] == REPORT_PRELIM_ISSUED, (
        f"issuing the preliminary interpretation should move status to "
        f"{REPORT_PRELIM_ISSUED}, got {data['status']!r}"
    )
    assert_instant_equals(
        data["prelim_issued_at"], T_PRELIM_ISSUED, "prelim_issued_at"
    )
    # 2026-08-04T12:00:00Z to 2026-08-05T10:00:00Z is 22 elapsed hours.
    assert_turnaround_value(
        data["turnaround_calendar_hours"], 22.00, "turnaround_calendar_hours"
    )
    # Of those 22 hours only 12:00-18:00 on 08-04 and 08:00-10:00 on 08-05 fall
    # inside the reading window: 360 + 120 minutes, i.e. 8 hours.
    assert_turnaround_value(
        data["turnaround_coverage_hours"], 8.00, "turnaround_coverage_hours"
    )
    assert data["turnaround_calendar_hours"] != data["turnaround_coverage_hours"], (
        "the two turnaround variants must diverge across an interval spanning a "
        "night, got both at "
        f"{data['turnaround_calendar_hours']!r}"
    )


def test_prelim_issuance_at_exactly_eight_coverage_hours_is_not_an_sla_breach(api):
    """Only the coverage figure drives the service level, and exactly eight hours passes it.

    PRD §3.8: "`sla_breached` is true if and only if `turnaround_coverage_hours`
    is **strictly greater** than the eight-hour preliminary reading service
    level; a coverage figure of exactly 8 is not a breach."
    PRD §3.8: "On that first issuance the server stamps `prelim_issued_at` from
    the logical clock and `prelim_author_user_id` from the acting `X-User-ID`,
    computes both turnaround figures, and sets `sla_breached`."

    Design: Difficulty/dual_variant_calc/report_turnaround_calendar_vs_coverage_clock_divergence
    """
    _, report = _stay_with_completed_study_and_report(api)
    fixtures.set_clock(api, T_PRELIM_ISSUED)

    validate_success(
        api.issue_prelim(
            report["id"],
            f.issue_prelim_payload("LEFT_TEMPORAL"),
            as_epileptologist(PRELIM_AUTHOR_USER_ID),
        )
    )
    stored = validate_success(api.get_report(report["id"], EPILEPTOLOGIST))

    assert_turnaround_value(
        stored["turnaround_coverage_hours"], 8.00, "turnaround_coverage_hours"
    )
    assert stored["sla_breached"] is False, (
        "a coverage figure of exactly 8 hours is not strictly greater than the "
        "eight-hour service level, so sla_breached should be false, got "
        f"{stored['sla_breached']!r}"
    )
    assert stored["prelim_author_user_id"] == PRELIM_AUTHOR_USER_ID, (
        "prelim_author_user_id should be stamped from the acting X-User-ID "
        f"{PRELIM_AUTHOR_USER_ID!r}, got {stored['prelim_author_user_id']!r}"
    )
    assert_turnaround_value(
        stored["turnaround_calendar_hours"], 22.00, "turnaround_calendar_hours"
    )


def test_capture_summary_separates_clamped_retrospective_from_unclamped_prospective(api):
    """Identical adjudicated-marking data yields a clamped 0.500 and an unclamped 1.250.

    PRD §3.7: "The retrospective figure stored on `capture_adequacy_index` is the
    lesser of 1.000 and `weighted_event_count` divided by `target_event_count`,
    rounded half up to 3 decimal places; it counts only weight already banked by
    adjudicated markings, it is clamped at 1.000, and it is **the only figure the
    `ADMITTED` to `CAPTURE_TARGET_MET` transition reads** — the transition fires
    when it reaches 1.000 or more, and the reverse transition fires when it falls
    below 1.000."
    PRD §3.7: "The prospective figure stored on
    `capture_adequacy_index_prospective` is `weighted_event_count` plus the
    product of `projected_daily_yield` and the authorization's `days_available`,
    all divided by `target_event_count`, rounded half up to 3 decimal places; it
    adds the yield still expected from the authorized days that remain, it is
    **not** clamped, so it may exceed 1.000, and it is advisory only — it is
    shown to the epileptologist weighing length of stay and never gates a
    transition."

    Design: Difficulty/dual_variant_calc/admission_capture_adequacy_retrospective_vs_prospective_divergence
    """
    baseline = _stay_with_two_adjudicated_seizures(api)

    summary = validate_success(
        api.get_capture_summary(baseline.admission_id, EPILEPTOLOGIST)
    )

    # 2.000 banked weight against a target of 4 clamps to 0.500.
    assert_capture_value(
        summary["adequacy_retrospective"], 0.500, "adequacy_retrospective"
    )
    # (2.000 + 1.000 * 3 remaining authorized days) / 4 = 1.250, unclamped.
    assert_capture_value(
        summary["adequacy_prospective"], 1.250, "adequacy_prospective"
    )
    assert summary["adequacy_prospective"] > summary["adequacy_retrospective"], (
        "with days_available and projected_daily_yield both above zero the "
        "prospective figure must be strictly larger than the retrospective one, "
        f"got {summary['adequacy_prospective']!r} against "
        f"{summary['adequacy_retrospective']!r}"
    )


def test_capture_summary_inputs_leave_admission_admitted_under_the_retrospective_gate(api):
    """The shared inputs behind both variants, and the clinical dimension the clamp holds back.

    PRD §3.7: "From that set: `weighted_event_count` is the sum of the members'
    `weight` values, rounded half up to 3 decimal places."
    PRD §3.7: "`projected_daily_yield` is 0 when `elapsed_monitored_days` is 0,
    and otherwise `weighted_event_count` divided by `elapsed_monitored_days`, to
    3 decimal places."
    PRD §3.7: "`deficit_weighted` is the greater of zero and the admission's
    `target_event_count` minus `weighted_event_count`, to 3 decimal places."
    PRD §3.3: "Admissions can be listed with filters on `patient_id`,
    `authorization_id`, `unit_id`, `bed_id`, `clinical_state` and
    `authorization_state`, and a dedicated computed read exposes the two
    capture-adequacy variants side by side for the length-of-stay conversation,
    returning `adequacy_retrospective`, `adequacy_prospective`,
    `weighted_event_count`, `projected_daily_yield`, `deficit_weighted` and
    `elapsed_monitored_days` in one object."

    Design: Difficulty/dual_variant_calc/admission_capture_adequacy_retrospective_vs_prospective_divergence
    """
    baseline = _stay_with_two_adjudicated_seizures(api)

    summary = validate_success(
        api.get_capture_summary(baseline.admission_id, EPILEPTOLOGIST)
    )

    # Two undiscounted CLINICAL_SEIZURE weights of 1.0 each.
    assert_capture_value(
        summary["weighted_event_count"], 2.000, "weighted_event_count"
    )
    # 2026-08-02T00:00:00Z to 2026-08-04T00:00:00Z is two whole days.
    assert_capture_value(
        summary["elapsed_monitored_days"], 2.000, "elapsed_monitored_days"
    )
    assert_capture_value(
        summary["projected_daily_yield"], 1.000, "projected_daily_yield"
    )
    assert_capture_value(summary["deficit_weighted"], 2.000, "deficit_weighted")

    admission = validate_success(
        api.get_admission(baseline.admission_id, COORDINATOR)
    )
    # The prospective figure has passed 1.000 but only the retrospective figure
    # gates the transition, and that stands at 0.500.
    assert_admission_dimensions(admission, CLINICAL_ADMITTED, AUTH_STATE_ACTIVE)

    authorization = validate_success(
        api.get_authorization(baseline.authorization_id, COORDINATOR)
    )
    assert_ledger(
        authorization,
        authorized_days=5,
        days_reserved=2,
        days_consumed=0,
        days_available=3,
    )
