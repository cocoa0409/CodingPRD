"""Which rows enter a computation, and which constants rescale it.

Two of these turn on the input set: an irrigation window pushes a reading out of
the classifier, and a bench test pushes one out of the learning aggregate.  Two
turn on constants: the vacation multiplier halves every flow and volume gate, and
each reading vouches for a fixed two hours whose spans merge edge to edge.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_baseline_profile,
    assert_credit_attestation,
    assert_insurance_policy,
    assert_telemetry_reading,
)
from test_helpers.fixtures import (
    finalize_attestation,
    ingest_quiet_reading,
    ingest_reading,
    open_attestation,
    read_attestation_list,
    read_device,
    read_events,
    read_live_baseline,
    read_policy,
    read_telemetry,
    set_clock,
    set_monitor_mode,
    setup_armed_device,
    setup_armed_device_with_policy,
    setup_irrigation_window,
    setup_learning_device,
)

WINDOW = ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")
INSIDE_AT = "2026-08-01T10:00:00Z"
AFTER_END_AT = "2026-08-01T11:00:00Z"
SPRINKLER_SHAPE = {
    "static_pressure_psi": 55.0,
    "flow_gpm": 8.0,
    "duration_minutes": 30,
    "total_gallons": 240.0,
}


def _one_sprinkler_shaped_reading_inside_the_window(api: ApiClient) -> dict:
    """8.0 gpm for half an hour, under the window's 9.0 gpm expectation."""
    state = setup_irrigation_window(
        api, *WINDOW, expected_max_flow_gpm=9.0, label="Front zone Saturday"
    )
    set_clock(api, INSIDE_AT)
    state["suppressed"] = ingest_reading(
        api, state["device_id"], INSIDE_AT, **SPRINKLER_SHAPE
    )
    return state


class TestIrrigationWindowFiltersTheClassifier:
    def test_a_running_fixture_shape_inside_the_window_is_forced_to_none(
        self, api: ApiClient
    ):
        """The verdict is overridden before the ladder ever reaches a rung.

        "During ingest, a reading whose `reading_at` falls inside an `ACTIVE` window for
        the property and whose `flow_gpm` is at or below that window's
        `expected_max_flow_gpm` has `suppressed_by_irrigation` set to true, its
        classification forced to `NONE`, and no anomaly event written — the sprinklers are
        simply doing their job."
        "Those three conditions together define eligibility: a reading is baseline-eligible
        exactly when its frozen classification is `NONE`, its `reading_source` is `DEVICE`,
        and its `suppressed_by_irrigation` flag is false."

        Design: Corner/calculations/irrigation_window_suppresses_running_fixture_classification
        """
        state = _one_sprinkler_shaped_reading_inside_the_window(api)

        reading = state["suppressed"]
        assert_telemetry_reading(reading)
        assert reading["suppressed_by_irrigation"] is True
        assert reading["classification_at_ingest"] == "NONE"
        assert reading["anomaly_event_created"] is False
        assert reading["baseline_eligible"] is False
        assert read_events(api, state["device_id"]) == []

        # A forced NONE cannot teach the baseline either.
        profile = read_live_baseline(api, state["device_id"])
        assert profile["sample_count"] == 3
        assert profile["baseline_static_pressure_psi"] == pytest.approx(60.0, abs=0.05)
        assert profile["baseline_peak_flow_gpm"] == pytest.approx(6.00, abs=0.01)

    def test_the_stored_suppressed_reading_still_vouches_for_its_two_hours(
        self, api: ApiClient
    ):
        """Suppression removes the verdict, not the row and not the coverage.

        "Every persisted reading also carries `coverage_minutes`, fixed at 120,
        representing the two hours of monitoring uptime that one sample vouches for;
        §3.7 explains how those spans are merged into an insurer-facing uptime figure."
        "**Step one**, the reading is persisted, with `device_id` set to the emitting
        device and `last_reading_at` on the device advanced to the new `reading_at`."

        Design: Corner/calculations/irrigation_window_suppresses_running_fixture_classification
        """
        state = _one_sprinkler_shaped_reading_inside_the_window(api)

        rows = read_telemetry(api, state["device_id"])
        stored = [r for r in rows if r["reading_at"].startswith("2026-08-01T10:00:00")]
        assert len(stored) == 1
        assert stored[0]["coverage_minutes"] == 120
        assert stored[0]["suppressed_by_irrigation"] is True

        device = read_device(api, state["device_id"])
        assert device["last_reading_at"].startswith("2026-08-01T10:00:00")
        # No verdict means no shutoff could follow.
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0

    def test_the_identical_shape_after_the_window_ends_is_a_running_fixture(
        self, api: ApiClient
    ):
        """Outside the span the same 8.0 gpm clears the 2.40 gpm running gate.

        "The **running-fixture flow gate** is `baseline_peak_flow_gpm` multiplied by 0.40
        and then by the multiplier."
        "Otherwise, if `flow_gpm` is at least the running-fixture flow gate **and**
        `duration_minutes` is at least 20 minutes, the verdict is `RUNNING_FIXTURE`."

        Design: Corner/calculations/irrigation_window_suppresses_running_fixture_classification
        """
        state = _one_sprinkler_shaped_reading_inside_the_window(api)
        set_clock(api, AFTER_END_AT)
        outside = ingest_reading(
            api, state["device_id"], AFTER_END_AT, **SPRINKLER_SHAPE
        )

        assert outside["suppressed_by_irrigation"] is False
        assert outside["classification_at_ingest"] == "RUNNING_FIXTURE"
        assert outside["anomaly_event_created"] is True

        events = read_events(api, state["device_id"])
        assert len(events) == 1
        assert events[0]["classification"] == "RUNNING_FIXTURE"
        assert events[0]["event_state"] == "ALERTED"
        assert events[0]["observed_flow_gpm"] == pytest.approx(8.0, abs=0.01)


