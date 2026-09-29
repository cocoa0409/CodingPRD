"""Postures that are not a single linear status.

A device carries three orthogonal dimensions, so a lifecycle demotion must leave
the valve and the monitor mode exactly where they were.  A baseline profile is a
cycle rather than a line: the same row travels out of COMPLETE and back, and the
second completion recomputes its thresholds from scratch.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_baseline_profile,
    assert_device,
)
from test_helpers.fixtures import (
    ingest_burst_reading,
    ingest_reading,
    label_drip_false_positive,
    push_firmware,
    read_device,
    read_events,
    read_live_baseline,
    read_telemetry,
    read_tickets,
    set_clock,
    setup_armed_device,
    snooze_device,
)

BURST_AT = "2026-08-01T07:00:00Z"


def _closed_and_snoozed_then_firmware_pushed(api: ApiClient) -> dict:
    """Auto-close the valve, snooze the device, then push new firmware."""
    state = setup_armed_device(api)
    set_clock(api, BURST_AT)
    ingest_burst_reading(api, state["device_id"], BURST_AT)
    events = read_events(api, state["device_id"], event_state="ALERTED")
    assert len(events) == 1
    state["event"] = events[0]

    snooze_device(api, state["device_id"], state["homeowner_id"], 60)
    push_firmware(api, state["device_id"], "3.2.1", user_id="tech-02")
    return state


class TestDeviceParallelDimensions:
    def test_firmware_demotion_leaves_the_valve_and_the_monitor_mode_untouched(
        self, api: ApiClient
    ):
        """LEARNING plus CLOSED plus SNOOZE is a legal combined posture.

        "The third posture dimension on a device is `monitor_mode`, and it is
        genuinely independent of the other two: changing it neither moves the valve
        nor alters the lifecycle."
        "When the device was `ARMED` at the time of the push, the demotion cascade
        fires in three hops: the baseline profile moves `COMPLETE → INVALIDATED`
        with `invalidated_reason` `FIRMWARE_UPDATE`, `completed_at` cleared to null,
        and `false_positive_count` reset to 0; that invalidation demotes the device
        `ARMED → LEARNING` and sets `baseline_ready` back to false; and leaving
        `ARMED` suspends any policy on the property that was earning credit, with
        `suspended_reason` `DEVICE_NOT_ARMED` and a clawback of the newest awarded
        period, as §3.8 describes."
        "Acceptance sets `snooze_window_start_at` to the clock and
        `snooze_window_end_at` to the clock plus the requested minutes."

        Design: Difficulty/non_linear_state_machine/device_parallel_dimensions_independent
        """
        state = _closed_and_snoozed_then_firmware_pushed(api)
        device = read_device(api, state["device_id"])
        assert_device(device)

        assert device["lifecycle_state"] == "LEARNING"
        assert device["valve_state"] == "CLOSED"
        assert device["monitor_mode"] == "SNOOZE"

        assert device["close_count"] == 1
        assert device["reopen_count"] == 0
        assert device["last_shutoff_at"].startswith("2026-08-01T07:00:00")
        assert device["snooze_window_start_at"].startswith("2026-08-01T07:00:00")
        assert device["snooze_window_end_at"].startswith("2026-08-01T08:00:00")
        assert device["monitor_mode_updated_at"].startswith("2026-08-01T07:00:00")
        assert device["firmware_version"] == "3.2.1"
        assert device["baseline_ready"] is False

        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "INVALIDATED"
        assert profile["invalidated_reason"] == "FIRMWARE_UPDATE"
        assert profile["completed_at"] is None
        assert profile["false_positive_count"] == 0

    def test_a_learning_closed_snoozed_device_still_accepts_telemetry(
        self, api: ApiClient
    ):
        """The demoted device keeps ingesting and reopens its profile.

        "A device accepts telemetry only while its `lifecycle_state` is `LEARNING`,
        `ARMED`, or `TRANSFER_PENDING`."
        "A profile that has been invalidated re-enters `COLLECTING` on the very next
        accepted reading, at which point `learning_cycle_no` increments by 1,
        `learning_started_at` is reset to the clock,
        `baseline_static_pressure_psi`, `baseline_peak_flow_gpm`, and
        `drip_threshold_gpm` are all cleared, `false_positive_count` resets to 0, and
        `sample_count` restarts from the readings stamped at or after the new
        learning start."

        Design: Difficulty/non_linear_state_machine/device_parallel_dimensions_independent
        """
        state = _closed_and_snoozed_then_firmware_pushed(api)
        set_clock(api, "2026-08-01T07:20:00Z")
        ingest_reading(
            api,
            state["device_id"],
            "2026-08-01T07:20:00Z",
            static_pressure_psi=55.0,
            flow_gpm=0.0,
            duration_minutes=0,
            total_gallons=0.0,
        )

        latest = read_telemetry(api, state["device_id"])[-1]
        assert latest["reading_at"].startswith("2026-08-01T07:20:00")
        assert latest["classification_at_ingest"] == "NONE"
        assert latest["baseline_eligible"] is True

        profile = read_live_baseline(api, state["device_id"])
        assert_baseline_profile(profile)
        assert profile["learning_state"] == "COLLECTING"
        assert profile["learning_cycle_no"] == 2
        assert profile["learning_started_at"].startswith("2026-08-01T07:20:00")
        assert profile["sample_count"] == 1

        # Neither the mode change nor the firmware push touched the open event.
        event = read_events(api, state["device_id"])[0]
        assert event["id"] == state["event"]["id"]
        assert event["event_state"] == "ALERTED"
        assert event["mitigation_credited"] is True


DRIP_TIMES = ("2026-08-01T07:00:00Z", "2026-08-01T08:10:00Z", "2026-08-01T09:20:00Z")
RELEARN_TIMES = ("2026-08-01T09:30:00Z", "2026-08-01T09:50:00Z", "2026-08-01T10:10:00Z")


def _three_false_positives(api: ApiClient) -> dict:
    """Label three drips inside the rolling window, forcing a relearn."""
    state = setup_armed_device(api)
    for stamp in DRIP_TIMES:
        label_drip_false_positive(
            api, state["device_id"], state["homeowner_id"], stamp
        )
    return state


def _relearn_cycle_two(api: ApiClient, state: dict) -> dict:
    """Feed three fresh samples at 70.0 psi and 3.00 gpm peak."""
    for stamp in RELEARN_TIMES:
        set_clock(api, stamp)
        ingest_reading(
            api,
            state["device_id"],
            stamp,
            static_pressure_psi=70.0,
            flow_gpm=3.0,
            duration_minutes=4,
            total_gallons=12.0,
        )
    return state


class TestBaselineRelearnCycle:
    def test_the_third_false_positive_invalidates_the_profile_and_demotes_the_device(
        self, api: ApiClient
    ):
        """Tuning climbs 0.12 → 0.14 → 0.17 → 0.20 and then stops.

        "Third, the live baseline is widened: `drip_threshold_gpm` becomes the
        smaller of an absolute ceiling of 0.50 gallons per minute and the current
        threshold increased by twenty percent, rounded half up to two decimal
        places; `last_false_positive_at` is stamped at the clock; and
        `baseline_version` increments by 1."
        "Fourth and last, when the recomputed `false_positive_count` reaches **three
        or more**, the platform stops tuning and demands a fresh start."
        "The profile moves `COMPLETE → INVALIDATED` with `invalidated_reason`
        `FALSE_POSITIVE_THRESHOLD` and `completed_at` cleared to null; the device is
        demoted `ARMED → LEARNING` with `baseline_ready` set back to false and its
        `version` incremented by 1; the next accepted reading reopens the same
        profile row as `COLLECTING` with `learning_cycle_no` incremented; and any
        policy on the property that was in `CREDIT_ACTIVE` is suspended with a
        clawback as described in §3.8."

        Design: Difficulty/non_linear_state_machine/baseline_relearn_cycle_returns_to_collecting
        """
        state = _three_false_positives(api)

        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "INVALIDATED"
        assert profile["invalidated_reason"] == "FALSE_POSITIVE_THRESHOLD"
        assert profile["completed_at"] is None
        assert profile["false_positive_count"] == 3
        assert profile["drip_threshold_gpm"] == pytest.approx(0.20, abs=0.01)
        assert profile["learning_cycle_no"] == 1

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "LEARNING"
        assert device["baseline_ready"] is False

        events = read_events(api, state["device_id"])
        assert len(events) == 3
        newest = events[-1]
        assert newest["event_state"] == "FALSE_POSITIVE"
        assert newest["feedback_label"] == "FALSE_POSITIVE"

        ticket = read_tickets(api, anomaly_event_id=newest["id"])[0]
        assert ticket["stage"] == "EXPIRED"
        assert ticket["expiry_reason"] == "EVENT_CLOSED"

    def test_the_reopened_profile_is_the_same_row_on_a_second_cycle(
        self, api: ApiClient
    ):
        """The next reading reopens the row rather than minting another one.

        "A profile that has been invalidated re-enters `COLLECTING` on the very next
        accepted reading, at which point `learning_cycle_no` increments by 1,
        `learning_started_at` is reset to the clock,
        `baseline_static_pressure_psi`, `baseline_peak_flow_gpm`, and
        `drip_threshold_gpm` are all cleared, `false_positive_count` resets to 0, and
        `sample_count` restarts from the readings stamped at or after the new
        learning start."

        Design: Difficulty/non_linear_state_machine/baseline_relearn_cycle_returns_to_collecting
        """
        state = _three_false_positives(api)
        invalidated = read_live_baseline(api, state["device_id"])

        set_clock(api, RELEARN_TIMES[0])
        ingest_reading(
            api,
            state["device_id"],
            RELEARN_TIMES[0],
            static_pressure_psi=70.0,
            flow_gpm=3.0,
            duration_minutes=4,
            total_gallons=12.0,
        )

        reopened = read_live_baseline(api, state["device_id"])
        assert reopened["id"] == invalidated["id"]
        assert reopened["learning_state"] == "COLLECTING"
        assert reopened["learning_cycle_no"] == 2
        assert reopened["learning_started_at"].startswith("2026-08-01T09:30:00")
        assert reopened["sample_count"] == 1
        assert reopened["false_positive_count"] == 0
        assert reopened["baseline_peak_flow_gpm"] is None
        assert reopened["drip_threshold_gpm"] is None

    def test_the_second_completion_recomputes_the_threshold_from_scratch(
        self, api: ApiClient
    ):
        """0.06 from the new 3.00 gpm peak, not the tuned 0.20 it left behind.

        "The relearn discards every tuning step taken: the next `COMPLETE` profile
        recomputes `drip_threshold_gpm` from scratch as the greater of the 0.05 floor
        and two percent of the newly learned `baseline_peak_flow_gpm`, with no memory
        of the widened value."
        "Note carefully what does *not* happen: a reading rejected by any validation
        is never persisted and therefore never advances `sample_count`, and readings
        belonging to an earlier `learning_cycle_no` are excluded from the aggregate
        entirely, so a relearn genuinely starts from zero rather than blending old
        household behaviour into new."

        Design: Difficulty/non_linear_state_machine/baseline_relearn_cycle_returns_to_collecting
        """
        state = _three_false_positives(api)
        state = _relearn_cycle_two(api, state)

        profile = read_live_baseline(api, state["device_id"])
        assert_baseline_profile(profile)
        assert profile["learning_state"] == "COMPLETE"
        assert profile["learning_cycle_no"] == 2
        assert profile["sample_count"] == 3
        # 70.0 is the mean of the cycle-2 samples alone; averaging both cycles
        # would have produced 65.0.
        assert profile["baseline_static_pressure_psi"] == pytest.approx(70.0, abs=0.01)
        assert profile["baseline_peak_flow_gpm"] == pytest.approx(3.00, abs=0.01)
        assert profile["drip_threshold_gpm"] == pytest.approx(0.06, abs=0.01)
        assert profile["completed_at"].startswith("2026-08-01T10:10:00")
        # Three cycle-1 publications, three tuning widenings, three cycle-2
        # publications.
        assert profile["baseline_version"] == 9

        device = read_device(api, state["device_id"])
        assert device["lifecycle_state"] == "ARMED"
        assert device["baseline_ready"] is True

        # Classification is skipped throughout a COLLECTING cycle, so the three
        # relearn samples minted nothing.
        assert len(read_events(api, state["device_id"])) == 3
