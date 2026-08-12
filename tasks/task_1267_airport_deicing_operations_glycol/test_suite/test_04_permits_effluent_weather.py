"""Tests for discharge permits, effluent readings, and weather events."""
import pytest

from test_helpers import (

    ApiErrorId,
    TEST_USERS,
    create_and_activate_weather_event,
    create_discharge_permit_payload,
    create_effluent_reading_payload,
    create_station,
    create_station_with_permit,
    create_weather_event,
    escalate_payload,
    make_environmental_officer_headers,
    setup_weather_event_escalated,
    validate_error,
    validate_success,
)


def _parse_ts(value: str):
    """Parse an ISO-8601 UTC timestamp into an aware datetime for
    instant-equality comparison."""
    from datetime import datetime, timezone

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestPermitOcc:
    def test_occ_permit_create_stale_station_version_rejected(self, api):
        """PRD §2.6: "Creating a discharge permit requires the request to carry
        `expected_station_version`, the client-observed `version` of the
        station. A mismatch with the station's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412), because permit creation
        legitimately supersedes the station's prior `ACTIVE` permit and a stale
        station view must not drive that supersede."

        Design: Corner/cross_cutting_layers/occ_permit_create_stale_station_version_rejected
        """
        station = create_station()
        stale_version = station["version"]

        # First permit advances the station version.
        payload = create_discharge_permit_payload(
            station["id"], expected_station_version=stale_version
        )
        resp = api.create_discharge_permit(
            payload, TEST_USERS["station_admin_headers"]
        )
        permit1 = validate_success(resp, expected_status=201)
        assert permit1["status"] == "ACTIVE"

        # Second create with the stale version is rejected.
        payload = create_discharge_permit_payload(
            station["id"],
            permit_number="P-2",
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2027-05-31T00:00:00Z",
            max_single_reading_mg_l=80,
            rolling_window_days=7,
            rolling_window_max_liters=90000,
            expected_station_version=stale_version,
        )
        resp = api.create_discharge_permit(
            payload, TEST_USERS["station_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # Permit P-1 remains ACTIVE.
        resp = api.get_discharge_permit(
            permit1["id"], TEST_USERS["environmental_officer_headers"]
        )
        assert validate_success(resp)["status"] == "ACTIVE"


class TestPermitLifecycle:
    def test_permit_expires_at_checkpoint_past_effective_to(self, api):
        """PRD §3.7: "Permits also expire through the ops checkpoint, and an
        `ACTIVE` permit expiring leaves the station in `PERMIT_SUSPENDED`
        posture until a replacement is created."

        Design: Corner/state_machines/permit_expires_at_checkpoint_past_effective_to
        """
        station, permit = create_station_with_permit(
            permit_overrides={
                "effective_from": "2026-04-01T00:00:00Z",
                "effective_to": "2026-05-02T00:00:00Z",
            }
        )
        # Advance the logical clock past the permit's effective_to.
        api.set_current_utc(
            {"to_iso8601": "2026-05-03T00:00:00Z"},
            TEST_USERS["station_admin_headers"],
        )

        resp = api.run_ops_checkpoint(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        station_after = validate_success(resp)
        assert station_after["posture"] == "PERMIT_SUSPENDED"

        resp = api.get_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )
        assert validate_success(resp)["status"] == "EXPIRED"

    def test_assign_blocked_when_station_permit_suspended(self, api):
        """PRD §3.4: "The station's posture must not be `PERMIT_SUSPENDED`,
        which rejects with `ERR_PERMIT_SUSPENDED`, and must not be
        `FLUID_CONSTRAINED`, which rejects with `ERR_FLUID_CONSTRAINED`."
        PRD §3.7: "An `EnvironmentalOfficer` may suspend an `ACTIVE` permit,
        moving it to `SUSPENDED`, and may reinstate a `SUSPENDED` permit back
        to `ACTIVE`; both actions recompute the station's posture."

        Design: Difficulty/cross_entity_state_dependency/assign_blocked_when_station_permit_suspended
        """
        from test_helpers import (
            assign_request_payload,
            create_reserved_request,
            setup_operational_base,
        )

        station, permit, tank, pad, airline = setup_operational_base()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        # Suspend the permit.
        resp = api.suspend_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )
        validate_success(resp)

        # Assign blocked while suspended.
        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_SUSPENDED)

        # Reinstate and assign succeeds.
        resp = api.reinstate_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )
        validate_success(resp)

        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "ASSIGNED"

    def test_permit_suspension_beats_pad_incompatibility(self, api):
        """PRD §2.8: "Regulatory and safety gates are fifth — a suspended
        permit blocking assignment (`ERR_PERMIT_SUSPENDED`)... Business
        constraints are sixth: pad size compatibility
        (`ERR_PAD_INCOMPATIBLE`)..."

        Design: Difficulty/priority_pair_validation_conflict/permit_suspension_beats_pad_incompatibility
        """
        from test_helpers import (
            assign_request_payload,
            create_reserved_request,
            setup_operational_base,
        )

        station, permit, tank, pad, airline = setup_operational_base(
            pad_overrides={"max_size_class": "SMALL"}
        )
        request = create_reserved_request(airline, station, tank, size_class="LARGE")

        # Suspend the permit so both p5 and p6 would fail.
        api.suspend_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )

        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_SUSPENDED)

        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "QUEUED"
        assert validate_success(resp)["assigned_pad_id"] is None


