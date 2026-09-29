"""The delivery call's own lifecycle: arrival, lateness, cancellation, misses.

The on-time band is half-open, so an arrival one instant into the window is on
time and an arrival exactly at its end is not; cancellation happens once; and a
call the checkpoint has already missed accepts nothing afterwards.
"""

from test_helpers import (
    PRODUCTION_PLANNER_HEADERS,
    ApiErrorId,
    CancelReason,
    DeliveryCallStatus,
    SupplierStatus,
    approx2,
    make_supplier_portal_headers,
    new_delivery_call,
    new_line,
    new_part,
    new_station,
    new_supplier,
    read_call,
    read_supplier,
    record_arrival_payload,
    run_checkpoint,
    same_instant,
    set_clock,
    validate_error,
    validate_success,
)


def _one_scheduled_call(api, window_start="2026-08-03T09:00:00Z",
                        window_end="2026-08-03T10:00:00Z"):
    """A single dock booking at ST10 with nothing else competing for it."""
    set_clock(api, "2026-08-03T06:00:00Z")
    line = new_line(api, "L1")
    station = new_station(api, line["id"], "ST10", 10)
    supplier = new_supplier(api, "SUP1", "Sync Modules GmbH",
                            sync_window_minutes=45)
    part = new_part(api, supplier["id"], "P-DOOR-A")
    call = new_delivery_call(api, supplier["id"], part["id"], station["id"],
                             window_start, window_end)
    return line, supplier, call


class TestArrivalScoring:
    """Inside the window earns credit; the closing instant costs eight points."""

    def test_an_arrival_inside_the_window_is_on_time_and_cannot_bank_credit(self, api):
        """Half an hour into the window, with the +2 credit already capped.

        "An `arrived_at` strictly before `window_end` takes the call `SCHEDULED →
        ARRIVED_ON_TIME` with `lateness_minutes` of 0 — arriving early counts as on
        time — increments `delivered_on_time_count`, adds 2 points to `on_time_score`
        capped at 100.00, and re-derives the supplier's `status`."

        Design: Corner/state_machines/record_arrival_inside_window_moves_call_to_arrived_on_time
        """
        _line, supplier, call = _one_scheduled_call(api)

        arrived = validate_success(
            api.record_arrival(
                call["id"], record_arrival_payload("2026-08-03T09:30:00Z"),
                make_supplier_portal_headers(supplier["id"]),
            )
        )

        assert arrived["status"] == DeliveryCallStatus.ARRIVED_ON_TIME.value
        assert same_instant(arrived["arrived_at"], "2026-08-03T09:30:00Z")
        assert arrived["lateness_minutes"] == 0
        scored = read_supplier(api, supplier["id"])
        assert scored["delivered_on_time_count"] == 1
        assert scored["delivered_late_count"] == 0
        assert float(scored["on_time_score"]) == approx2(100.00)
        assert scored["status"] == SupplierStatus.APPROVED.value

    def test_an_arrival_exactly_at_the_window_end_is_late_by_zero_minutes(self, api):
        """The closing instant belongs to the late branch.

        "An `arrived_at` at or after `window_end` takes the call `SCHEDULED →
        ARRIVED_LATE`; because the window is half-open, arriving at exactly
        `window_end` is late."

        Design: Corner/state_machines/record_arrival_exactly_at_window_end_is_late
        """
        _line, supplier, call = _one_scheduled_call(api)

        arrived = validate_success(
            api.record_arrival(
                call["id"], record_arrival_payload("2026-08-03T10:00:00Z"),
                make_supplier_portal_headers(supplier["id"]),
            )
        )

        assert arrived["status"] == DeliveryCallStatus.ARRIVED_LATE.value
        assert arrived["lateness_minutes"] == 0
        charged = read_supplier(api, supplier["id"])
        assert charged["delivered_late_count"] == 1
        assert charged["delivered_on_time_count"] == 0
        assert float(charged["on_time_score"]) == approx2(92.00)
        assert charged["status"] == SupplierStatus.APPROVED.value


class TestCancellationAndMissedCalls:
    """A dead call is dead: neither cancellation nor arrival applies twice."""

    def test_cancelling_a_second_time_is_refused_and_changes_nothing(self, api):
        """The transition exists only from SCHEDULED.

        "A planner or administrator may cancel a `SCHEDULED` call outright. That takes
        it `SCHEDULED → CANCELLED` with `cancel_reason` `PLANNER`, and every build
        slot whose pinned call it was and which is still `SEQUENCED` is un-sequenced
        to `PLANNED`, replaying the full reversal: presentation slots released, shift
        labour recomputed and line posture re-derived."

        Design: Corner/state_machines/cancel_delivery_call_twice_second_attempt_returns_409
        """
        _line, _supplier, call = _one_scheduled_call(api)

        cancelled = validate_success(
            api.cancel_delivery_call(call["id"], PRODUCTION_PLANNER_HEADERS)
        )
        assert cancelled["status"] == DeliveryCallStatus.CANCELLED.value
        assert cancelled["cancel_reason"] == CancelReason.PLANNER.value

        validate_error(
            api.cancel_delivery_call(call["id"], PRODUCTION_PLANNER_HEADERS),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        after = read_call(api, call["id"])
        assert after["status"] == DeliveryCallStatus.CANCELLED.value
        assert after["cancel_reason"] == CancelReason.PLANNER.value
        assert after["updated_at"] == cancelled["updated_at"]

    def test_a_missed_call_refuses_a_late_arrival_and_is_charged_only_once(self, api):
        """Once swept, the call is closed to its own supplier.

        "The target entity is in a state from which the requested transition exists,
        on every action endpoint, including cross-dimension guards such as shipping
        requiring a certified quality status — otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/record_arrival_on_missed_call_returns_409
        """
        line, supplier, call = _one_scheduled_call(
            api, "2026-08-03T06:10:00Z", "2026-08-03T06:40:00Z"
        )
        set_clock(api, "2026-08-03T06:56:00Z")
        run_checkpoint(api, line["id"])
        assert read_call(api, call["id"])["status"] == DeliveryCallStatus.MISSED.value

        validate_error(
            api.record_arrival(
                call["id"], record_arrival_payload("2026-08-03T06:55:00Z"),
                make_supplier_portal_headers(supplier["id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )

        still_missed = read_call(api, call["id"])
        assert still_missed["status"] == DeliveryCallStatus.MISSED.value
        assert still_missed["arrived_at"] is None
        assert still_missed["lateness_minutes"] is None
        charged_once = read_supplier(api, supplier["id"])
        assert charged_once["missed_count"] == 1
        assert charged_once["delivered_late_count"] == 0
        assert float(charged_once["on_time_score"]) == approx2(80.00)
