"""
Multi-input formulas whose result depends on the order the terms are applied.

Study storage accumulates through a pinned round-per-segment-then-re-round
order. The alert response deadline folds four independent terms through a nested
clamp. The length-of-stay decision resolves an apparent circularity by pinning
seven evaluation steps against the state as it stood before the call.
"""

from test_helpers import (
    assert_admission_dimensions,
    assert_alert_dimensions,
    assert_capture_value,
    assert_instant_equals,
    assert_ledger,
    assert_storage_value,
    assert_study_dimensions,
    assert_unit_storage,
    assert_whole_minutes,
    factories as f,
    fixtures,
    validate_success,
)
from test_helpers.constants import (
    ACQ_COMPLETED,
    ALERT_SOURCE_ALGORITHM,
    AUTH_STATE_ACTIVE,
    CLINICAL_ADMITTED,
    DATA_ONLINE,
    EVENT_CLINICAL_SEIZURE,
    EXTENSION_GRANTED,
    INTERVENTION_POSITIONING,
    INTERVENTION_SEIZURE_TESTING,
    INTERVENTION_VITALS,
    POSTURE_OPEN,
    RESPONSE_AWAITING,
    RESPONSE_ON_TIME,
    RISK_MODERATE,
    SETTING_INPATIENT,
    TRIAGE_DETECTED,
)
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    NURSE,
    TECHNOLOGIST,
    as_epileptologist,
)

# Two closed segments of 1538 and 1243 whole minutes.
T_SEGMENT_1_START = "2026-08-03T08:00:00Z"
T_SEGMENT_1_END = "2026-08-04T09:38:00Z"
T_SEGMENT_2_START = "2026-08-04T10:21:00Z"
T_SEGMENT_2_END = "2026-08-05T07:04:00Z"
SEGMENT_1_MINUTES = 1538
SEGMENT_2_MINUTES = 1243

# The alert-deadline timeline: a daytime detection and a bedside response landing
# on exactly the deadline.
T_ALERT_DETECTED = "2026-08-03T14:00:00Z"
T_ALERT_RESPONDED = "2026-08-03T14:06:00Z"

# The length-of-stay timeline.
T_SEGMENT_CLOSED = "2026-08-03T00:00:00Z"
T_DECISION = "2026-08-04T00:00:00Z"
ONSET_FIRST = "2026-08-02T06:00:00Z"
ONSET_SECOND = "2026-08-02T12:00:00Z"


def _study_with_two_closed_segments(api):
    """Drive a 32-channel inpatient study through two closed segments to completion."""
    baseline = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=RISK_MODERATE,
        setting=SETTING_INPATIENT,
        requested_days=5,
        planned_days=5,
        max_concurrent_studies=2,
        channel_count=32,
    )
    fixtures.start_study(
        api, baseline.study_id, baseline.shift_id, at=T_SEGMENT_1_START
    )
    fixtures.pause_study(
        api, baseline.study_id, at=T_SEGMENT_1_END, reason="ELECTRODE_CHECK"
    )
    fixtures.resume_study(api, baseline.study_id, at=T_SEGMENT_2_START)
    study = fixtures.complete_study(api, baseline.study_id, at=T_SEGMENT_2_END)
    return baseline, study


def _acquiring_stay_with_daytime_alert(api):
    """A MODERATE-risk stay with no taper plan and an alert detected at 14:00 UTC."""
    baseline = fixtures.build_acquiring_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=RISK_MODERATE,
        setting=SETTING_INPATIENT,
        requested_days=5,
        planned_days=5,
        max_concurrent_studies=2,
        channel_count=32,
    )
    fixtures.set_clock(api, T_ALERT_DETECTED)
    alert = validate_success(
        api.raise_alert(
            baseline.study_id, f.alert_payload(ALERT_SOURCE_ALGORITHM), TECHNOLOGIST
        ),
        expected_status=201,
    )
    return baseline, alert


