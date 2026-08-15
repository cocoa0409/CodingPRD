"""Observing events: scheduling gates, confirmation gates, weather
auto-cancel, completion cascade, unschedule cycle, OCC on confirm."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_confirmed_event,
    create_event,
    create_group_booking,
    create_member_with_paid_dues,
    create_operator_assignment_payload,
    create_scheduled_event,
    create_certification,
    create_telescope,
    get_success_data,
    invite_and_accept_operator,
    make_member_headers,
    set_clock,
    setup_member_with_cert_and_scope,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["event_coordinator_headers"]
OFFICER = TEST_USERS["club_officer_headers"]


class TestMoonGate:
    def test_moon_gate_boundary_40_passes_41_fails(self, api):
        """PRD: "For a `PUBLIC_NIGHT`, the moon must cooperate:
        `moon_illumination_pct` of at most 40 is required, and anything
        brighter is rejected with `ERR_MOON_TOO_BRIGHT` (HTTP 422)."

        Design: Corner/validations/moon_gate_boundary_40_passes_41_fails
        """
        e40 = create_event(title="M40", moon_illumination_pct=40)
        e41 = create_event(title="M41", moon_illumination_pct=41,
                           window_start="2026-08-11T01:00:00Z",
                           window_end="2026-08-11T05:00:00Z")

        ok = validate_success(api.schedule_event(e40["id"], COORDINATOR))
        assert ok["status"] == "SCHEDULED", (
            "moon_illumination_pct == 40 is at the inclusive limit")

        resp = api.schedule_event(e41["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_MOON_TOO_BRIGHT)
        assert resp.status_code == 422


class TestSolarDaylightGate:
    def test_solar_session_night_window_rejected(self, api):
        """PRD: "For a `SOLAR_SESSION`, the window must lie entirely within
        civil daylight for the observatory site: the server consults a fixed
        daylight table in which every date's civil daylight runs from 06:00Z
        inclusive to 20:00Z exclusive of the same UTC date, so the event's
        `window_start` must be at or after 06:00Z and its `window_end` at or
        before 20:00Z of that date; a window straying outside is rejected
        with `ERR_NOT_DAYLIGHT_WINDOW` (HTTP 422)."

        Design: Corner/validations/solar_session_night_window_rejected
        """
        solar = create_event(title="SolarNight", event_kind="SOLAR_SESSION",
                             window_start="2026-08-10T01:00:00Z",
                             window_end="2026-08-10T05:00:00Z",
                             moon_illumination_pct=10)
        resp = api.schedule_event(solar["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_NOT_DAYLIGHT_WINDOW)
        assert resp.status_code == 422

        public = create_event(title="PubNight", event_kind="PUBLIC_NIGHT",
                              window_start="2026-08-10T01:00:00Z",
                              window_end="2026-08-10T05:00:00Z",
                              moon_illumination_pct=10)
        ok = validate_success(api.schedule_event(public["id"], COORDINATOR))
        assert ok["status"] == "SCHEDULED", (
            "The daylight gate does not apply to PUBLIC_NIGHT")


class TestTerminalEventLockdown:
    def test_terminal_event_cancel_lockdown(self, api):
        """PRD: "state-machine legality — the target resource is in a state
        from which the requested transition exists, otherwise
        `ERR_INVALID_STATE`"
        PRD: "After the window closes — that is, once the logical clock is
        at or after `window_end` — the coordinator completes the event,
        moving `CONFIRMED → COMPLETED`."

        Design: Corner/state_machines/terminal_event_cancel_lockdown
        """
        event = create_scheduled_event(title="Dead Event")
        get_success_data(api.cancel_event(event["id"], "OTHER", COORDINATOR))

        resp = api.complete_event(event["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

        fetched = validate_success(api.get_observing_event(event["id"], COORDINATOR))
        assert fetched["status"] == "CANCELLED", (
            "A CANCELLED event accepts no further transitions")


class TestUnscheduleCycle:
    def test_unschedule_returns_event_to_draft(self, api):
        """PRD: "A scheduled event can be sent back for replanning, moving
        `SCHEDULED → DRAFT` with no side effects."
        PRD: "Scheduling moves `DRAFT → SCHEDULED`"

        Design: Corner/endpoints/unschedule_returns_event_to_draft
        """
        event = create_scheduled_event(title="Replan")
        unscheduled = validate_success(
            api.unschedule_event(event["id"], COORDINATOR))
        assert unscheduled["status"] == "DRAFT"

        rescheduled = validate_success(
            api.schedule_event(event["id"], COORDINATOR))
        assert rescheduled["status"] == "SCHEDULED", (
            "The DRAFT <-> SCHEDULED cycle is traversable")


class TestWeatherAutoCancel:
    def test_weather_check_auto_cancels_confirmed_event(self, api):
        """PRD: "when a weather-check records a `weather_cancellation_pct`
        of 70 or higher on an event that is currently `CONFIRMED`, the event
        auto-cancels with `cancellation_reason` `WEATHER`, applying the same
        cascades as a manual cancellation."
        PRD: "Cancelling from `CONFIRMED` withdraws the same assignments and
        cancels only the `CONFIRMED` group bookings"

        Design: Corner/state_machines/weather_check_auto_cancels_confirmed_event
        """
        event, assignment, op, _scope = create_confirmed_event(
            title="Wx PN", window_start="2026-08-20T01:00:00Z",
            window_end="2026-08-20T05:00:00Z", moon_illumination_pct=10)
        booking = create_group_booking(event["id"], op, party_size=8,
                                       group_name="Wx Group")
        get_success_data(api.confirm_group_booking(booking["id"], COORDINATOR))

        resp = validate_success(
            api.weather_check_event(event["id"], 75, COORDINATOR))
        assert resp["status"] == "CANCELLED"
        assert resp["cancellation_reason"] == "WEATHER"

        asg_after = validate_success(
            api.get_operator_assignment(assignment["id"], COORDINATOR))
        assert asg_after["status"] == "WITHDRAWN", (
            "Auto-cancel withdraws CONFIRMED operator assignments")
        booking_after = validate_success(
            api.get_group_visit_booking(booking["id"], COORDINATOR))
        assert booking_after["status"] == "CANCELLED", (
            "Auto-cancel cancels CONFIRMED group bookings")


class TestEventCompletionCascade:
    def test_event_complete_cascades_bookings(self, api):
        """PRD: "Completion cascades to group bookings: every booking in
        `CONFIRMED` moves to `COMPLETED`."
        PRD: "After the window closes — that is, once the logical clock is
        at or after `window_end` — the coordinator completes the event,
        moving `CONFIRMED → COMPLETED`."

        Design: Corner/state_machines/event_complete_cascades_bookings
        """
        event, _asg, op, _scope = create_confirmed_event(
            title="EC PN", window_start="2026-08-05T01:00:00Z",
            window_end="2026-08-05T05:00:00Z", moon_illumination_pct=8,
            equipment_class="SCT")
        b1 = create_group_booking(event["id"], op, party_size=5, group_name="B1")
        get_success_data(api.confirm_group_booking(b1["id"], COORDINATOR))
        b2 = create_group_booking(event["id"], op, party_size=6, group_name="B2")

        set_clock("2026-08-05T06:00:00Z")
        completed = validate_success(api.complete_event(event["id"], COORDINATOR))
        assert completed["status"] == "COMPLETED"

        b1_after = validate_success(api.get_group_visit_booking(b1["id"], COORDINATOR))
        assert b1_after["status"] == "COMPLETED", (
            "CONFIRMED bookings cascade to COMPLETED")
        b2_after = validate_success(api.get_group_visit_booking(b2["id"], COORDINATOR))
        assert b2_after["status"] == "PENDING", (
            "PENDING bookings are not moved by the completion cascade")


class TestConfirmGateOrdering:
    def test_state_vs_business_temporal_on_confirm(self, api):
        """PRD: "(6) state-machine legality — the target resource is in a
        state from which the requested transition exists, otherwise
        `ERR_INVALID_STATE`; and only then (7+) the business rules in their
        domain-specific order"
        PRD: "Second, weather: the latest `weather_cancellation_pct` must be
        strictly below 70; at 70 or above the confirm is rejected with
        `ERR_WEATHER_RISK` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_confirm
        """
        event = create_scheduled_event(title="Dual Fail")
        get_success_data(api.weather_check_event(event["id"], 80, COORDINATOR))
        get_success_data(api.cancel_event(event["id"], "WEATHER", COORDINATOR))
        current = validate_success(api.get_observing_event(event["id"], COORDINATOR))

        resp = api.confirm_event(event["id"], current["version"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "State legality (step 6) precedes the weather business gate "
            "(step 7+) even though weather_cancellation_pct 80 also fails")

        after = validate_success(api.get_observing_event(event["id"], COORDINATOR))
        assert after["status"] == "CANCELLED"

    def test_weather_gate_fires_when_state_is_legal(self, api):
        """PRD: "Second, weather: the latest `weather_cancellation_pct`
        must be strictly below 70; at 70 or above the confirm is rejected
        with `ERR_WEATHER_RISK` (HTTP 422)."
        PRD: "First, operator coverage: `confirmed_operator_count` must be
        at least `min_operators` — exactly meeting the minimum passes, one
        short fails with `ERR_INSUFFICIENT_OPERATORS` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_confirm
        """
        event, _asg, _op, _scope = create_confirmed_event(
            title="Weather Then State",
            window_start="2026-08-21T01:00:00Z",
            window_end="2026-08-21T05:00:00Z")
        # Walk back to SCHEDULED by withdrawing the operator, then weather 80.
        get_success_data(api.withdraw_assignment(
            _asg["id"], make_member_headers(_op["id"])))
        get_success_data(api.weather_check_event(event["id"], 80, COORDINATOR))
        current = validate_success(api.get_observing_event(event["id"], COORDINATOR))
        assert current["status"] == "SCHEDULED"

        resp = api.confirm_event(event["id"], current["version"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_OPERATORS)
        assert resp.status_code == 422, (
            "Coverage (first business gate) precedes weather when both fail")


class TestEventConfirmOcc:
    def test_stale_event_version_on_confirm(self, api):
        """PRD: "If `expected_event_version` does not match the event's
        current `version`, the confirm is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD: "A successful accept recomputes the host event's
        `confirmed_operator_count` over the event's `CONFIRMED` assignments
        only — `INVITED`, `DECLINED`, `NO_SHOW`, and `WITHDRAWN` never count
        — and bumps the event's `version`"

        Design: Corner/cross_cutting_layers/stale_event_version_on_confirm
        """
        op, scope, _cert = setup_member_with_cert_and_scope(
            equipment_class="DOBSONIAN", member_name="OCC Eve")
        event = create_scheduled_event(
            title="OCC PN", window_start="2026-08-20T01:00:00Z",
            window_end="2026-08-20T05:00:00Z", moon_illumination_pct=10)
        pre_accept = validate_success(
            api.get_observing_event(event["id"], COORDINATOR))
        v1 = pre_accept["version"]

        assignment = invite_and_accept_operator(event["id"], op, scope)
        post_accept = validate_success(
            api.get_observing_event(event["id"], COORDINATOR))
        v2 = post_accept["version"]
        assert v2 > v1, "Accept bumps the event version via coverage recompute"

        stale = api.confirm_event(event["id"], v1, COORDINATOR)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

        ok = validate_success(api.confirm_event(event["id"], v2, COORDINATOR))
        assert ok["status"] == "CONFIRMED"
