"""Two boundaries that have to fall on the exact side the contract names.

Uptime of exactly 95.00 percent earns the lowest credit tier because the floor is
inclusive, while one minute less denies the period outright.  An irrigation window
covers its start instant but not its end instant, so a reading stamped exactly at
`end_at` is classified rather than suppressed.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_credit_attestation,
    assert_uptime_precision,
)
from test_helpers.fixtures import (
    finalize_attestation,
    ingest_quiet_readings,
    ingest_reading,
    open_attestation,
    read_device,
    read_events,
    read_irrigation_windows,
    read_policy,
    read_telemetry,
    read_tickets,
    set_clock,
    setup_finalized_credit_period,
    setup_irrigation_window,
)

PERIOD_2 = ("2026-08-02T06:40:00Z", "2026-08-02T13:20:00Z")
PERIOD_2_READINGS = (
    "2026-08-02T06:40:00Z",
    "2026-08-02T08:40:00Z",
    "2026-08-02T10:40:00Z",
    "2026-08-02T13:01:00Z",
)


def _floor_period_then_one_minute_below(api: ApiClient) -> dict:
    """Award a period at exactly 95.00, then finalize one at 94.75."""
    state = setup_finalized_credit_period(api)
    set_clock(api, "2026-08-02T13:01:00Z")
    ingest_quiet_readings(api, state["device_id"], PERIOD_2_READINGS)
    second = open_attestation(api, state["policy_id"], *PERIOD_2)
    set_clock(api, PERIOD_2[1])
    state["attestation_2"] = finalize_attestation(api, second["id"])
    state["attestation_2_id"] = second["id"]
    return state


class TestUptimeCreditFloor:
    def test_exactly_95_00_percent_awards_the_lowest_tier(self, api: ApiClient):
        """The floor is inclusive, so the period is awarded rather than denied.

        "A tier is selected from `uptime_pct` by the first matching band, with every
        cut inclusive and no interpolation between bands: at least 99.00 percent
        earns a `tier_pct` of 0.12, at least 97.00 percent earns 0.08, at least
        95.00 percent earns 0.05, and anything below 95.00 percent earns nothing."
        "`covered_minutes` is the total length of the merged intervals in whole
        minutes; `uptime_pct` is `covered_minutes` multiplied by 100, divided by
        `period_minutes`, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/uptime_exactly_at_credit_floor
        """
        state = setup_finalized_credit_period(api)
        awarded = state["attestation"]
        assert_credit_attestation(awarded)

        assert awarded["period_minutes"] == 400
        assert awarded["covered_minutes"] == 380
        assert_uptime_precision(awarded["uptime_pct"])
        assert awarded["uptime_pct"] == pytest.approx(95.00, abs=0.01)
        assert awarded["tier_pct"] == pytest.approx(0.05, abs=0.01)
        assert awarded["credit_cents_awarded"] == 3748
        assert awarded["status"] == "FINALIZED_AWARDED"
        assert awarded["denial_reason"] is None

    def test_one_covered_minute_below_the_floor_denies_the_period(
        self, api: ApiClient
    ):
        """379 covered minutes of the same 400 is 94.75 and earns nothing.

        "Three denial reasons exist and they are mutually exclusive:
        `UPTIME_BELOW_FLOOR` when `uptime_pct` is below 95.00; `DEVICE_NOT_ARMED`
        when the resolved device's `lifecycle_state` is anything other than `ARMED`;
        and `NO_ENROLLED_DEVICE` when no device resolves for the policy's property
        at all."
        "`offline_gap_count` is the number of maximal uncovered stretches inside the
        period whose length is at least a full hour; shorter holes are not counted."

        Design: Difficulty/boundary_precision_check/uptime_exactly_at_credit_floor
        """
        state = _floor_period_then_one_minute_below(api)
        denied = state["attestation_2"]
        assert_credit_attestation(denied)

        assert denied["period_minutes"] == 400
        assert denied["covered_minutes"] == 379
        assert denied["uptime_pct"] == pytest.approx(94.75, abs=0.01)
        assert denied["tier_pct"] == pytest.approx(0.00, abs=0.01)
        assert denied["credit_cents_awarded"] == 0
        assert denied["status"] == "FINALIZED_DENIED"
        assert denied["denial_reason"] == "UPTIME_BELOW_FLOOR"

        # The uncovered span [12:40, 13:01) is 21 minutes, short of the hour.
        assert denied["offline_gap_count"] == 0

        # A denied period still closes the policy year, and the annual figure
        # matches the single awarded period's provisional accrual exactly.
        assert denied["is_policy_year_close"] is True
        assert denied["true_up_cents"] == 0

    def test_a_denial_suspends_the_credit_without_clawing_anything_back(
        self, api: ApiClient
    ):
        """The awarded period keeps its 3748 cents; no reversal is booked.

        "A denial still advances the chain, setting the policy's
        `last_attestation_end_at` to the period end, and when the policy was
        `CREDIT_ACTIVE` and the reason was `UPTIME_BELOW_FLOOR` it drives the policy
        `CREDIT_ACTIVE → CREDIT_SUSPENDED` with `suspended_reason`
        `UPTIME_BELOW_FLOOR` and `current_credit_tier_pct` reset to 0."
        "Two policy figures are derived rather than accumulated and are recomputed
        at this point: `finalized_period_count` is the number of the policy's
        attestations whose `status` is either `FINALIZED_AWARDED` or
        `FINALIZED_DENIED`, and `avg_uptime_pct` is the arithmetic mean of
        `uptime_pct` across those same rows, rounded half up to two decimal places,
        or null when the policy has no finalized period yet."

        Design: Difficulty/boundary_precision_check/uptime_exactly_at_credit_floor
        """
        state = _floor_period_then_one_minute_below(api)

        policy = read_policy(api, state["policy_id"])
        assert policy["credit_state"] == "CREDIT_SUSPENDED"
        assert policy["suspended_reason"] == "UPTIME_BELOW_FLOOR"
        assert policy["credited_cents_total"] == 3748
        assert policy["clawback_cents_total"] == 0
        assert policy["current_credit_tier_pct"] == pytest.approx(0.00, abs=0.01)

        assert policy["finalized_period_count"] == 2
        assert policy["avg_uptime_pct"] == pytest.approx(94.88, abs=0.01)

        # The earlier award is untouched.
        assert state["attestation"]["credit_cents_awarded"] == 3748


WINDOW = ("2026-08-01T07:00:00Z", "2026-08-01T08:00:00Z")
INSIDE_AT = "2026-08-01T07:59:00Z"
AT_END_AT = "2026-08-01T08:00:00Z"
RUNNING_SAMPLE = {
    "static_pressure_psi": 54.0,
    "flow_gpm": 3.0,
    "duration_minutes": 30,
    "total_gallons": 90.0,
}


def _one_reading_inside_the_window_and_one_at_its_end(api: ApiClient) -> dict:
    """The same running-fixture sample, one minute before end_at and at it."""
    state = setup_irrigation_window(api, *WINDOW, label="Front zone Saturday")
    set_clock(api, INSIDE_AT)
    ingest_reading(api, state["device_id"], INSIDE_AT, **RUNNING_SAMPLE)
    set_clock(api, AT_END_AT)
    ingest_reading(api, state["device_id"], AT_END_AT, **RUNNING_SAMPLE)
    return state


class TestIrrigationWindowEndAtIsExclusive:
    def test_a_reading_one_minute_inside_the_window_is_suppressed(
        self, api: ApiClient
    ):
        """Suppression covers 07:59Z and keeps the sample out of the baseline.

        "During ingest, a reading whose `reading_at` falls inside an `ACTIVE` window
        for the property and whose `flow_gpm` is at or below that window's
        `expected_max_flow_gpm` has `suppressed_by_irrigation` set to true, its
        classification forced to `NONE`, and no anomaly event written — the
        sprinklers are simply doing their job."
        "Two interval families exist in this system, and both are **half-open**:
        they include their start instant and exclude their end instant."
        "Those three conditions together define eligibility: a reading is
        baseline-eligible exactly when its frozen classification is `NONE`, its
        `reading_source` is `DEVICE`, and its `suppressed_by_irrigation` flag is
        false."

        Design: Difficulty/boundary_precision_check/irrigation_window_end_at_is_exclusive
        """
        state = _one_reading_inside_the_window_and_one_at_its_end(api)
        rows = read_telemetry(api, state["device_id"])
        inside = [r for r in rows if r["reading_at"].startswith("2026-08-01T07:59:00")]
        assert len(inside) == 1

        assert inside[0]["suppressed_by_irrigation"] is True
        assert inside[0]["classification_at_ingest"] == "NONE"
        assert inside[0]["anomaly_event_created"] is False
        assert inside[0]["baseline_eligible"] is False

    def test_a_reading_stamped_exactly_at_end_at_is_classified(self, api: ApiClient):
        """08:00Z lies outside the interval, so the same flow alerts.

        "Two interval families exist in this system, and both are **half-open**:
        they include their start instant and exclude their end instant."
        "Otherwise, if `flow_gpm` is at least the running-fixture flow gate **and**
        `duration_minutes` is at least 20 minutes, the verdict is
        `RUNNING_FIXTURE`."
        "Rounding is applied **once**, to the weighted sum, half up to three decimal
        places; summing three separately rounded components is incorrect."

        Design: Difficulty/boundary_precision_check/irrigation_window_end_at_is_exclusive
        """
        state = _one_reading_inside_the_window_and_one_at_its_end(api)
        rows = read_telemetry(api, state["device_id"])
        at_end = [r for r in rows if r["reading_at"].startswith("2026-08-01T08:00:00")]
        assert len(at_end) == 1

        assert at_end[0]["suppressed_by_irrigation"] is False
        assert at_end[0]["classification_at_ingest"] == "RUNNING_FIXTURE"
        assert at_end[0]["anomaly_event_created"] is True

        events = read_events(api, state["device_id"])
        assert len(events) == 1
        event = events[0]
        assert event["classification"] == "RUNNING_FIXTURE"
        assert event["event_state"] == "ALERTED"
        assert event["detected_at"].startswith("2026-08-01T08:00:00")
        assert event["observed_flow_gpm"] == pytest.approx(3.0, abs=0.01)
        assert event["observed_duration_minutes"] == pytest.approx(30, abs=0.01)
        assert event["observed_gallons"] == pytest.approx(90.0, abs=0.01)
        # Flow 3.0 / 18.0 unclamped, both other components clamped at 1.0.
        assert event["severity_score"] == pytest.approx(0.583, abs=0.0005)

        ticket = read_tickets(api, anomaly_event_id=event["id"])[0]
        assert ticket["stage"] == "PENDING_HOMEOWNER"
        assert ticket["homeowner_deadline_at"].startswith("2026-08-01T08:15:00")

    def test_a_running_fixture_in_normal_mode_leaves_the_valve_and_window_alone(
        self, api: ApiClient
    ):
        """No shutoff means nothing suspends the declared window.

        "A shutoff is *required* in exactly two situations: the classification is
        `CATASTROPHIC_BURST`, in any mode; or the classification is
        `RUNNING_FIXTURE` and the device's `monitor_mode` is `VACATION`."
        "And every irrigation window belonging to the device's property whose
        `status` is `ACTIVE` moves to `SUSPENDED_BY_SHUTOFF` with `suspended_at`
        stamped at the clock; there is no point excusing sprinkler flow on a line
        that has no water in it."

        Design: Difficulty/boundary_precision_check/irrigation_window_end_at_is_exclusive
        """
        state = _one_reading_inside_the_window_and_one_at_its_end(api)

        event = read_events(api, state["device_id"])[0]
        assert event["auto_shutoff_executed"] is False

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0

        window = read_irrigation_windows(
            api, state["property_id"], state["homeowner_headers"]
        )[0]
        assert window["status"] == "ACTIVE"
        assert window["suspended_at"] is None