BENCH_TEST = {
    "reading_at": "2026-08-01T00:00:00Z",
    "static_pressure_psi": 90.0,
    "flow_gpm": 0.0,
    "duration_minutes": 5.0,
    "total_gallons": 0.0,
    "reading_source": "MANUAL_TEST",
}
DEVICE_SAMPLES = [
    {
        "reading_at": "2026-08-01T00:10:00Z",
        "static_pressure_psi": 60.0,
        "flow_gpm": 0.0,
        "duration_minutes": 5.0,
        "total_gallons": 0.0,
    },
    {
        "reading_at": "2026-08-01T00:20:00Z",
        "static_pressure_psi": 62.0,
        "flow_gpm": 6.0,
        "duration_minutes": 4.0,
        "total_gallons": 24.0,
    },
]
COMPLETING_SAMPLE = {
    "reading_at": "2026-08-01T00:30:00Z",
    "static_pressure_psi": 58.0,
    "flow_gpm": 0.0,
    "duration_minutes": 5.0,
    "total_gallons": 0.0,
}


def _bench_test_then_two_device_samples(api: ApiClient) -> dict:
    """A 90.0 psi workbench sample that must not skew the 60.0 psi mean."""
    state = setup_learning_device(api)
    state["bench"] = ingest_reading(api, state["device_id"], **BENCH_TEST)
    for sample in DEVICE_SAMPLES:
        ingest_reading(api, state["device_id"], **sample)
    return state


