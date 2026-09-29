"""Two formulas whose answer depends on the order their steps are applied in.

The severity score clamps each component before weighting and rounds exactly once
afterwards.  The ingest pipeline persists, then classifies against the snapshot as
it stood before the reading was folded in, then republishes — which is what makes
the reading that completes a learning cycle provably unclassified.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_anomaly_event,
    assert_baseline_profile,
    assert_device,
    assert_severity_precision,
    assert_telemetry_reading,
)
from test_helpers.constants import CANONICAL_LEARNING_READINGS
from test_helpers.fixtures import (
    ingest_burst_reading,
    ingest_reading,
    read_device,
    read_events,
    read_live_baseline,
    read_telemetry,
    set_clock,
    setup_armed_device,
    setup_learning_device,
)

BURST_AT = "2026-08-01T07:00:00Z"


def _armed_device_with_burst(api: ApiClient) -> dict:
    """Arm the canonical device, then ingest the 12.0 gpm burst sample."""
    state = setup_armed_device(api)
    set_clock(api, BURST_AT)
    state["burst_reading"] = ingest_burst_reading(api, state["device_id"], BURST_AT)
    return state


class TestSeverityScoreFormula:
    def test_severity_score_clamps_each_component_then_rounds_the_sum_once(
        self, api: ApiClient
    ):
        """0.833, not the 0.834 that per-component rounding would produce.

        "Three reference denominators are computed first, each the corresponding
        burst gate doubled and rounded to four decimal places: the flow reference is
        twice the burst flow gate, the duration reference is twice the 3-minute
        burst duration threshold (so 6.0000 minutes), and the volume reference is
        twice the burst volume gate."
        "Three components follow, each the observed value divided by its reference
        and then capped at 1.0 — the cap is applied to each component individually,
        before weighting, so no single enormous measurement can push the score
        beyond its own share."
        "Rounding is applied **once**, to the weighted sum, half up to three decimal
        places; summing three separately rounded components is incorrect."

        Design: Difficulty/combinatorial_formula/severity_score_weighted_clamp_then_round
        """
        state = _armed_device_with_burst(api)
        events = read_events(api, state["device_id"], classification="CATASTROPHIC_BURST")
        assert len(events) == 1
        event = events[0]
        assert_anomaly_event(event)

        assert event["classification"] == "CATASTROPHIC_BURST"
        assert event["event_state"] == "ALERTED"

        # flow 12.0 / 18.0 unrounded, duration 6 / 6.0 clamped at 1.0, gallons
        # 72.0 / 60.0 clamped at 1.0, weighted 0.50 / 0.30 / 0.20 and rounded once.
        assert_severity_precision(event["severity_score"])
        assert event["severity_score"] == pytest.approx(0.833, abs=0.0005)
        assert event["severity_score"] != pytest.approx(0.834, abs=0.0005)

        assert event["observed_flow_gpm"] == pytest.approx(12.0, abs=0.01)
        assert event["observed_duration_minutes"] == pytest.approx(6, abs=0.01)
        assert event["observed_gallons"] == pytest.approx(72.0, abs=0.01)
        assert event["baseline_version_used"] == 3
        assert event["detected_at"].startswith("2026-08-01T07:00:00")

    def test_burst_ingest_closes_the_valve_and_freezes_the_readings_verdict(
        self, api: ApiClient
    ):
        """The scored event and its shutoff cascade land in the same request.

        "A shutoff is *required* in exactly two situations: the classification is
        `CATASTROPHIC_BURST`, in any mode; or the classification is
        `RUNNING_FIXTURE` and the device's `monitor_mode` is `VACATION`."
        "When no gate applies, the closure executes as a single atomic cascade: the
        device's `valve_state` moves `OPEN → CLOSED`, `close_count` increases by 1,
        `last_shutoff_at` is stamped with the clock, and the device's `version`
        increases by 1."
        "Those three conditions together define eligibility: a reading is
        baseline-eligible exactly when its frozen classification is `NONE`, its
        `reading_source` is `DEVICE`, and its `suppressed_by_irrigation` flag is
        false."

        Design: Difficulty/combinatorial_formula/severity_score_weighted_clamp_then_round
        """
        state = _armed_device_with_burst(api)
        events = read_events(api, state["device_id"])
        assert len(events) == 1
        event = events[0]

        assert event["auto_shutoff_executed"] is True
        assert event["shutoff_latency_minutes"] == pytest.approx(0.0, abs=0.01)
        assert event["mitigation_credited"] is True

        device = read_device(api, state["device_id"])
        assert_device(device)
        assert device["valve_state"] == "CLOSED"
        assert device["close_count"] == 1
        assert device["last_shutoff_at"].startswith("2026-08-01T07:00:00")

        burst = [
            row for row in read_telemetry(api, state["device_id"])
            if row["reading_at"].startswith("2026-08-01T07:00:00")
        ]
        assert len(burst) == 1
        assert_telemetry_reading(burst[0])
        assert burst[0]["classification_at_ingest"] == "CATASTROPHIC_BURST"
        assert burst[0]["baseline_eligible"] is False
        assert burst[0]["anomaly_event_created"] is True


class TestIngestEvaluationOrder:
    def _collecting_device_with_two_samples(self, api: ApiClient) -> dict:
        state = setup_learning_device(api)
        for sample in CANONICAL_LEARNING_READINGS[:2]:
            ingest_reading(api, state["device_id"], **sample)
        return state

    def test_the_reading_that_completes_learning_is_never_classified(
        self, api: ApiClient
    ):
        """A sample exactly on the standing burst gate still records NONE.

        "While the profile is still `COLLECTING`, classification is skipped
        entirely, `classification_at_ingest` is `NONE`, and the reading is
        baseline-eligible."
        "Two consequences follow and are binding: the very reading that completes a
        learning cycle is itself never classified, and a stored reading's
        `classification_at_ingest` is permanent — later baseline recomputation never
        reclassifies history."
        "The transition `COLLECTING → COMPLETE` publishes the three learned values,
        increments `baseline_version` by 1, and stamps `completed_at` with the clock
        — and that publication bubbles up to promote the device from `LEARNING` to
        `ARMED`, setting `baseline_ready` to true."

        Design: Difficulty/combinatorial_formula/baseline_classification_evaluation_order
        """
        state = self._collecting_device_with_two_samples(api)

        # Flow 9.0 with 6 minutes and 60 gallons meets the standing burst gate of
        # 9.00 exactly, yet the profile is still COLLECTING when it lands.
        ingest_reading(
            api,
            state["device_id"],
            "2026-08-01T00:40:00Z",
            static_pressure_psi=58.0,
            flow_gpm=9.0,
            duration_minutes=6,
            total_gallons=60.0,
        )

        rows = read_telemetry(api, state["device_id"])
        completing = rows[-1]
        assert completing["reading_at"].startswith("2026-08-01T00:40:00")
        assert completing["classification_at_ingest"] == "NONE"
        assert completing["baseline_eligible"] is True
        assert completing["anomaly_event_created"] is False

        profile = read_live_baseline(api, state["device_id"])
        assert_baseline_profile(profile)
        assert profile["learning_state"] == "COMPLETE"
        assert profile["sample_count"] == 3
        assert profile["baseline_static_pressure_psi"] == pytest.approx(60.0, abs=0.01)
        assert profile["baseline_peak_flow_gpm"] == pytest.approx(9.00, abs=0.01)
        assert profile["drip_threshold_gpm"] == pytest.approx(0.18, abs=0.01)
        assert profile["baseline_version"] == 3

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "ARMED"
        assert device["baseline_ready"] is True
        assert read_events(api, state["device_id"]) == []

    def test_the_next_reading_is_judged_against_the_freshly_published_snapshot(
        self, api: ApiClient
    ):
        """12.0 gpm is quiet under a 9.00 gpm peak the previous reading published.

        "**Step two**, classification runs against the baseline snapshot *as it
        stood before this reading was folded in* — that is, against the values
        published by earlier readings — and the resulting verdict is frozen in the
        reading's `classification_at_ingest` and, on any anomaly event minted, in
        `baseline_version_used`."
        "The **burst flow gate** is `baseline_peak_flow_gpm` multiplied by 1.50 and
        then by the multiplier."
        "On each accepted reading while the profile is still `COLLECTING`, three
        values are recomputed over exactly that eligible set"

        Design: Difficulty/combinatorial_formula/baseline_classification_evaluation_order
        """
        state = self._collecting_device_with_two_samples(api)
        ingest_reading(
            api,
            state["device_id"],
            "2026-08-01T00:40:00Z",
            static_pressure_psi=58.0,
            flow_gpm=9.0,
            duration_minutes=6,
            total_gallons=60.0,
        )
        ingest_reading(
            api,
            state["device_id"],
            "2026-08-01T01:00:00Z",
            static_pressure_psi=30.0,
            flow_gpm=12.0,
            duration_minutes=6,
            total_gallons=72.0,
        )

        rows = read_telemetry(api, state["device_id"])
        later = rows[-1]
        assert later["reading_at"].startswith("2026-08-01T01:00:00")
        # Burst gate 13.50, running gate 3.60 needing 20 minutes, drip gate 0.18
        # needing a full hour: 12.0 gpm for 6 minutes matches no rung.
        assert later["classification_at_ingest"] == "NONE"
        assert later["baseline_eligible"] is True
        assert later["anomaly_event_created"] is False

        assert read_events(api, state["device_id"]) == []

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0

        # Recomputation is scoped to a COLLECTING profile, so the published
        # snapshot the classifier used is still the live one.
        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "COMPLETE"
        assert profile["baseline_version"] == 3
        assert profile["baseline_peak_flow_gpm"] == pytest.approx(9.00, abs=0.01)