def _stay_ready_for_extension(api):
    """A MODERATE stay at taper step 1 with 2.000 banked weight and 2.000 elapsed days."""
    baseline = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=RISK_MODERATE,
        setting=SETTING_INPATIENT,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        max_concurrent_studies=2,
        channel_count=32,
        with_study=False,
        with_shift=False,
    )
    fixtures.create_taper_plan(api, baseline.admission_id, total_steps=3, steps_advanced=1)
    baseline.shift = fixtures.create_shift(api, baseline.unit_id)
    baseline.study = fixtures.create_study(api, baseline.admission_id, channel_count=32)
    fixtures.start_study(api, baseline.study_id, baseline.shift_id)
    fixtures.pause_study(api, baseline.study_id, at=T_SEGMENT_CLOSED)
    for onset, duration in ((ONSET_FIRST, 90), (ONSET_SECOND, 75)):
        fixtures.create_marking(
            api,
            baseline.study_id,
            onset,
            event_class=EVENT_CLINICAL_SEIZURE,
            duration_seconds=duration,
            adjudicate=True,
        )
    fixtures.set_clock(api, T_DECISION)
    return baseline


def test_stored_gb_rounds_each_segment_before_accumulating(api):
    """Two closed segments accumulate to 89.00 rather than the sum-then-round 88.99.

    PRD §3.5: "For each segment, take its duration truncated down to whole
    minutes, multiply by the per-minute rate, and round that product half up to 2
    decimal places to get that segment's volume; then add the segment volume to
    the running total and round the new running total half up to 2 decimal places
    before moving on."
    PRD §3.5: "Rounding each segment and re-rounding after each accumulation is
    required; summing raw segment volumes and rounding once at the end yields a
    different figure and is wrong."

    Design: Difficulty/combinatorial_formula/study_storage_gb_round_per_segment_then_sum
    """
    _, study = _study_with_two_closed_segments(api)

    assert study["closed_segment_count"] == 2, (
        "two paused-or-completed segments should leave closed_segment_count at 2, "
        f"got {study['closed_segment_count']!r}"
    )
    assert_whole_minutes(
        study["acquired_minutes"],
        SEGMENT_1_MINUTES + SEGMENT_2_MINUTES,
        "acquired_minutes",
    )
    # Per-minute rate 0.0004 * 32 channels * 2.5 inpatient factor = 0.032 GB.
    # 1538 min -> 49.216 -> 49.22; running total 49.22.
    # 1243 min -> 39.776 -> 39.78; running total 89.00.
    assert_storage_value(study["stored_gb"], 89.00, "stored_gb")
    assert abs(float(study["stored_gb"]) - 88.99) > 1e-9, (
        "88.99 is the figure produced by summing raw segment volumes and rounding "
        "once at the end, which the contract rejects"
    )
    assert_study_dimensions(study, ACQ_COMPLETED, DATA_ONLINE)


def test_unit_storage_figure_follows_the_per_segment_accumulation(api):
    """The unit's used volume and pressure inherit the per-segment accumulation exactly.

    PRD §2.11: "Its `storage_used_gb` is recomputed, as a figure rounded half up
    to 2 decimal places, as the sum of `stored_gb` over every study of the unit
    whose `data_state` is `ONLINE` or `EXPORT_HELD`, plus the sum of `package_gb`
    over every export package on those same studies whose `status` is `BUILT` or
    `DELIVERED`."
    PRD §2.11: "From that figure, `storage_pressure_pct` is the used volume
    divided by the unit's `storage_quota_gb`, multiplied by 100, rounded half up
    to 2 decimal places."

    Design: Difficulty/combinatorial_formula/study_storage_gb_round_per_segment_then_sum
    """
    baseline, _ = _study_with_two_closed_segments(api)

    unit = validate_success(api.get_unit(baseline.unit_id, COORDINATOR))

    # The one ONLINE study contributes 89.00; 89.00 / 500.00 * 100 = 17.80.
    assert_unit_storage(
        unit,
        storage_used_gb=89.00,
        storage_pressure_pct=17.80,
        posture=POSTURE_OPEN,
    )