class TestPermitSuspensionPriority:
    def test_permit_suspension_beats_pad_unavailable(self, api):
        """PRD §2.8: "Regulatory and safety gates are fifth — a suspended
        permit blocking assignment (`ERR_PERMIT_SUSPENDED`)... Business
        constraints are sixth: pad size compatibility
        (`ERR_PAD_INCOMPATIBLE`), pad availability (`ERR_PAD_NOT_AVAILABLE`)..."

        Design: Difficulty/priority_pair_validation_conflict/permit_suspension_beats_pad_incompatibility
        """
        from test_helpers import (
            assign_request_payload,
            create_reserved_request,
            setup_operational_base,
        )

        station, permit, tank, pad, airline = setup_operational_base()
        request = create_reserved_request(airline, station, tank, size_class="MEDIUM")

        # Take pad out of service AND suspend permit.
        api.take_pad_out_of_service(
            pad["id"], TEST_USERS["station_admin_headers"]
        )
        api.suspend_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )

        payload = assign_request_payload(pad["id"])
        resp = api.assign_deice_request(
            request["id"], payload, TEST_USERS["pad_operator_headers"]
        )
        # business_safety (p5) beats business_constraint (p6).
        validate_error(resp, ApiErrorId.ERR_PERMIT_SUSPENDED)