class TestBenchTestExcludedFromTheLearningAggregate:
    def test_a_bench_reading_is_stored_but_never_counted_as_a_sample(
        self, api: ApiClient
    ):
        """Three readings in, sample_count 2, and the cycle still collecting.

        "A bench test is never baseline-eligible, which is the point of distinguishing it
        — a technician exercising the valve on the workbench must not teach the house's
        baseline."
        "`sample_count` is the number of telemetry readings for this device that are marked
        baseline-eligible and whose `reading_at` falls at or after the profile's current
        `learning_started_at`."

        Design: Corner/calculations/manual_test_reading_excluded_from_baseline_sample_set
        """
        state = _bench_test_then_two_device_samples(api)

        bench = state["bench"]
        assert bench["reading_source"] == "MANUAL_TEST"
        assert bench["baseline_eligible"] is False
        assert bench["classification_at_ingest"] == "NONE"

        assert len(read_telemetry(api, state["device_id"])) == 3
        excluded = read_telemetry(
            api, state["device_id"], params={"baseline_eligible": "false"}
        )
        assert len(excluded) == 1
        assert excluded[0]["reading_source"] == "MANUAL_TEST"

        profile = read_live_baseline(api, state["device_id"])
        assert_baseline_profile(profile)
        assert profile["learning_state"] == "COLLECTING"
        assert profile["sample_count"] == 2
        assert profile["completed_at"] is None
        assert read_device(api, state["device_id"])["lifecycle_state"] == "LEARNING"

    def test_the_published_mean_is_taken_over_the_eligible_readings_alone(
        self, api: ApiClient
    ):
        """60.0 psi from 60/62/58, not 67.5 psi from 90/60/62/58.

        "On each accepted reading while the profile is still `COLLECTING`, three values are
        recomputed over exactly that eligible set: `baseline_static_pressure_psi` is the
        arithmetic mean of the readings' static pressures, rounded half up to one decimal
        place; `baseline_peak_flow_gpm` is the largest observed flow among them, carried to
        two decimal places; and `drip_threshold_gpm` is the greater of an absolute floor of
        0.05 gallons per minute and two percent of `baseline_peak_flow_gpm`, rounded half
        up to two decimal places."
        "The transition `COLLECTING → COMPLETE` publishes the three learned values,
        increments `baseline_version` by 1, and stamps `completed_at` with the clock — and
        that publication bubbles up to promote the device from `LEARNING` to `ARMED`,
        setting `baseline_ready` to true."

        Design: Corner/calculations/manual_test_reading_excluded_from_baseline_sample_set
        """
        state = _bench_test_then_two_device_samples(api)
        ingest_reading(api, state["device_id"], **COMPLETING_SAMPLE)

        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "COMPLETE"
        assert profile["sample_count"] == 3
        assert profile["baseline_static_pressure_psi"] == pytest.approx(60.0, abs=0.05)
        assert profile["baseline_peak_flow_gpm"] == pytest.approx(6.00, abs=0.005)
        assert profile["drip_threshold_gpm"] == pytest.approx(0.12, abs=0.005)
        assert profile["baseline_version"] == 3
        assert profile["completed_at"].startswith("2026-08-01T06:05:00")

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "ARMED"
        assert device["baseline_ready"] is True


NORMAL_AT = "2026-08-01T07:00:00Z"
VACATION_AT = "2026-08-01T08:00:00Z"
VACATION_ENDS_AT = "2026-08-10T00:00:00Z"
BORDERLINE_SHAPE = {
    "static_pressure_psi": 50.0,
    "flow_gpm": 5.0,
    "duration_minutes": 4.0,
    "total_gallons": 20.0,
}


def _the_borderline_sample_while_at_home(api: ApiClient) -> dict:
    """5.0 gpm sits under the 9.00 gpm gate a 6.00 gpm peak implies at 1.00."""
    state = setup_armed_device(api)
    set_clock(api, NORMAL_AT)
    state["at_home"] = ingest_reading(
        api, state["device_id"], NORMAL_AT, **BORDERLINE_SHAPE
    )
    return state