def test_alert_deadline_folds_four_terms_through_the_nested_clamp(api):
    """A MODERATE base with no taper, an OPEN posture and a daytime hour freeze the deadline at 6.

    PRD §3.6: "Start from the base allowance for the patient's `risk_tier`: 10
    minutes for `LOW`, 6 minutes for `MODERATE`, 3 minutes for `HIGH` — the higher
    the clinical risk, the tighter the base."
    PRD §3.6: "Then clamp the sum: take the lesser of the sum and a ceiling of 15
    minutes, and then take the greater of that result and a floor of 2 minutes."

    Design: Difficulty/combinatorial_formula/alert_deadline_four_input_nested_clamp
    """
    baseline, alert = _acquiring_stay_with_daytime_alert(api)

    unit = validate_success(api.get_unit(baseline.unit_id, COORDINATOR))
    assert unit["posture"] == POSTURE_OPEN, (
        "one acquiring study against a coverage capacity of 2 leaves the posture "
        f"OPEN, so no coverage surcharge applies, got {unit['posture']!r}"
    )
    # Base 6 for MODERATE, minus 0 taper steps, plus 0 coverage surcharge, plus 0
    # overnight allowance; max(2, min(15, 6)) = 6.
    assert alert["response_deadline_minutes"] == 6, (
        "response_deadline_minutes should be the clamped whole number 6, got "
        f"{alert['response_deadline_minutes']!r}"
    )
    assert_alert_dimensions(alert, TRIAGE_DETECTED, RESPONSE_AWAITING)
    assert_instant_equals(alert["detected_at"], T_ALERT_DETECTED, "detected_at")
    assert alert["responded_at"] is None, (
        f"responded_at should still be null, got {alert['responded_at']!r}"
    )
    assert alert["latency_minutes"] is None, (
        f"latency_minutes should still be null, got {alert['latency_minutes']!r}"
    )


def test_latency_equal_to_the_deadline_settles_on_time_and_spares_the_unit_counter(api):
    """A latency of exactly the frozen deadline lands on the inclusive on-time side.

    PRD §3.6: "It stamps the alert's `responded_at` from the clock and computes
    `latency_minutes` as the elapsed minutes from `detected_at` to `responded_at`,
    truncated down."
    PRD §3.6: "If that latency is less than or equal to
    `response_deadline_minutes` — equality counts as on time — `response_state`
    moves from `AWAITING_RESPONSE` to `RESPONDED_ON_TIME`."
    PRD §3.6: "If the latency is strictly greater, `response_state` moves to
    `RESPONDED_LATE` and, additionally, the unit's `late_response_count` increases
    by 1."

    Design: Difficulty/combinatorial_formula/alert_deadline_four_input_nested_clamp
    """
    baseline, alert = _acquiring_stay_with_daytime_alert(api)
    fixtures.set_clock(api, T_ALERT_RESPONDED)

    validate_success(
        api.record_intervention(
            alert["id"],
            f.intervention_payload(
                interventions=[
                    INTERVENTION_POSITIONING,
                    INTERVENTION_SEIZURE_TESTING,
                    INTERVENTION_VITALS,
                ],
                injury_observed=False,
                rescue_med_given=False,
            ),
            NURSE,
        ),
        expected_status=201,
    )
    settled = validate_success(api.get_alert(alert["id"], NURSE))

    assert_whole_minutes(settled["latency_minutes"], 6, "latency_minutes")
    assert settled["response_deadline_minutes"] == 6, (
        "the deadline is frozen at detection and must not be recomputed, got "
        f"{settled['response_deadline_minutes']!r}"
    )
    # 6 is not strictly greater than 6, so the response is on time.
    assert_alert_dimensions(settled, TRIAGE_DETECTED, RESPONSE_ON_TIME)
    assert_instant_equals(settled["responded_at"], T_ALERT_RESPONDED, "responded_at")

    unit = validate_success(api.get_unit(baseline.unit_id, COORDINATOR))
    assert unit["late_response_count"] == 0, (
        "an on-time response must leave late_response_count at 0, got "
        f"{unit['late_response_count']!r}"
    )