class TestEffluentReadings:
    def test_double_concentration_breach_auto_suspends_permit(self, api):
        """PRD §3.7: "A reading whose measured concentration is strictly greater
        than the permit's `max_single_reading_mg_l` is flagged with `violation`
        true; a reading exactly at the limit is not a violation. A more severe
        threshold triggers automatic enforcement: a concentration strictly
        greater than twice the limit suspends the permit on the spot, moving it
        from `ACTIVE` to `SUSPENDED` and pushing the station into
        `PERMIT_SUSPENDED` posture."

        Design: Corner/cross_cutting_layers/double_concentration_breach_auto_suspends_permit
        """
        station, permit = create_station_with_permit(
            permit_overrides={
                "max_single_reading_mg_l": 100,
                "rolling_window_days": 7,
                "rolling_window_max_liters": 100000,
            }
        )

        # Reading exactly at the limit: violation false.
        payload = create_effluent_reading_payload(
            measured_at="2026-05-01T00:00:00Z",
            concentration_mg_l=100,
            volume_liters=10,
        )
        resp = api.create_effluent_reading(
            permit["id"], payload, TEST_USERS["environmental_officer_headers"]
        )
        reading1 = validate_success(resp, expected_status=201)
        assert reading1["violation"] is False

        # Reading at 250 (> 2*100): violation true, permit auto-suspended.
        payload = create_effluent_reading_payload(
            measured_at="2026-05-01T01:00:00Z",
            concentration_mg_l=250,
            volume_liters=10,
        )
        resp = api.create_effluent_reading(
            permit["id"], payload, TEST_USERS["environmental_officer_headers"]
        )
        reading2 = validate_success(resp, expected_status=201)
        assert reading2["violation"] is True

        resp = api.get_discharge_permit(
            permit["id"], TEST_USERS["environmental_officer_headers"]
        )
        assert validate_success(resp)["status"] == "SUSPENDED"

        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["posture"] == "PERMIT_SUSPENDED"

    def test_permit_rolling_window_aggregate_capacity(self, api):
        """PRD §3.7: "Consider the closed trailing window from
        `rolling_window_days` before the new reading's `measured_at` up to and
        including `measured_at` itself. Summing the `volume_liters` of every
        existing reading on the same permit whose `measured_at` falls inside
        that window, then adding the new reading's `volume_liters`: if the
        total exceeds `rolling_window_max_liters`, the reading is rejected with
        `ERR_PERMIT_VOLUME_EXCEEDED`. Only the window sum matters; pairwise
        spacing of readings within the window is irrelevant."

        Design: Difficulty/resource_temporal_overlap/permit_rolling_window_aggregate_capacity
        """
        station, permit = create_station_with_permit(
            permit_overrides={
                "effective_from": "2026-04-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
                "max_single_reading_mg_l": 100,
                "rolling_window_days": 7,
                "rolling_window_max_liters": 10000,
            }
        )
        eo = TEST_USERS["environmental_officer_headers"]

        # Existing readings: 6000 + 3500 = 9500.
        api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-01T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=6000,
            ),
            eo,
        )
        api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-03T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=3500,
            ),
            eo,
        )

        # 600 L would push to 10100 > 10000: rejected.
        resp = api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-05T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=600,
            ),
            eo,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_VOLUME_EXCEEDED)

        # 400 L brings to 9900: accepted.
        resp = api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-05T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=400,
            ),
            eo,
        )
        validate_success(resp, expected_status=201)

        # 100 L brings to exactly 10000: accepted (not > cap).
        resp = api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-05T01:00:00Z",
                concentration_mg_l=10,
                volume_liters=100,
            ),
            eo,
        )
        validate_success(resp, expected_status=201)


class TestEffluentWindowEdgeCases:
    def test_permit_rolling_window_exact_capacity_passes(self, api):
        """PRD §3.7: "if the total exceeds `rolling_window_max_liters`, the
        reading is rejected with `ERR_PERMIT_VOLUME_EXCEEDED`." A total exactly
        equal to the cap does not exceed it.

        Design: Difficulty/resource_temporal_overlap/permit_rolling_window_aggregate_capacity
        """
        station, permit = create_station_with_permit(
            permit_overrides={
                "effective_from": "2026-04-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
                "max_single_reading_mg_l": 100,
                "rolling_window_days": 7,
                "rolling_window_max_liters": 10000,
            }
        )
        eo = TEST_USERS["environmental_officer_headers"]

        # Fill to exactly 10000 in two readings.
        api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-01T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=6000,
            ),
            eo,
        )
        api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-03T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=4000,
            ),
            eo,
        )

        # A further 1 L would exceed: rejected.
        resp = api.create_effluent_reading(
            permit["id"],
            create_effluent_reading_payload(
                measured_at="2026-05-05T00:00:00Z",
                concentration_mg_l=10,
                volume_liters=1,
            ),
            eo,
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_VOLUME_EXCEEDED)