class TestVacationMultiplierHalvesTheGates:
    def test_the_sample_is_benign_while_the_device_is_in_normal_mode(
        self, api: ApiClient
    ):
        """At a multiplier of 1.00 the ladder finds no rung to stand on.

        "It begins by resolving a sensitivity multiplier from the device's `monitor_mode`:
        in `VACATION` the multiplier is 0.50, which halves every flow and volume gate and
        thereby makes the device twice as suspicious; in `NORMAL` and in `SNOOZE` the
        multiplier is 1.00."
        "A verdict of `NONE` writes no anomaly event at all, leaves `anomaly_event_created`
        false, and — provided the sample came from `DEVICE` rather than `MANUAL_TEST` and
        was not suppressed by irrigation — marks the reading `baseline_eligible`."

        Design: Corner/calculations/vacation_multiplier_halves_burst_gates
        """
        state = _the_borderline_sample_while_at_home(api)

        reading = state["at_home"]
        assert reading["classification_at_ingest"] == "NONE"
        assert reading["anomaly_event_created"] is False
        assert reading["baseline_eligible"] is True
        assert read_events(api, state["device_id"]) == []

        device = read_device(api, state["device_id"])
        assert device["monitor_mode"] == "NORMAL"
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0

    def test_the_identical_sample_in_vacation_mode_is_a_catastrophic_burst(
        self, api: ApiClient
    ):
        """Halving puts the flow gate at 4.50 and the volume gate at 15 gallons.

        "The **burst flow gate** is `baseline_peak_flow_gpm` multiplied by 1.50 and then by
        the multiplier."
        "The **burst volume gate** is 30 gallons multiplied by the multiplier."
        "1. If `flow_gpm` is at least the burst flow gate, **and** `duration_minutes` is at
        least 3 minutes, **and** `total_gallons` is at least the burst volume gate, the
        verdict is `CATASTROPHIC_BURST`."

        Design: Corner/calculations/vacation_multiplier_halves_burst_gates
        """
        state = _the_borderline_sample_while_at_home(api)
        set_clock(api, VACATION_AT)
        away = set_monitor_mode(
            api,
            state["device_id"],
            state["homeowner_id"],
            "VACATION",
            vacation_ends_at=VACATION_ENDS_AT,
        )
        assert away["monitor_mode"] == "VACATION"

        reading = ingest_reading(
            api, state["device_id"], VACATION_AT, **BORDERLINE_SHAPE
        )
        assert reading["classification_at_ingest"] == "CATASTROPHIC_BURST"
        assert reading["anomaly_event_created"] is True

        events = read_events(api, state["device_id"])
        assert len(events) == 1
        assert events[0]["classification"] == "CATASTROPHIC_BURST"
        assert events[0]["event_state"] == "ALERTED"
        assert events[0]["observed_flow_gpm"] == pytest.approx(5.0, abs=0.005)
        assert events[0]["baseline_version_used"] == 3

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "CLOSED"
        assert device["close_count"] == 1
        assert device["last_shutoff_at"].startswith("2026-08-01T08:00:00")

    def test_the_drip_floor_is_left_unscaled_by_the_multiplier(self, api: ApiClient):
        """The published threshold is the drip gate in either mode.

        "The **drip gate** is simply the published `drip_threshold_gpm`, deliberately *not*
        scaled by the multiplier, because the drip floor is absolute."
        "For as long as the mode holds, the sensitivity multiplier described in §3.3 halves
        the burst flow gate, the running-fixture flow gate, and the burst volume gate, and
        the vacation-specific rung of the classification ladder becomes live so that any
        positive flow accumulating fifteen gallons is treated as a running fixture."

        Design: Corner/calculations/vacation_multiplier_halves_burst_gates
        """
        state = _the_borderline_sample_while_at_home(api)
        before = read_live_baseline(api, state["device_id"])
        assert before["drip_threshold_gpm"] == pytest.approx(0.12, abs=0.005)

        set_clock(api, VACATION_AT)
        set_monitor_mode(
            api,
            state["device_id"],
            state["homeowner_id"],
            "VACATION",
            vacation_ends_at=VACATION_ENDS_AT,
        )
        ingest_reading(api, state["device_id"], VACATION_AT, **BORDERLINE_SHAPE)

        after = read_live_baseline(api, state["device_id"])
        assert after["drip_threshold_gpm"] == pytest.approx(0.12, abs=0.005)
        assert after["baseline_peak_flow_gpm"] == pytest.approx(6.00, abs=0.005)
        assert after["baseline_version"] == before["baseline_version"]


POLICY_YEAR_START = "2026-08-03T00:00:00Z"
PERIOD = ("2026-08-03T00:00:00Z", "2026-08-03T04:00:00Z")
READING_TIMES = ("2026-08-03T00:00:00Z", "2026-08-03T02:00:00Z")
LAST_READING_AT = "2026-08-03T02:00:00Z"
PERIOD_END_AT = "2026-08-03T04:00:00Z"


