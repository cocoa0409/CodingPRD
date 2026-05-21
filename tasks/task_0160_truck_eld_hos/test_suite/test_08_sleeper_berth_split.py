"""Sleeper-berth split — PRD §3.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_minutes,
    add_seconds,
    advance_clock_to_iso,
    create_duty_event_payload,
    make_driver_headers,
    post_duty_event,
    setup_full_stack,
    setup_sleeper_berth_pair_eight_two,
    validate_error,
    validate_success,
)


# ===========================================================================
# Insufficient rest — PRD §3.5
# ===========================================================================
class TestInsufficientRest:

    def test_sleeper_to_driving_without_pair_rejected(self, api):
        """PRD §3.5: "Going from `SLEEPER_BERTH` to `DRIVING` is
        admissible if the continuous OFF_DUTY-plus-SLEEPER_BERTH
        minutes ending at `event_time` are at least 600, or if a
        qualifying sleeper-berth pair exists; if neither condition
        holds, the request is rejected with `ERR_INSUFFICIENT_REST`."

        Claim: a SLEEPER_BERTH → DRIVING transition after only a
        short rest (well below 600 minutes and with no qualifying
        pair) fails with ERR_INSUFFICIENT_REST.
        """
        anchor = "2026-07-10T00:00:00.000Z"
        advance_clock_to_iso(anchor)
        state = setup_full_stack(home_terminal_timezone="UTC")
        driver, vehicle = state["driver"], state["vehicle"]
        # 1) Need to first reach DRIVING legitimately. Drive a bit so
        # driving_minutes accumulate, then SLEEPER for less than 10h,
        # then attempt DRIVING.
        # Actually simpler: start OFF_DUTY → SLEEPER_BERTH for ~30 min
        # then attempt DRIVING. The driver's first DRIVING event has
        # no prior DRIVING, so the qualifying-break check at the
        # FIRST DRIVING attempt looks at the OFF/SB run BEFORE that
        # attempt — which is the freshly-bound driver's existence
        # since OFF_DUTY is the initial state. To make the rule fire
        # we must put the driver into SLEEPER_BERTH and then attempt
        # DRIVING with < 600 minutes of OFF+SB AND no qualifying pair.
        #
        # The transition rule fires on SLEEPER_BERTH → DRIVING. We
        # need:
        #   - first event: OFF_DUTY at anchor + 1s
        #   - second event: DRIVING at anchor + 60s  (first DRIVING —
        #     the qualifying-break check before this depends on
        #     pre-anchor OFF/SB which is implementer-specific. To
        #     avoid that ambiguity, we instead exercise:
        #     OFF_DUTY → DRIVING → SLEEPER_BERTH → DRIVING.)
        # 1: OFF_DUTY at anchor + 1s
        post_duty_event(driver, new_status="OFF_DUTY",
                        event_time=add_seconds(anchor, 1))
        # 2: DRIVING after a fresh-driver gap — implementations may
        # accept this since no prior driving exists. Use enough wall
        # clock to be unambiguous.
        # Wait 600 minutes of OFF_DUTY first so the qualifying break
        # check is satisfied for the first DRIVING attempt.
        advance_clock_to_iso(add_minutes(anchor, 605))
        post_duty_event(
            driver, new_status="DRIVING",
            event_time=add_minutes(anchor, 605),
            vehicle_id=vehicle["id"], odometer_miles=1000.0,
        )
        # 3: SLEEPER_BERTH after only 30 minutes of driving.
        sb_iso = add_minutes(anchor, 635)
        post_duty_event(
            driver, new_status="SLEEPER_BERTH",
            event_time=sb_iso,
        )
        # 4: DRIVING attempt 30 minutes later — only 30 minutes of
        # SLEEPER_BERTH have accrued. No pair exists.
        attempt_iso = add_minutes(sb_iso, 30)
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
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REST.value)


# ===========================================================================
# Qualifying pair — PRD §3.5
# ===========================================================================
class TestSleeperBerthPairQualifies:

    def test_eight_two_split_qualifies(self, api):
        """PRD §3.5: "An `EIGHT_TWO_SPLIT` is a long leg of at least
        480 minutes paired with a short leg in the half-open range
        from 120 to 180 minutes - eight hours of `SLEEPER_BERTH` plus
        two hours of OFF_DUTY-or-SLEEPER_BERTH."

        Claim: a 480-minute SLEEPER_BERTH long leg paired with a
        preceding 120-minute OFF_DUTY short leg qualifies the pair;
        a DRIVING transition at the end of the long leg succeeds.
        """
        state = setup_sleeper_berth_pair_eight_two(
            anchor_iso="2026-07-15T00:00:00.000Z",
        )
        driver, vehicle = state["driver"], state["vehicle"]
        attempt_iso = add_seconds(state["drive_iso"], 1)
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=1000.0,
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["new_status"] == "DRIVING"
        assert data["edit_state"] == "ACTIVE"