class TestWeatherEventLifecycle:
    def test_weather_reintensification_cycle(self, api):
        """PRD §3.2: "Activation moves a `FORECASTED` event to `ACTIVE`. Ending
        an `ACTIVE` event moves it to `ENDED` and stamps `ended_at` with the
        current logical clock. Storms re-intensify: activating an `ENDED` event
        returns it to `ACTIVE` and clears `ended_at` back to null, forming a
        deliberate `ACTIVE → ENDED → ACTIVE` cycle."

        Design: Difficulty/non_linear_state_machine/weather_reintensification_cycle
        """
        station = create_station()
        event = create_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="LIGHT",
            severity="LEVEL_1",
        )
        assert event["status"] == "FORECASTED"

        # Activate.
        resp = api.activate_weather_event(
            event["id"], TEST_USERS["station_admin_headers"]
        )
        assert validate_success(resp)["status"] == "ACTIVE"

        # End.
        resp = api.end_weather_event(
            event["id"], TEST_USERS["station_admin_headers"]
        )
        ended = validate_success(resp)
        assert ended["status"] == "ENDED"
        # PRD §3.2 stamps ended_at with the current logical clock, which
        # reads 2026-05-01T00:00:00Z; §2.4 renders timestamps with three
        # fractional digits. Compare instants, not string form.
        assert _parse_ts(ended["ended_at"]) == _parse_ts("2026-05-01T00:00:00Z")

        # Re-activate (re-intensification).
        resp = api.activate_weather_event(
            event["id"], TEST_USERS["station_admin_headers"]
        )
        reactivated = validate_success(resp)
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["ended_at"] is None

    def test_weather_forecasted_end_cancels(self, api):
        """PRD §3.2: "Ending a `FORECASTED` event — a storm that never
        materialized — moves it to `CANCELLED`, which is terminal, and
        likewise stamps `ended_at`."

        Design: Difficulty/non_linear_state_machine/weather_reintensification_cycle
        """
        station = create_station()
        event = create_weather_event(
            station["id"],
            precip_type="SNOW",
            precip_rate="LIGHT",
            severity="LEVEL_1",
        )
        assert event["status"] == "FORECASTED"

        # Ending a FORECASTED event cancels it.
        resp = api.end_weather_event(
            event["id"], TEST_USERS["station_admin_headers"]
        )
        ended = validate_success(resp)
        assert ended["status"] == "CANCELLED"
        # PRD §3.2 stamps ended_at with the current logical clock, which
        # reads 2026-05-01T00:00:00Z; §2.4 renders timestamps with three
        # fractional digits. Compare instants, not string form.
        assert _parse_ts(ended["ended_at"]) == _parse_ts("2026-05-01T00:00:00Z")

    def test_weather_severity_drives_required_crew(self, api):
        """PRD §3.2: "Its staffing requirement is fixed by severity and recorded
        as `required_crew_count`: a `LEVEL_1` event requires 4 crew, `LEVEL_2`
        requires 8, and `LEVEL_3` requires 14. The event's `staffing_status` is
        `ADEQUATE` when the assigned crew count meets or exceeds the required
        count, and `SHORT` otherwise."

        Design: Corner/calculations/weather_severity_drives_required_crew
        """
        station = create_station()
        event = create_weather_event(
            station["id"],
            precip_type="FREEZING_RAIN",
            precip_rate="MODERATE",
            severity="LEVEL_2",
        )
        assert event["required_crew_count"] == 8
        assert event["staffing_status"] == "SHORT"
        assert event["assigned_crew_count"] == 0

        # Escalate to 5: still SHORT.
        resp = api.escalate_weather_event(
            event["id"],
            escalate_payload(5),
            TEST_USERS["station_admin_headers"],
        )
        event = validate_success(resp)
        assert event["staffing_status"] == "SHORT"
        assert event["escalation_level"] == 1

        # Escalate to 8: ADEQUATE.
        resp = api.escalate_weather_event(
            event["id"],
            escalate_payload(8),
            TEST_USERS["station_admin_headers"],
        )
        event = validate_success(resp)
        assert event["staffing_status"] == "ADEQUATE"
        assert event["escalation_level"] == 2