def test_extension_grants_the_smallest_of_the_three_ceilings(api):
    """Deficit days 2, risk budget 5 and three available days grant exactly 2 days.

    PRD §3.7: "**Step four** computes the days the deficit implies:
    `deficit_weighted` divided by `projected_daily_yield`, rounded **up** to a
    whole number of days, never negative."
    PRD §3.7: "**Step six** turns a per-stay risk allowance of 24 units into a day
    budget: 24 divided by the daily risk figure, rounded **down** to a whole
    number of days."
    PRD §3.7: "**Step seven** grants the smallest of three ceilings — the days the
    deficit implies, the days the risk budget permits, and the authorization's
    `days_available`."

    Design: Difficulty/combinatorial_formula/los_extension_pinned_evaluation_order_s1_s7
    """
    baseline = _stay_ready_for_extension(api)
    admission = validate_success(
        api.get_admission(baseline.admission_id, EPILEPTOLOGIST)
    )
    # The inputs the seven steps read, all as they stand before the call.
    assert_capture_value(
        admission["projected_daily_yield"], 1.000, "projected_daily_yield"
    )
    assert_capture_value(admission["deficit_weighted"], 2.000, "deficit_weighted")

    decided = validate_success(
        api.record_extension_decision(
            baseline.admission_id,
            f.extension_payload(admission["version"]),
            as_epileptologist("epi-los-1"),
        )
    )

    # Deficit days ceil(2.000 / 1.000) = 2; daily risk 3 + 1.5 * 1 taper step =
    # 4.5, so the risk budget is floor(24 / 4.5) = 5; days_available is 3.
    assert decided["last_extension_outcome"] == EXTENSION_GRANTED, (
        f"a positive smallest ceiling is a grant, got "
        f"{decided['last_extension_outcome']!r}"
    )
    assert decided["last_extension_granted_days"] == 2, (
        "the smallest of 2 deficit days, 5 risk-budget days and 3 available days "
        f"is 2, got {decided['last_extension_granted_days']!r}"
    )
    assert decided["extension_count"] == 1, (
        f"extension_count should be 1, got {decided['extension_count']!r}"
    )


def test_extension_grant_moves_planned_discharge_ledger_and_prospective_figure(api):
    """The grant is applied exactly once, pushing discharge, reserving days and re-deriving the advisory index.

    PRD §3.7: "On a grant, the granted days are reserved on the funding ledger,
    adding to `days_reserved` and subtracting from `days_available`, and
    `planned_discharge_at` is pushed out by 24 hours per granted day, so that the
    planned discharge always reflects `admitted_at` plus the initially planned
    days plus every day granted since."
    PRD §3.7: "`capture_adequacy_index_prospective` is recomputed, since
    `days_available` has moved."

    Design: Difficulty/combinatorial_formula/los_extension_pinned_evaluation_order_s1_s7
    """
    baseline = _stay_ready_for_extension(api)
    admission = validate_success(
        api.get_admission(baseline.admission_id, EPILEPTOLOGIST)
    )

    decided = validate_success(
        api.record_extension_decision(
            baseline.admission_id,
            f.extension_payload(admission["version"]),
            as_epileptologist("epi-los-1"),
        )
    )

    # admitted_at 2026-08-02T00:00:00Z plus 2 planned days plus 2 granted days.
    assert_instant_equals(
        decided["planned_discharge_at"], "2026-08-06T00:00:00Z", "planned_discharge_at"
    )
    # (2.000 + 1.000 * 1 remaining available day) / 4 = 0.750.
    assert_capture_value(
        decided["capture_adequacy_index_prospective"],
        0.750,
        "capture_adequacy_index_prospective",
    )
    # days_available is 1, not zero, so the authorization dimension stays active.
    assert_admission_dimensions(decided, CLINICAL_ADMITTED, AUTH_STATE_ACTIVE)

    authorization = validate_success(
        api.get_authorization(baseline.authorization_id, COORDINATOR)
    )
    assert_ledger(
        authorization,
        authorized_days=5,
        days_reserved=4,
        days_available=1,
        days_consumed=0,
    )
