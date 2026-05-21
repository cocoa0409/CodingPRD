"""11-hour driving limit — PRD §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ELEVEN_HOUR_BASE_MINUTES,
    ApiErrorId,
    TEST_USERS,
    add_minutes,
    add_seconds,
    advance_clock_to_iso,
    create_duty_event_payload,
    declare_adverse_conditions,
    get_server_clock_iso,
    make_driver_headers,
    post_driving,
    post_duty_event,
    setup_after_10h_break,
    setup_driving_at_exact_660_minutes,
    validate_error,
    validate_success,
)


# ===========================================================================
# 11-hour limit boundary — PRD §3.4
# ===========================================================================
class TestElevenHourLimit:

    def test_driving_at_exact_660_minutes_rejected(self, api):
        """PRD §3.4: "The available driving minutes remaining is the
        cap minus the accumulated driving minutes since the break;
        if the result is zero or fewer minutes when the event is
        being written, the request is rejected with
        `ERR_ELEVEN_HOUR_LIMIT_EXCEEDED`."

        Claim: at exactly 660 driving minutes since the qualifying
        break, the next DRIVING event finds minutes_remaining == 0
        (zero is not greater than zero) and is rejected with
        ERR_ELEVEN_HOUR_LIMIT_EXCEEDED.
        """
        state = setup_driving_at_exact_660_minutes(
            break_end_iso="2026-06-01T10:00:00.000Z",
        )
        driver, vehicle = state["driver"], state["vehicle"]
        # Attempt to drive again 1 second after the closing event.
        attempt_iso = add_seconds(state["last_event_time"], 1)
        advance_clock_to_iso(attempt_iso)
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=2000.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ELEVEN_HOUR_LIMIT_EXCEEDED.value)

    def test_driving_at_659_minutes_succeeds(self, api):
        """PRD §3.4: "The available driving minutes remaining is the
        cap minus the accumulated driving minutes since the break; if
        the result is zero or fewer minutes when the event is being
        written, the request is rejected with
        `ERR_ELEVEN_HOUR_LIMIT_EXCEEDED`."

        Claim: at 659 driving minutes since the qualifying break,
        minutes_remaining == 1 > 0 and the next DRIVING event is
        accepted.
        """
        # Build same recipe but close DRIVING after 659 minutes.
        break_end = "2026-06-02T10:00:00.000Z"
        state = setup_after_10h_break(break_end_iso=break_end)
        driver, vehicle = state["driver"], state["vehicle"]
        # Drive starting at break_end + 1s.
        drive_start = add_seconds(break_end, 1)
        post_driving(
            driver, vehicle,
            event_time=drive_start, odometer_miles=1000.0,
        )
        # Close DRIVING after 659 minutes.
        close_iso = add_minutes(drive_start, 659)
        advance_clock_to_iso(add_seconds(close_iso, 60))
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=close_iso, vehicle_id=vehicle["id"],
            odometer_miles=1100.0,
        )
        # Now attempt DRIVING again immediately after — 1 minute
        # remaining.
        attempt_iso = add_seconds(close_iso, 1)
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=1101.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["new_status"] == "DRIVING"


# ===========================================================================
# Adverse-conditions extension lifts the 11-hour cap — PRD §3.4
# ===========================================================================
class TestElevenHourAdverseExtension:

    def test_with_active_exemption_driving_past_660_succeeds(self, api):
        """PRD §3.4: "The driving cap is 660 minutes (eleven hours) by
        default; if and only if the duty event is being written with
        an `adverse_conditions_exemption_id` referencing an `ACTIVE`
        exemption attached to the current 14-hour window, the cap is
        extended by an additional 120 minutes (two hours), to 780
        minutes."

        Claim: at 660 driving minutes since the break, supplying an
        ACTIVE exemption id on the next DRIVING event raises the cap
        to 780 and the event is accepted.
        """
        state = setup_driving_at_exact_660_minutes(
            break_end_iso="2026-06-03T10:00:00.000Z",
        )
        driver, vehicle = state["driver"], state["vehicle"]
        # Declare adverse conditions; declared_at must be within
        # current 14-hour window — i.e., relative to the first
        # on-duty event after the break — which is the DRIVING
        # event at break_end + 1s. The 14-hour window cap is 840
        # minutes; we are at 660 minutes since the break, which is
        # well inside the window.
        next_iso = add_seconds(state["last_event_time"], 5)
        advance_clock_to_iso(next_iso)
        exemption = declare_adverse_conditions(
            driver, declared_at=next_iso,
            reason="Heavy fog on I-5 reducing visibility below 200ft.",
        )
        assert exemption["status"] == "ACTIVE"
        # Now attempt DRIVING with the exemption id.
        attempt_iso = add_seconds(next_iso, 5)
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=2000.0,
            adverse_conditions_exemption_id=exemption["id"],
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["new_status"] == "DRIVING"
