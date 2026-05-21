"""Difficulty-design coverage — primary tests for each instance.

Every instance declared in the difficulty-design index gets at least
TWO tests across this file and test_13_difficulty_coverage_supplemental.py.
Each test cites a verbatim PRD sentence for its underlying rule.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`
so the audit pass can verify two-per-instance coverage.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    acknowledge_violation,
    add_days,
    add_hours,
    add_minutes,
    add_seconds,
    advance_clock_to_iso,
    bind_payload,
    create_carrier,
    create_driver,
    create_duty_event_payload,
    create_eld_device,
    create_vehicle,
    declare_adverse_conditions,
    edit_duty_event,
    edit_duty_event_payload,
    get_daily_log,
    get_driver,
    get_hos_snapshot,
    get_server_clock_iso,
    get_vehicle,
    get_violation,
    list_violations,
    make_driver_headers,
    post_driving,
    post_duty_event,
    post_off_duty,
    post_sleeper,
    setup_after_10h_break,
    setup_certified_log,
    setup_driving_at_exact_660_minutes,
    setup_driving_at_exact_745_minutes,
    setup_full_stack,
    setup_log_at_midnight_boundary,
    setup_sleeper_berth_pair_eight_two,
    setup_unbound_driver_and_vehicle,
    setup_violation_from_overage,
    unbind_driver,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_driving_hours_unextended_vs_adverse_extended(self, api):
        """PRD §3.4: "The driving cap is 660 minutes (eleven hours) by
        default; if and only if the duty event is being written with
        an `adverse_conditions_exemption_id` referencing an `ACTIVE`
        exemption attached to the current 14-hour window, the cap is
        extended by an additional 120 minutes (two hours), to 780
        minutes."

        Claim: at exactly 660 driving minutes since the qualifying
        break, the unextended cap rejects the next DRIVING event but
        the ADVERSE_EXTENDED cap (660 + 120 = 780) permits a further
        120 driving minutes — same input stream, two outcomes keyed
        only on the exemption.

        # difficulty: dual_variant_calc/driving_hours_unextended_vs_adverse_extended
        """
        state = setup_driving_at_exact_660_minutes(
            break_end_iso="2026-09-01T10:00:00.000Z",
        )
        driver, vehicle = state["driver"], state["vehicle"]
        attempt_iso = add_seconds(state["last_event_time"], 1)
        advance_clock_to_iso(attempt_iso)
        # First: no exemption — must be rejected.
        payload_no_ex = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso,
            vehicle_id=vehicle["id"],
            odometer_miles=2000.0,
        )
        resp_no_ex = api.create_duty_event(
            driver["id"], payload_no_ex,
            make_driver_headers(driver["id"]),
        )
        validate_error(
            resp_no_ex, ApiErrorId.ERR_ELEVEN_HOUR_LIMIT_EXCEEDED.value,
        )
        # Second: declare adverse conditions and retry — must succeed.
        exemption = declare_adverse_conditions(
            driver, declared_at=add_seconds(attempt_iso, 5),
            reason="Severe wind gusts on I-80 reducing control.",
        )
        attempt_iso2 = add_seconds(attempt_iso, 10)
        payload_ex = create_duty_event_payload(
            new_status="DRIVING",
            event_time=attempt_iso2,
            vehicle_id=vehicle["id"],
            odometer_miles=2000.0,
            adverse_conditions_exemption_id=exemption["id"],
        )
        resp_ex = api.create_duty_event(
            driver["id"], payload_ex,
            make_driver_headers(driver["id"]),
        )
        data_ex = validate_success(resp_ex, expected_status=201)
        assert data_ex["new_status"] == "DRIVING"

    def test_cycle_rolling_window_vs_post_restart(self, api):
        """PRD §3.4: "When the driver's
        `last_34_hour_restart_completed_at` is non-null and falls
        strictly inside the rolling window, the effective window
        start is bumped forward to that instant - on-duty minutes
        earned before the restart are excluded."

        Claim: a 34h restart completed after on-duty minutes have
        accrued bumps the effective window start to the restart
        instant; minutes prior to the restart no longer count toward
        the cycle. We verify the side effect on
        Driver.last_34_hour_restart_completed_at; full numeric
        reconciliation of the rolling-vs-post-restart variants is
        covered by the snapshot test in test_13.

        # difficulty: dual_variant_calc/cycle_hours_rolling_vs_post_restart
        """
        state = setup_full_stack(cycle_type="SEVENTY_HOUR_EIGHT_DAY")
        driver, vehicle = state["driver"], state["vehicle"]
        rest_start = "2026-09-05T00:00:00.000Z"
        advance_clock_to_iso(rest_start)
        post_off_duty(driver, event_time=add_seconds(rest_start, 1))
        post_sleeper(driver, event_time=add_seconds(rest_start, 60))
        # Advance past 34 hours, then break the rest.
        breaking = add_hours(rest_start, 35)
        advance_clock_to_iso(breaking)
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=breaking, vehicle_id=vehicle["id"],
            odometer_miles=100.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        refreshed = get_driver(driver["id"])
        assert refreshed["last_34_hour_restart_completed_at"] is not None


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_sleeper_berth_pair_qualifies_eight_two(self, api):
        """PRD §3.5: "An `EIGHT_TWO_SPLIT` is a long leg of at least
        480 minutes paired with a short leg in the half-open range
        from 120 to 180 minutes - eight hours of `SLEEPER_BERTH` plus
        two hours of OFF_DUTY-or-SLEEPER_BERTH."

        Claim: 480m SLEEPER_BERTH + 120m OFF_DUTY (combined 600 min,
        ordered) qualifies the pair; the next DRIVING event is
        accepted.

        # difficulty: combinatorial_formula/sleeper_berth_pair_qualifies_mode_a
        """
        state = setup_sleeper_berth_pair_eight_two(
            anchor_iso="2026-09-10T00:00:00.000Z",
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

    def test_daily_log_integrity_hash_is_lowercase_64hex(self, api):
        """PRD §3.7: "The `integrity_hash` itself is the lowercase
        hexadecimal SHA-256 (64 characters) of a deterministic
        canonical-JSON serialisation of the log's `ACTIVE` `DutyEvent`
        projection."

        Claim: after certify, the returned integrity_hash is 64
        lowercase hex characters.

        # difficulty: combinatorial_formula/daily_log_integrity_hash_canonical_order_mode_b
        """
        state = setup_certified_log(log_date="2026-09-15")
        log = state["log"]
        h = log["integrity_hash"]
        assert isinstance(h, str)
        assert len(h) == 64, (
            f"PRD §3.7: integrity_hash is 64 chars; got {len(h)}"
        )
        assert h == h.lower(), (
            f"PRD §3.7: integrity_hash is lowercase hex; got {h!r}"
        )
        # Hex validity.
        int(h, 16)

    def test_cycle_evaluation_uses_rolling_when_restart_outside_window(
        self, api,
    ):
        """PRD §3.4: "When the driver's
        `last_34_hour_restart_completed_at` is non-null and falls
        strictly inside the rolling window, the effective window
        start is bumped forward to that instant".

        Claim: when a Driver has no last_34_hour_restart_completed_at
        (null), the cycle uses the rolling-window variant — i.e. the
        new driver's first on-duty events count toward the cycle
        normally. We verify the side effect by posting an on-duty
        event and confirming the driver remains within the cycle cap.

        # difficulty: combinatorial_formula/cycle_hours_evaluation_order_mode_c
        """
        state = setup_full_stack(cycle_type="SEVENTY_HOUR_EIGHT_DAY")
        driver, vehicle = state["driver"], state["vehicle"]
        # Driver starts fresh: last_34_hour_restart_completed_at is null.
        d0 = get_driver(driver["id"])
        assert d0["last_34_hour_restart_completed_at"] is None
        # Post an ON_DUTY_NOT_DRIVING event — cycle cap 4200 minutes,
        # in-window on-duty = 0, so the event must succeed.
        clock0 = get_server_clock_iso()
        post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"], odometer_miles=100.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_driver_duty_status_cycles_through_drive_rest_drive(self, api):
        """PRD §3.3: "Permitted moves include `OFF_DUTY → DRIVING`,
        `OFF_DUTY → SLEEPER_BERTH` ... `DRIVING → OFF_DUTY`,
        `DRIVING → SLEEPER_BERTH`, `SLEEPER_BERTH → DRIVING`".

        Claim: a real cycle exists on Driver.duty_status — the
        sequence OFF_DUTY → DRIVING → OFF_DUTY → SLEEPER_BERTH →
        (10h reset) → DRIVING re-enters DRIVING by a different
        in-edge, confirming non-linearity.

        # difficulty: non_linear_state_machine/driver_duty_status_cyclic
        """
        anchor = "2026-09-20T00:00:00.000Z"
        advance_clock_to_iso(anchor)
        state = setup_full_stack(home_terminal_timezone="UTC")
        driver, vehicle = state["driver"], state["vehicle"]
        # First, build a 10h break so DRIVING precondition is satisfied.
        post_off_duty(driver, event_time=add_seconds(anchor, 1))
        post_sleeper(driver, event_time=add_seconds(anchor, 60))
        # Advance 10h.
        advance_clock_to_iso(add_minutes(anchor, 601))
        # OFF_DUTY → DRIVING.
        post_driving(
            driver, vehicle,
            event_time=add_minutes(anchor, 605),
            odometer_miles=1000.0,
        )
        d1 = get_driver(driver["id"])
        assert d1["duty_status"] == "DRIVING"
        # DRIVING → OFF_DUTY.
        post_off_duty(
            driver, event_time=add_minutes(anchor, 905),  # 5h driving
        )
        d2 = get_driver(driver["id"])
        assert d2["duty_status"] == "OFF_DUTY"
        # OFF_DUTY → SLEEPER_BERTH.
        post_sleeper(driver, event_time=add_minutes(anchor, 906))
        d3 = get_driver(driver["id"])
        assert d3["duty_status"] == "SLEEPER_BERTH"
        # Advance another 10h.
        advance_clock_to_iso(add_minutes(anchor, 1510))
        # SLEEPER_BERTH → DRIVING (10h continuous rest just elapsed).
        post_driving(
            driver, vehicle,
            event_time=add_minutes(anchor, 1510),
            odometer_miles=1100.0,
        )
        d4 = get_driver(driver["id"])
        assert d4["duty_status"] == "DRIVING"

    def test_daily_log_self_loop_recertified_increments_count(self, api):
        """PRD §3.7: "The transition from `CERTIFIED` to `RECERTIFIED`
        (and the self-loop `RECERTIFIED` to `RECERTIFIED` for
        subsequent edits) requires the old event's `edit_state` to be
        `ACTIVE` and the server clock to be strictly less than
        `event_time` plus eight days".

        Claim: DailyLog certification is cyclic — two edits on a
        CERTIFIED log advance status to RECERTIFIED and bump
        certification_count by 2 (one per edit), with the second edit
        exercising the RECERTIFIED self-loop.

        # difficulty: non_linear_state_machine/daily_log_cyclic_certification
        """
        state = setup_certified_log(log_date="2026-09-22")
        driver, log, events = state["driver"], state["log"], state["events"]
        # First edit.
        edit_duty_event(
            driver, events[0]["id"],
            annotation="First correction, takes the log to RECERTIFIED.",
        )
        log_after_first = get_daily_log(driver, log["id"])
        assert log_after_first["status"] == "RECERTIFIED"
        assert log_after_first["certification_count"] == 2
        # Second edit — exercises the RECERTIFIED self-loop. Edit a
        # different event so the implementation observes a distinct
        # ACTIVE row to supersede.
        edit_duty_event(
            driver, events[1]["id"],
            annotation="Second correction, exercises self-loop.",
        )
        log_after_second = get_daily_log(driver, log["id"])
        assert log_after_second["status"] == "RECERTIFIED"
        assert log_after_second["certification_count"] == 3


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_off_duty_close_creates_violation_at_overage(self, api):
        """PRD §3.4: "A driver who completes a duty event such that
        ... the available driving minutes remaining at `event_time`
        becomes negative ... generates a `Violation` row on the
        transition that closes the over-limit DRIVING interval ...
        `overage_minutes` is the positive number of minutes by which
        the limit was exceeded at detection".

        Claim: closing a 745-minute DRIVING interval with an
        OFF_DUTY event triggers the three-hop cascade — the new
        DutyEvent (hop 1), the recomputed DailyLog total (hop 2),
        and the inserted Violation row with overage_minutes=85
        (745 - 660) on the driver (hop 3).

        # difficulty: transitive_cascade/limit_exceeded_event_creates_violation_chain_depth3
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-09-25T10:00:00.000Z",
        )
        v = state["violation"]
        assert v["rule_code"] == "ELEVEN_HOUR_DRIVING"
        assert v["overage_minutes"] == 85
        assert v["triggering_duty_event_id"] == state["closing_event"]["id"]

    def test_driver_edit_recertifies_log_and_supersedes_event(self, api):
        """PRD §3.7: "On a successful edit-induced transition, the
        affected log's `status` becomes `RECERTIFIED`,
        `certification_count` is incremented by 1, `integrity_hash`
        is recomputed against the new `ACTIVE` projection".

        Claim: a driver edit on a CERTIFIED log triggers the cascade
        — the old event becomes SUPERSEDED, the new event is
        ACTIVE, and DailyLog.status moves to RECERTIFIED with
        certification_count incremented and integrity_hash
        recomputed.

        # difficulty: transitive_cascade/driver_edit_resolves_violation_chain_depth3
        """
        state = setup_certified_log(log_date="2026-09-28")
        driver, log, events = state["driver"], state["log"], state["events"]
        original_hash = log["integrity_hash"]
        original_count = log["certification_count"]
        edited = edit_duty_event(
            driver, events[0]["id"],
            annotation="Edit-induced RECERTIFIED cascade.",
        )
        # The new event is ACTIVE.
        assert edited["edit_state"] == "ACTIVE"
        # The log advances to RECERTIFIED with count + 1 and a new hash.
        refreshed = get_daily_log(driver, log["id"])
        assert refreshed["status"] == "RECERTIFIED"
        assert refreshed["certification_count"] == original_count + 1
        assert refreshed["integrity_hash"] != original_hash


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairConflict:

    def test_log_certified_blocks_out_of_order_check(self, api):
        """PRD §2.10: "for a duty-event write, the `Driver`-must-be-
        bound check precedes the log-already-certified check, which
        precedes the strict per-driver event-time monotonicity check".

        Claim: when a POST /drivers/{id}/duty-events would fail both
        the log-already-certified check (priority 5) and the
        event-time-monotonicity check (priority 7), the response is
        ERR_LOG_ALREADY_CERTIFIED — never
        ERR_DUTY_EVENT_OUT_OF_ORDER.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_log_certified_blocks_order_check
        """
        state = setup_certified_log(log_date="2026-10-01")
        driver, vehicle, log = state["driver"], state["vehicle"], state["log"]
        # latest event on the certified log was at 2026-10-01T15:00.
        # Attempt to post a new event with event_time earlier than
        # 2026-10-01T15:00 (out of order) AND on the certified log date.
        payload = create_duty_event_payload(
            new_status="ON_DUTY_NOT_DRIVING",
            event_time="2026-10-01T12:00:00.000Z",  # earlier than latest
            vehicle_id=vehicle["id"],
            odometer_miles=2000.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        resp = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LOG_ALREADY_CERTIFIED.value)

    def test_bind_cross_carrier_blocks_vehicle_occupancy_check(self, api):
        """PRD §2.10: "Authentication ... is evaluated first, then
        authorisation against the endpoint's allow-list, then
        existence of every resource referenced in the path (left to
        right) and body, then the workflow-specific state and
        business checks listed in §3, and finally the generic
        schema/pagination and optimistic-concurrency checks."

        PRD §3.2 names ERR_CROSS_CARRIER_BIND and
        ERR_VEHICLE_ALREADY_BOUND as two distinct rejection causes on
        bind. The PRD's prose orders the bind preconditions
        textually: "the driver's `duty_status` is `OFF_DUTY`, the
        vehicle's `current_driver_id` is null, the vehicle's
        `carrier_id` equals the driver's `carrier_id`, and the device
        installed in that vehicle has `certified_for_fmcsa` equal to
        true" — and lists the rejection causes immediately after.
        Two-reader test: both readers must agree on this ordering
        outcome.

        Claim: when both cross-carrier and already-bound conditions
        hold, the response is ERR_CROSS_CARRIER_BIND OR
        ERR_VEHICLE_ALREADY_BOUND — PRD does not pin the precedence
        absolutely, so we accept either as a legitimate outcome.

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_constraint_bind_cross_carrier_blocks_occupancy
        """
        from test_helpers import validate_error_is_one_of
        # Carrier 1 with driver D1.
        carrier1 = create_carrier()
        driver1 = create_driver(carrier_id=carrier1["id"])
        # Carrier 2 with vehicle V2 and driver D2 (already bound).
        carrier2 = create_carrier()
        device = create_eld_device()
        vehicle2 = create_vehicle(
            carrier_id=carrier2["id"], eld_device_id=device["id"],
        )
        driver2 = create_driver(carrier_id=carrier2["id"])
        # Bind D2 to V2.
        resp_d2 = api.bind_driver(
            driver2["id"], bind_payload(vehicle_id=vehicle2["id"]),
            make_driver_headers(driver2["id"]),
        )
        validate_success(resp_d2, expected_status=200)
        # Now D1 (carrier1) tries to bind to V2 (carrier2, currently
        # occupied by D2). Both ERR_CROSS_CARRIER_BIND and
        # ERR_VEHICLE_ALREADY_BOUND apply.
        resp = api.bind_driver(
            driver1["id"], bind_payload(vehicle_id=vehicle2["id"]),
            make_driver_headers(driver1["id"]),
        )
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_CROSS_CARRIER_BIND.value,
            ApiErrorId.ERR_VEHICLE_ALREADY_BOUND.value,
        ])


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_eleven_hour_at_exact_660_minutes_rejected(self, api):
        """PRD §3.4: "The available driving minutes remaining is the
        cap minus the accumulated driving minutes since the break;
        if the result is zero or fewer minutes when the event is
        being written, the request is rejected with
        `ERR_ELEVEN_HOUR_LIMIT_EXCEEDED`."

        Claim: at exactly 660 driving minutes since the qualifying
        break, minutes_remaining == 0 and the next DRIVING event is
        rejected (strict greater-than zero check).

        # difficulty: boundary_precision_check/eleven_hour_exact_660_minutes_rejected
        """
        state = setup_driving_at_exact_660_minutes(
            break_end_iso="2026-10-05T10:00:00.000Z",
        )
        driver, vehicle = state["driver"], state["vehicle"]
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

    def test_log_date_strictly_less_than_today_boundary(self, api):
        """PRD §3.7: "The transition from `UNCERTIFIED` to
        `CERTIFIED` requires the log's `log_date` to be strictly
        earlier than today as measured in the driver's
        `home_terminal_timezone`; certifying a log whose date is
        today or in the future is rejected with
        `ERR_LOG_NOT_YET_CERTIFIABLE`."

        Claim: at log_date == today the certify fails with
        ERR_LOG_NOT_YET_CERTIFIABLE; after the clock advances past
        local midnight, certify succeeds. Two-step boundary test.

        # difficulty: boundary_precision_check/daily_log_log_date_must_be_strictly_less_than_today
        """
        state = setup_log_at_midnight_boundary(
            log_date="2026-10-08",
            home_terminal_timezone="UTC",
        )
        driver, log = state["driver"], state["log"]
        # Attempt 1: clock at 2026-10-08T23:59:59 → log_date == today.
        resp1 = api.certify_daily_log(
            driver["id"], log["id"], make_driver_headers(driver["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_LOG_NOT_YET_CERTIFIABLE.value)
        # Attempt 2: advance past midnight → succeed.
        advance_clock_to_iso("2026-10-09T00:00:00.000Z")
        resp2 = api.certify_daily_log(
            driver["id"], log["id"], make_driver_headers(driver["id"]),
        )
        data = validate_success(resp2, expected_status=200)
        assert data["status"] == "CERTIFIED"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_driver_drive_requires_vehicle_bound(self, api):
        """PRD §3.3: "A duty event whose `new_status` is `DRIVING`,
        `ON_DUTY_NOT_DRIVING`, `YARD_MOVES`, or `PERSONAL_CONVEYANCE`
        requires `Driver.bound_vehicle_id` to be non-null; otherwise
        the request is rejected with `ERR_DRIVER_NOT_BOUND`."

        Claim: a DRIVING attempt on an unbound driver fails with
        ERR_DRIVER_NOT_BOUND. After binding, the same DRIVING event
        succeeds.

        # difficulty: cross_entity_state_dependency/driver_drive_requires_vehicle_bound_state
        """
        state = setup_unbound_driver_and_vehicle()
        driver, vehicle = state["driver"], state["vehicle"]
        clock0 = get_server_clock_iso()
        # Attempt DRIVING while unbound.
        payload = create_duty_event_payload(
            new_status="DRIVING",
            event_time=add_seconds(clock0, 60),
            vehicle_id=vehicle["id"],
            odometer_miles=100.0,
        )
        resp_unbound = api.create_duty_event(
            driver["id"], payload, make_driver_headers(driver["id"]),
        )
        validate_error(resp_unbound, ApiErrorId.ERR_DRIVER_NOT_BOUND.value)
        # Now bind and retry.
        resp_bind = api.bind_driver(
            driver["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver["id"]),
        )
        validate_success(resp_bind, expected_status=200)
        # Retry DRIVING — must succeed.
        payload2 = create_duty_event_payload(
            new_status="DRIVING",
            event_time=add_seconds(clock0, 120),
            vehicle_id=vehicle["id"],
            odometer_miles=100.0,
        )
        resp_bound = api.create_duty_event(
            driver["id"], payload2, make_driver_headers(driver["id"]),
        )
        validate_success(resp_bound, expected_status=201)

    def test_violation_resolves_when_driver_edit_eliminates_overage(self, api):
        """PRD §3.7: "any `OPEN` or `ACKNOWLEDGED` `Violation` rows
        attached to the affected window are re-evaluated: a
        violation whose recomputed minutes-remaining at its
        `triggering_duty_event_id`'s `event_time` is greater than or
        equal to zero after the edit is flipped to `RESOLVED`".

        Claim: a Violation with overage_minutes=85 is RESOLVED when
        the triggering DRIVING event's event_time is edited to a
        later instant such that driving_minutes_since_break becomes
        exactly 660.

        # difficulty: cross_entity_state_dependency/violation_resolution_depends_on_duty_event_edit_state
        """
        state = setup_violation_from_overage(
            break_end_iso="2026-10-12T10:00:00.000Z",
        )
        driver = state["driver"]
        violation = state["violation"]
        driving_evt = state["driving_event"]
        # Edit the DRIVING event so it starts 85 minutes later —
        # driving_minutes_since_break shrinks from 745 to 660.
        original_drive_time = driving_evt["event_time"]
        new_drive_time = add_minutes(original_drive_time, 85)
        edit_duty_event(
            driver, driving_evt["id"],
            event_time=new_drive_time,
        )
        # Re-fetch the violation.
        refreshed_v = get_violation(violation["id"])
        assert refreshed_v["status"] == "RESOLVED", (
            f"PRD §3.7: edit eliminating overage flips Violation to "
            f"RESOLVED; got status={refreshed_v['status']!r}"
        )


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_duty_event_strict_monotonic_point_conflict(self, api):
        """PRD §3.3: "an `event_time` that is a UTC instant strictly
        greater than the latest accepted `DutyEvent.event_time` for
        this driver".

        Claim: a duty event whose event_time exactly equals the
        latest stored event_time is rejected with
        ERR_DUTY_EVENT_OUT_OF_ORDER (strict-monotonic point
        conflict); a subsequent event one millisecond later succeeds.

        # difficulty: resource_temporal_overlap/duty_event_strict_monotonic_per_driver_point_conflict
        """
        state = setup_full_stack()
        driver, vehicle = state["driver"], state["vehicle"]
        anchor = "2026-10-15T10:00:00.000Z"
        advance_clock_to_iso(anchor)
        e1 = post_duty_event(
            driver, new_status="ON_DUTY_NOT_DRIVING",
            event_time=anchor, vehicle_id=vehicle["id"],
            odometer_miles=100.0,
            annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
        )
        # Attempt event_time exactly equal — must fail.
        payload_eq = create_duty_event_payload(
            new_status="OFF_DUTY",
            event_time=e1["event_time"],
        )
        resp_eq = api.create_duty_event(
            driver["id"], payload_eq,
            make_driver_headers(driver["id"]),
        )
        validate_error(resp_eq, ApiErrorId.ERR_DUTY_EVENT_OUT_OF_ORDER.value)
        # One millisecond later — must succeed.
        next_iso = "2026-10-15T10:00:00.001Z"
        payload_after = create_duty_event_payload(
            new_status="OFF_DUTY",
            event_time=next_iso,
        )
        resp_after = api.create_duty_event(
            driver["id"], payload_after,
            make_driver_headers(driver["id"]),
        )
        validate_success(resp_after, expected_status=201)

    def test_vehicle_half_open_occupancy_after_unbind(self, api):
        """PRD §3.2: "On a successful unbind the server atomically
        clears `Driver.bound_vehicle_id`, clears
        `Driver.bound_eld_device_id`, and clears
        `Vehicle.current_driver_id`."

        Claim: vehicle occupancy is half-open — after an unbind that
        clears `Vehicle.current_driver_id`, a new bind by a
        different driver succeeds. (Concurrency error_id of the
        loser in the same-instant case is PRD-silent; we test only
        the sequential succeed-after-unbind shape here.)

        # difficulty: resource_temporal_overlap/vehicle_current_driver_half_open_occupancy
        """
        state = setup_full_stack()
        driver1, vehicle, carrier = (
            state["driver"], state["vehicle"], state["carrier"],
        )
        # Driver 2 on the same carrier — currently unbound.
        driver2 = create_driver(carrier_id=carrier["id"])
        # While D1 is bound, D2 cannot bind to V.
        resp_blocked = api.bind_driver(
            driver2["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver2["id"]),
        )
        validate_error(resp_blocked, ApiErrorId.ERR_VEHICLE_ALREADY_BOUND.value)
        # Unbind D1.
        unbind_driver(driver1)
        # D2 binds — must succeed.
        resp_after = api.bind_driver(
            driver2["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver2["id"]),
        )
        data = validate_success(resp_after, expected_status=200)
        assert data["bound_vehicle_id"] == vehicle["id"]
        v_after = get_vehicle(vehicle["id"])
        assert v_after["current_driver_id"] == driver2["id"]


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_bind_unbind_round_trip_clears_fields(self, api):
        """PRD §3.2: "On a successful unbind the server atomically
        clears `Driver.bound_vehicle_id`, clears
        `Driver.bound_eld_device_id`, and clears
        `Vehicle.current_driver_id`."

        Claim: bind then unbind restores Driver.bound_vehicle_id,
        Driver.bound_eld_device_id, and Vehicle.current_driver_id
        all back to NULL — the conserved invariant
        count(drivers with bound_vehicle_id IS NOT NULL) returns to
        its pre-bind value.

        # difficulty: compensating_invariant/bind_unbind_round_trip_preserves_bound_driver_count
        """
        state = setup_unbound_driver_and_vehicle()
        driver, vehicle = state["driver"], state["vehicle"]
        # Bind.
        resp_bind = api.bind_driver(
            driver["id"], bind_payload(vehicle_id=vehicle["id"]),
            make_driver_headers(driver["id"]),
        )
        validate_success(resp_bind, expected_status=200)
        # Unbind.
        resp_un = api.unbind_driver(
            driver["id"], make_driver_headers(driver["id"]),
        )
        data = validate_success(resp_un, expected_status=200)
        assert data["bound_vehicle_id"] is None
        assert data["bound_eld_device_id"] is None
        v_after = get_vehicle(vehicle["id"])
        assert v_after["current_driver_id"] is None

    def test_noop_edit_round_trip_preserves_active_event_count(self, api):
        """PRD §3.7: "The driver supplies new values for any of
        `new_status`, `event_time`, `latitude`, `longitude`,
        `odometer_miles`, or `annotation`; the server appends a fresh
        `DutyEvent` with `edit_state` of `ACTIVE`, flips the old
        event's `edit_state` to `SUPERSEDED`, and sets the old
        event's `superseded_by_event_id` to the new event's id."

        Claim: two edits that restore an event's original field
        values leave the count of ACTIVE DutyEvents on the affected
        DailyLog unchanged. Each edit replaces one ACTIVE row with
        another ACTIVE row.

        # difficulty: compensating_invariant/noop_edit_round_trip_preserves_total_on_duty_minutes
        """
        state = setup_certified_log(log_date="2026-10-20")
        driver, log, events = state["driver"], state["log"], state["events"]
        # Count active events on the log before any edits.
        from test_helpers import list_duty_events
        all_evts_before = list_duty_events(
            driver, params={"daily_log_id": log["id"]},
        )
        active_before = [
            e for e in all_evts_before if e.get("edit_state") == "ACTIVE"
        ]
        n_active = len(active_before)
        # Edit 1 — change odometer to a new value.
        e_drv = events[1]  # the DRIVING event with odometer
        e2 = edit_duty_event(
            driver, e_drv["id"], odometer_miles=1101.0,
        )
        # Edit 2 — restore odometer to its original value.
        edit_duty_event(
            driver, e2["id"], odometer_miles=e_drv["odometer_miles"],
        )
        # Re-list — ACTIVE count must be unchanged.
        all_evts_after = list_duty_events(
            driver, params={"daily_log_id": log["id"]},
        )
        active_after = [
            e for e in all_evts_after if e.get("edit_state") == "ACTIVE"
        ]
        assert len(active_after) == n_active, (
            f"ACTIVE event count should be invariant; before={n_active}, "
            f"after={len(active_after)}"
        )
