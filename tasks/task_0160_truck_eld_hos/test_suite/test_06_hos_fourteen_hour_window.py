"""14-hour on-duty window — PRD §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    add_minutes,
    add_seconds,
    advance_clock_to_iso,
    create_duty_event_payload,
    make_driver_headers,
    post_duty_event,
    setup_after_10h_break,
    validate_error,
)


# ===========================================================================
# 14-hour window — PRD §3.4
# ===========================================================================
class TestFourteenHourWindow:

    def test_event_at_or_beyond_840_minutes_rejected(self, api):
        """PRD §3.4: "the elapsed wall-clock minutes from that window
        start to the new `event_time` is compared to a base cap of
        840 minutes (fourteen hours) ... If the wall-clock elapsed
        minutes equal or exceed the cap, the request is rejected with
        `ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED`."

        Claim: a DRIVING event 840 wall-clock minutes after the first
        on-duty event after the qualifying break is rejected with
        ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED.
        """
        break_end = "2026-06-10T10:00:00.000Z"
        state = setup_after_10h_break(break_end_iso=break_end)
        driver, vehicle = state["driver"], state["vehicle"]
        # First on-duty event right after the break — opens the window.
        window_start = add_seconds(break_end, 1)
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=window_start, vehicle_id=vehicle["id"],
            odometer_miles=1000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Attempt a DRIVING event exactly 840 wall-clock minutes later.
        attempt_iso = add_minutes(window_start, 840)
        advance_clock_to_iso(add_seconds(attempt_iso, 60))
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=1100.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED.value,
        )

    def test_off_duty_minutes_consume_window(self, api):
        """PRD §3.4: "Critically, the 14-hour window measures
        wall-clock elapsed time and not on-duty accumulated time:
        OFF_DUTY, SLEEPER_BERTH, and PERSONAL_CONVEYANCE intervals
        all consume the window even though they do not contribute to
        on-duty totals."

        Claim: after opening the 14-hour window with one on-duty
        event, OFF_DUTY intervals still consume wall-clock time —
        a subsequent DRIVING event at window_start + 840 minutes is
        rejected even though most of the elapsed time was OFF_DUTY.

        Setup must avoid creating any continuous OFF_DUTY+SLEEPER_BERTH
        run of >= 600 minutes inside the 14-hour window (per PRD §3.4
        the window-start anchor moves forward when a new qualifying
        break completes). We split the OFF_DUTY into two chunks of
        < 600 min separated by a brief ON_DUTY_NOT_DRIVING marker.
        """
        break_end = "2026-06-11T10:00:00.000Z"
        state = setup_after_10h_break(break_end_iso=break_end)
        driver, vehicle = state["driver"], state["vehicle"]
        # Open the window with an ON_DUTY_NOT_DRIVING event.
        window_start = add_seconds(break_end, 1)
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=window_start, vehicle_id=vehicle["id"],
            odometer_miles=1000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # OFF_DUTY 1 minute later — accrues wall-clock but not on-duty.
        post_duty_event(
            driver, new_status="OFF_DUTY",
            event_time=add_minutes(window_start, 1),
        )
        # Briefly return to ON_DUTY_NOT_DRIVING after 400 minutes so the
        # continuous rest run never reaches 600 min.
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=add_minutes(window_start, 401),
            vehicle_id=vehicle["id"],
            odometer_miles=1000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Back OFF_DUTY one minute later — the second OFF_DUTY chunk
        # runs ~439 minutes (window_start+402 .. window_start+840).
        post_duty_event(
            driver, new_status="OFF_DUTY",
            event_time=add_minutes(window_start, 402),
        )
        # 840 wall-clock minutes have now passed.
        attempt_iso = add_minutes(window_start, 840)
        advance_clock_to_iso(add_seconds(attempt_iso, 60))
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=1001.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_FOURTEEN_HOUR_WINDOW_EXCEEDED.value,
        )
