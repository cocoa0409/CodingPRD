"""En-route operations: delay decisions and their cascade, departure gates,
monitoring events and margin boundaries, acknowledgement, diversion, and the
MEL expiry sweep (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_monitoring_event,
    create_delay_payload,
    create_desk_shift_payload,
    create_divert_payload,
    create_leg_payload,
    create_mel_item_payload,
    create_monitoring_event_payload,
    setup_leg_departed,
    setup_manifest_chain,
    setup_reference_data,
    setup_release_pending,
    setup_release_released,
    add_leg,
    add_second_leg,
    set_clock,
    sign_both,
    validate_error,
    validate_paginated,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestDelayCascade:
    def _setup_delayed(self, api):
        """RELEASED chain plus a second SCHEDULED leg; then a +60 minute delay
        on the released leg."""
        ctx = setup_release_released()
        add_second_leg(ctx, flight_no="FD161", distance_nm=300,
                       sched_dep_utc="2026-05-01T16:00:00Z",
                       sched_arr_utc="2026-05-01T17:00:00Z")
        delayed = validate_success(
            api.delay_leg(ctx["leg"]["id"], create_delay_payload(), ctx["d_headers"]),
            200,
        )
        ctx["delayed_leg"] = delayed
        return ctx

    def test_delay_threshold_cascade_leg_and_release(self, api):
        """PRD §3.8: "An accepted delay updates `sched_dep_utc` and
        `sched_arr_utc`, increments `delay_count` by one, increments the leg's
        `version` by one, and writes a `DELAY_DECISION` record carrying the
        reason. Delay also triggers the auto-amendment rule: when the push in
        whole minutes is at least sixty — exactly sixty triggers; fifty-nine
        does not — and the leg's release is currently `RELEASED`, the release
        moves to `UNDER_AMENDMENT` with `cycle_seq` and `amendment_count` each
        incremented by one and a `RELEASE_AUTO_AMENDED` record written."

        Design: Difficulty/transitive_cascade/delay_threshold_cascade_to_signatures
        """
        ctx = self._setup_delayed(api)
        delayed = ctx["delayed_leg"]
        assert_instant_equals(delayed["sched_dep_utc"], "2026-05-01T11:00:00Z")
        assert delayed["delay_count"] == 1

        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert release["status"] == "UNDER_AMENDMENT"
        assert release["cycle_seq"] == 2
        assert release["amendment_count"] == 1

    def test_delay_threshold_cascade_stales_signatures_and_keeps_workload(self, api):
        """PRD §3.8: "The chain is three links long: the delay mutates the leg,
        the release auto-amends, and the cycle increment invalidates the
        release's existing signatures." The delayed leg is still SCHEDULED, so
        per PRD §3.1 ("the flat count of the dispatcher's legs whose
        `ops_status` is `SCHEDULED` or `DEPARTED`") the counter still covers
        both legs.

        Design: Difficulty/transitive_cascade/delay_threshold_cascade_to_signatures
        """
        ctx = self._setup_delayed(api)
        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        sigs, meta = validate_paginated(
            api.list_release_signatures(ctx["release"]["id"], ctx["d_headers"])
        )
        assert meta["total_count"] == 2
        for sig in sigs:
            assert sig["cycle_seq"] == 1
            assert sig["cycle_seq"] != release["cycle_seq"], (
                "cycle bump must stale every collected signature"
            )

        records, _ = validate_paginated(
            api.list_control_records(ctx["leg"]["id"], ctx["d_headers"])
        )
        actions = [r["action"] for r in records]
        assert "DELAY_DECISION" in actions
        assert "RELEASE_AUTO_AMENDED" in actions

        dispatcher = validate_success(
            api.get_dispatcher(ctx["dispatcher"]["id"], SUP), 200
        )
        assert dispatcher["workload_leg_count"] == 2


class TestDelayValidation:
    def test_delay_invalid_time_rejected(self, api):
        """PRD §3.8: "The new departure must be strictly after the current
        `sched_dep_utc`, and the new arrival strictly after the new departure;
        violations are rejected with `ERR_DELAY_INVALID_TIME`."

        Design: Corner/validations/delay_invalid_time_rejected
        """
        ctx = setup_reference_data(with_alternate=False)
        add_leg(ctx, flight_no="FD580", distance_nm=400)
        res = api.delay_leg(
            ctx["leg"]["id"],
            create_delay_payload(new_dep_utc="2026-05-01T09:00:00Z",
                                 new_arr_utc="2026-05-01T10:00:00Z",
                                 reason_code="OPS"),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DELAY_INVALID_TIME.value)


class TestDepartureGates:
    def test_depart_rejected_while_release_pending(self, api):
        """PRD §3.8: "Only the assigned dispatcher may mark it
        (`ERR_NOT_ASSIGNED_DISPATCHER`); a release for the leg must exist in
        `RELEASED` status (`ERR_INVALID_STATE` otherwise); an `ACTIVE` desk
        shift for the leg's dispatcher must cover the current clock on some desk
        (`ERR_NO_ACTIVE_SHIFT`); and no `EXPIRED` deferred defect may exist on
        the aircraft (`ERR_MEL_ITEM_EXPIRED`). Departure stamps `actual_dep_utc`
        with the current clock, moves `monitor_status` from `UNMONITORED` to
        `MONITORING`, and writes a `DEPARTURE` record."

        Design: Difficulty/cross_entity_state_dependency/leg_depart_gated_on_release_and_shift
        """
        from test_helpers import add_desk_and_shift

        ctx = setup_release_pending()
        add_desk_and_shift(ctx)
        res = api.depart_leg(ctx["leg"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

        sign_both(ctx)
        departed = validate_success(
            api.depart_leg(ctx["leg"]["id"], ctx["d_headers"]), 200
        )
        # Fixture clock is still 08:00, inside the 06:00-14:00 shift window.
        assert departed["ops_status"] == "DEPARTED"
        assert departed["monitor_status"] == "MONITORING"

    def test_depart_rejected_without_active_shift(self, api):
        """PRD §3.8: "an `ACTIVE` desk shift for the leg's dispatcher must cover
        the current clock on some desk (`ERR_NO_ACTIVE_SHIFT`)" — with the
        release RELEASED but the clock outside every shift window, departure is
        rejected; a covering shift on a later day restores the gate.

        Design: Difficulty/cross_entity_state_dependency/leg_depart_gated_on_release_and_shift
        """
        ctx = setup_release_released(include_desk_shift=True)
        set_clock(ctx, "2026-05-01T20:00:00Z")
        res = api.depart_leg(ctx["leg"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_SHIFT.value)
        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        assert leg["ops_status"] == "SCHEDULED"

        # A fresh shift the next day (16 h gap satisfies the rest buffer)
        # makes departure possible again without moving the clock backwards.
        validate_success(
            api.create_desk_shift(
                create_desk_shift_payload(
                    ctx["dispatcher"]["id"], desk_id=ctx["desk"]["id"],
                    shift_start_utc="2026-05-02T06:00:00Z",
                    shift_end_utc="2026-05-02T14:00:00Z",
                ),
                SUP,
            ),
            201,
        )
        set_clock(ctx, "2026-05-02T10:30:00Z")
        departed = validate_success(
            api.depart_leg(ctx["leg"]["id"], ctx["d_headers"]), 200
        )
        assert departed["ops_status"] == "DEPARTED"
        assert departed["monitor_status"] == "MONITORING"


class TestFuelMarginBoundaries:
    def test_margin_exactly_500_is_none(self, api):
        """PRD §3.8: "The fuel recommendation follows fixed thresholds: a margin
        of at least 500 kg yields `NONE`; a margin of zero or more but under 500
        yields `CONSIDER_DIVERT`; a negative margin yields `RECOMMEND_DIVERT` —
        a margin of exactly 500 is `NONE`, exactly 0 is `CONSIDER_DIVERT`."
        (Fuel 4595 - 2730 remaining = 1865 projected; 1865 - 1365 reserve =
        500 margin.)

        Design: Difficulty/boundary_precision_check/fuel_margin_exact_threshold_boundaries
        """
        ctx = setup_leg_departed()
        event = validate_success(
            api.create_monitoring_event(
                create_monitoring_event_payload(ctx["leg"]["id"],
                                                fuel_remaining_kg=4595),
                ctx["d_headers"],
            ),
            201,
        )
        assert_monitoring_event(event)
        assert event["fuel_margin_kg"] == 500
        assert event["recommendation"] == "NONE"

    def test_margin_exactly_zero_is_consider_divert(self, api):
        """PRD §3.8: "a margin of zero or more but under 500 yields
        `CONSIDER_DIVERT`" and "A new event starts `OPEN`; a recommendation of
        `CONSIDER_DIVERT` or `RECOMMEND_DIVERT` moves the leg's `monitor_status`
        from `MONITORING` to `ALERTED`"
        (Fuel 4095 - 2730 = 1365 projected; 1365 - 1365 = 0 margin.)

        Design: Difficulty/boundary_precision_check/fuel_margin_exact_threshold_boundaries
        """
        ctx = setup_leg_departed()
        event = validate_success(
            api.create_monitoring_event(
                create_monitoring_event_payload(ctx["leg"]["id"],
                                                fuel_remaining_kg=4095),
                ctx["d_headers"],
            ),
            201,
        )
        assert event["fuel_margin_kg"] == 0
        assert event["recommendation"] == "CONSIDER_DIVERT"
        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        assert leg["monitor_status"] == "ALERTED"

    def test_margin_minus_one_is_recommend_divert(self, api):
        """PRD §3.8: "a negative margin yields `RECOMMEND_DIVERT`" and "a
        `RECOMMEND_DIVERT` additionally writes a `DIVERT_RECOMMENDED` record."
        (Fuel 4094 - 2730 = 1364 projected; 1364 - 1365 = -1 margin.)

        Design: Difficulty/boundary_precision_check/fuel_margin_exact_threshold_boundaries
        """
        ctx = setup_leg_departed()
        event = validate_success(
            api.create_monitoring_event(
                create_monitoring_event_payload(ctx["leg"]["id"],
                                                fuel_remaining_kg=4094),
                ctx["d_headers"],
            ),
            201,
        )
        assert event["fuel_margin_kg"] == -1
        assert event["recommendation"] == "RECOMMEND_DIVERT"
        records, _ = validate_paginated(
            api.list_control_records(ctx["leg"]["id"], ctx["d_headers"])
        )
        divert_records = [r for r in records if r["action"] == "DIVERT_RECOMMENDED"]
        assert len(divert_records) == 1


class TestMonitorDimensions:
    def test_alert_ack_cycle_leaves_ops_departed(self, api):
        """PRD §3.8: "Acknowledgement de-escalates the leg only when it clears
        the board: the leg's `monitor_status` returns from `ALERTED` to
        `MONITORING` only if, after this acknowledgement, no other event for the
        same leg remains `OPEN` with a recommendation other than `NONE`."
        (Fuel 4365 - 2730 = 1635 projected; margin 270 in [0, 500).)

        Design: Difficulty/non_linear_state_machine/leg_parallel_ops_and_monitor_dimensions
        """
        ctx = setup_leg_departed()
        event = validate_success(
            api.create_monitoring_event(
                create_monitoring_event_payload(ctx["leg"]["id"],
                                                fuel_remaining_kg=4365),
                ctx["d_headers"],
            ),
            201,
        )
        assert event["recommendation"] == "CONSIDER_DIVERT"
        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        assert leg["monitor_status"] == "ALERTED"
        assert leg["ops_status"] == "DEPARTED"

        acked = validate_success(
            api.acknowledge_monitoring_event(event["id"], ctx["d_headers"]), 200
        )
        assert acked["status"] == "ACKNOWLEDGED"
        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        assert leg["monitor_status"] == "MONITORING"
        assert leg["ops_status"] == "DEPARTED"

    def test_recommend_divert_then_diversion_closes_both_dimensions(self, api):
        """PRD §3.8: "**Diversion** is the joint prerogative of dispatcher and
        captain: either may initiate it" and "Diversion moves the leg to
        `DIVERTED` and its `monitor_status` to `CLOSED`, cancels any
        non-terminal release on the leg — including one that is `RELEASED` — and
        creates a continuation leg: `ops_status` `SCHEDULED`, `monitor_status`
        `UNMONITORED`, `diverted_from_leg_id` pointing back to the diverted leg"

        Design: Difficulty/non_linear_state_machine/leg_parallel_ops_and_monitor_dimensions
        """
        ctx = setup_leg_departed()
        event = validate_success(
            api.create_monitoring_event(
                create_monitoring_event_payload(ctx["leg"]["id"],
                                                fuel_remaining_kg=4000),
                ctx["d_headers"],
            ),
            201,
        )
        # projected rhu(4000 - 2730) = 1270; margin 1270 - 1365 = -95 < 0
        assert event["recommendation"] == "RECOMMEND_DIVERT"
        assert event["fuel_margin_kg"] == -95
        records, _ = validate_paginated(
            api.list_control_records(ctx["leg"]["id"], ctx["d_headers"])
        )
        assert "DIVERT_RECOMMENDED" in [r["action"] for r in records]

        continuation = validate_success(
            api.divert_leg(
                ctx["leg"]["id"],
                create_divert_payload(ctx["alt_station"]["id"]),
                ctx["c_headers"],
            ),
            201,
        )
        assert continuation["diverted_from_leg_id"] == ctx["leg"]["id"]
        assert continuation["ops_status"] == "SCHEDULED"
        assert continuation["monitor_status"] == "UNMONITORED"

        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        assert leg["ops_status"] == "DIVERTED"
        assert leg["monitor_status"] == "CLOSED"
        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert release["status"] == "CANCELLED"


class TestMonitoringPreconditions:
    def test_monitoring_event_on_ground_leg_rejected(self, api):
        """PRD §3.8: "Filing an event for a leg that is not `DEPARTED` is
        rejected with `ERR_LEG_NOT_IN_FLIGHT`."

        Design: Corner/state_machines/monitoring_event_on_ground_leg_rejected
        """
        ctx = setup_reference_data(with_alternate=False)
        add_leg(ctx, flight_no="FD340", distance_nm=1200)
        res = api.create_monitoring_event(
            create_monitoring_event_payload(ctx["leg"]["id"], fuel_remaining_kg=9000,
                                            eta_destination_utc="2026-05-01T12:30:00Z"),
            ctx["d_headers"],
        )
        validate_error(res, ApiErrorId.ERR_LEG_NOT_IN_FLIGHT.value)

    def test_ack_non_alerting_event_keeps_monitoring(self, api):
        """PRD §3.8: "Acknowledging an event, done by the dispatcher assigned to
        the event's leg (`ERR_NOT_ASSIGNED_DISPATCHER`), moves the event from
        `OPEN` to `ACKNOWLEDGED` — an event not currently `OPEN` is rejected
        with `ERR_INVALID_STATE`." A NONE event never alerted the leg, so the
        monitor stays MONITORING. (Fuel 8000 - 2730 = 5270; margin 3905 >= 500.)

        Design: Corner/state_machines/ack_non_alerting_event_keeps_monitoring
        """
        ctx = setup_leg_departed()
        event = validate_success(
            api.create_monitoring_event(
                create_monitoring_event_payload(ctx["leg"]["id"],
                                                fuel_remaining_kg=8000),
                ctx["d_headers"],
            ),
            201,
        )
        assert event["recommendation"] == "NONE"
        acked = validate_success(
            api.acknowledge_monitoring_event(event["id"], ctx["d_headers"]), 200
        )
        assert acked["status"] == "ACKNOWLEDGED"
        leg = validate_success(api.get_leg(ctx["leg"]["id"], ctx["d_headers"]), 200)
        assert leg["monitor_status"] == "MONITORING"


class TestMelExpirySweep:
    def test_mel_cleared_item_survives_deadline(self, api):
        """PRD §3.6: "Every item still `OPEN` whose `repair_deadline_utc` lies
        before the new clock becomes `EXPIRED`, processed in
        `repair_deadline_utc` ascending order with ties broken by `created_at`
        ascending, never by id; `CLEARED` items are never touched by the sweep."

        Design: Corner/state_machines/mel_cleared_item_survives_deadline
        """
        ctx = setup_reference_data(with_alternate=False)
        set_clock(ctx, "2026-05-01T08:00:00Z")
        mel = validate_success(
            api.create_mel_item(
                create_mel_item_payload(
                    ctx["aircraft"]["id"], item_code="52-1", deferral_category="A",
                    repair_deadline_utc="2026-05-01T09:00:00Z",
                ),
                SUP,
            ),
            201,
        )
        cleared = validate_success(api.clear_mel_item(mel["id"], SUP), 200)
        assert cleared["status"] == "CLEARED"

        set_clock(ctx, "2026-05-01T10:00:00Z")
        after = validate_success(api.get_mel_item(mel["id"], SUP), 200)
        assert after["status"] == "CLEARED"


class TestRepairWindow:
    def test_repair_window_exceeded_rejected(self, api):
        """PRD §3.6: "The deferral class bounds the deadline from the creation
        clock: class `A` allows at most one day, `B` at most three days, `C` at
        most ten days, and `D` at most thirty days; a deadline beyond its class
        interval is rejected with `ERR_REPAIR_WINDOW_EXCEEDED`."
        (Class B at the 2026-05-01T00:00:00Z startup clock allows at most
        2026-05-04T00:00:00Z; 2026-05-06 is five days out.)

        Design: Corner/validations/repair_window_exceeded_rejected
        """
        ctx = setup_reference_data(with_alternate=False)
        res = api.create_mel_item(
            create_mel_item_payload(
                ctx["aircraft"]["id"], item_code="30-4", deferral_category="B",
                repair_deadline_utc="2026-05-06T00:00:00Z",
            ),
            SUP,
        )
        validate_error(res, ApiErrorId.ERR_REPAIR_WINDOW_EXCEEDED.value)
