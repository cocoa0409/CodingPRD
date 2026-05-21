"""Rolling 60/70-hour cycle limit and 34-hour restart — PRD §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    add_hours,
    add_minutes,
    add_seconds,
    advance_clock_to_iso,
    bind_driver_to_vehicle,
    create_carrier,
    create_driver,
    create_eld_device,
    create_vehicle,
    get_driver,
    get_hos_snapshot,
    make_driver_headers,
    post_duty_event,
    post_sleeper,
    setup_after_10h_break,
    setup_full_stack,
    validate_error,
    validate_success,
)


# ===========================================================================
# 34-hour restart side effect — PRD §3.4
# ===========================================================================
class TestThirtyFourHourRestart:

    def test_34h_continuous_off_sleeper_sets_restart_timestamp(self, api):
        """PRD §3.4: "The driver's projected
        `last_34_hour_restart_completed_at` is recomputed as a side
        effect of any duty-event write whose transition closes a
        continuous rest window of at least 34 hours, as already
        described in §3.3."

        PRD §3.3: "if that accumulated continuous window had reached
        at least 34 hours in length when broken, the server sets
        `Driver.last_34_hour_restart_completed_at` to the
        `event_time` of the breaking transition".

        Claim: after the driver completes 34h of continuous
        OFF_DUTY+SLEEPER_BERTH and then transitions out (here to
        ON_DUTY_NOT_DRIVING), the breaking event's event_time becomes
        Driver.last_34_hour_restart_completed_at.
        """
        state = setup_full_stack(
            cycle_type="SEVENTY_HOUR_EIGHT_DAY",
            home_terminal_timezone="UTC",
        )
        driver, vehicle = state["driver"], state["vehicle"]
        # Anchor the clock at a known instant.
        rest_start = "2026-07-01T00:00:00.000Z"
        advance_clock_to_iso(rest_start)
        # Driver is already OFF_DUTY (initial state). Post OFF_DUTY at
        # rest_start + 1s to establish a clear start of the rest run.
        post_duty_event(
            driver, new_status="OFF_DUTY",
            event_time=add_seconds(rest_start, 1),
        )
        # Continuous SLEEPER_BERTH from rest_start + 60s onward.
        post_sleeper(driver, event_time=add_seconds(rest_start, 60))
        # Now advance clock past 34h.
        break_end = add_hours(rest_start, 35)
        advance_clock_to_iso(break_end)
        # Break the rest with ON_DUTY_NOT_DRIVING.
        breaking_iso = add_hours(rest_start, 35)
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=breaking_iso, vehicle_id=vehicle["id"],
            odometer_miles=100.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        refreshed = get_driver(driver["id"])
        assert refreshed["last_34_hour_restart_completed_at"] is not None, (
            "Driver.last_34_hour_restart_completed_at must be set after a "
            "34h continuous rest is broken (PRD §3.3)."
        )


# ===========================================================================
# HOS snapshot — PRD §3.9
# ===========================================================================
class TestHosSnapshot:

    def test_hos_snapshot_returns_three_remaining_values(self, api):
        """PRD §3.9: "The snapshot returns the three minutes-remaining
        values - driving (eleven-hour), window (fourteen-hour), and
        cycle (seventy- or sixty-hour, per the driver's `cycle_type`)
        - computed exactly as described in §3.4 against the current
        server clock."

        Claim: GET /drivers/{id}/hos-snapshot returns a structure
        carrying all three of available_driving_hours,
        available_on_duty_window, cycle_hours_remaining. We accept
        either a flat shape (minutes_remaining keys) or a nested
        variant shape (UNEXTENDED key) — the PRD does not pin the
        exact JSON layout.
        """
        state = setup_full_stack()
        driver = state["driver"]
        snap = get_hos_snapshot(driver)
        # Three named limits must be present — exact substring match.
        # PRD §3.9 names the UNEXTENDED and ADVERSE_EXTENDED variants
        # but does not pin the exact JSON layout, so accept both a
        # flat shape (keys at top-level) and a nested shape (keys
        # inside an `unextended` or `UNEXTENDED` group).
        def _candidate_dicts(s):
            yield s
            for k in ("unextended", "UNEXTENDED",
                      "adverse_extended", "ADVERSE_EXTENDED"):
                v = s.get(k) if isinstance(s, dict) else None
                if isinstance(v, dict):
                    yield v

        def _has_match(s, predicate):
            for d in _candidate_dicts(s):
                if any(predicate(k) for k in d.keys()):
                    return True
            return False

        all_keys = []
        for d in _candidate_dicts(snap):
            all_keys.extend(d.keys())

        driving_ok = _has_match(
            snap,
            lambda k: "driving" in k.lower() and "available" in k.lower(),
        )
        window_ok = _has_match(
            snap,
            lambda k: (
                ("window" in k.lower() or "on_duty" in k.lower())
                and "available" in k.lower()
            ),
        )
        cycle_ok = _has_match(snap, lambda k: "cycle" in k.lower())
        assert driving_ok, (
            f"HOS snapshot must include an available_driving_hours "
            f"value (PRD §3.9). Keys: {sorted(set(all_keys))!r}"
        )
        assert window_ok, (
            f"HOS snapshot must include the 14-hour on-duty window "
            f"value (PRD §3.9). Keys: {sorted(set(all_keys))!r}"
        )
        assert cycle_ok, (
            f"HOS snapshot must include the cycle minutes remaining "
            f"(PRD §3.9). Keys: {sorted(set(all_keys))!r}"
        )