def _two_samples_exactly_two_hours_apart_then_finalize(api: ApiClient) -> dict:
    """00:00 covers to 02:00 and 02:00 covers to 04:00, edge to edge."""
    state = setup_armed_device_with_policy(api, POLICY_YEAR_START)
    set_clock(api, LAST_READING_AT)
    for stamp in READING_TIMES:
        ingest_quiet_reading(api, state["device_id"], stamp)
    set_clock(api, PERIOD_END_AT)
    opened = open_attestation(api, state["policy_id"], *PERIOD)
    assert opened["status"] == "OPEN"
    assert opened["period_minutes"] == 240
    state["attestation_id"] = opened["id"]
    state["attestation"] = finalize_attestation(api, opened["id"])
    return state


class TestAdjacentCoverageIntervalsMerge:
    def test_samples_exactly_two_hours_apart_leave_no_uncovered_minute(
        self, api: ApiClient
    ):
        """One 240-minute block from two readings, so uptime is 100.00.

        "Those intervals are sorted by start ascending and merged, with two intervals
        merging whenever the next one's start is at or before the current one's end —
        adjacency with a zero-minute gap merges, so readings taken exactly two hours apart
        produce one continuous block with no lost minute (samples at 06:40 and 08:40 cover
        a single 240-minute stretch)."
        "`offline_gap_count` is the number of maximal uncovered stretches inside the period
        whose length is at least a full hour; shorter holes are not counted."

        Design: Corner/calculations/uptime_adjacent_readings_exactly_120_minutes_apart_merge
        """
        state = _two_samples_exactly_two_hours_apart_then_finalize(api)

        attestation = state["attestation"]
        assert_credit_attestation(attestation)
        assert attestation["period_minutes"] == 240
        assert attestation["covered_minutes"] == 240
        assert attestation["uptime_pct"] == pytest.approx(100.00, abs=0.005)
        assert attestation["offline_gap_count"] == 0

    def test_the_clamped_tail_keeps_the_top_tier_award_at_the_ceiling(
        self, api: ApiClient
    ):
        """The 02:00 sample's tail is cut at the period end, not beyond it.

        "Because of the clamp, `covered_minutes` can never exceed `period_minutes` and
        `uptime_pct` can never exceed 100.00."
        "A tier is selected from `uptime_pct` by the first matching band, with every cut
        inclusive and no interpolation between bands: at least 99.00 percent earns a
        `tier_pct` of 0.12, at least 97.00 percent earns 0.08, at least 95.00 percent earns
        0.05, and anything below 95.00 percent earns nothing."
        "The **provisional period accrual** runs on every finalize: `credit_cents_awarded`
        is the policy's `annual_premium_cents` multiplied by `tier_pct`, divided by the two
        attestation periods that make up a policy year, and rounded half up to a whole
        cent."

        Design: Corner/calculations/uptime_adjacent_readings_exactly_120_minutes_apart_merge
        """
        state = _two_samples_exactly_two_hours_apart_then_finalize(api)

        attestation = state["attestation"]
        assert attestation["status"] == "FINALIZED_AWARDED"
        assert attestation["tier_pct"] == pytest.approx(0.12, abs=0.005)
        assert attestation["credit_cents_awarded"] == 8994
        assert attestation["true_up_cents"] == 0
        assert attestation["is_policy_year_close"] is False
        assert attestation["denial_reason"] is None
        assert attestation["device_snapshot_lifecycle_state"] == "ARMED"
        assert attestation["finalized_at"].startswith("2026-08-03T04:00:00")

        rows = read_attestation_list(api, state["policy_id"])
        assert len(rows) == 1
        assert rows[0]["covered_minutes"] == 240

        policy = read_policy(api, state["policy_id"])
        assert_insurance_policy(policy)
        assert policy["credit_state"] == "CREDIT_ACTIVE"
        assert policy["credited_cents_total"] == 8994
        assert policy["clawback_cents_total"] == 0
        assert policy["current_credit_tier_pct"] == pytest.approx(0.12, abs=0.005)
        assert policy["finalized_period_count"] == 1
        assert policy["avg_uptime_pct"] == pytest.approx(100.00, abs=0.005)
        assert policy["last_attestation_end_at"].startswith("2026-08-03T04:00:00")
