"""Reachable transitions, guarded transitions and terminal lockdown.

Every machine here is walked one rung at a time: the legal move, the move that
skips a rung, the replay of a move that already landed, and the side effects each
one drags onto neighbouring rows.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    OPS_USER_A,
    Z1_STANDARD_LINES,
    Z1_STANDARD_SUBTOTAL_CENTS,
    active_allocation,
    advance_to_assigned,
    allocations_for,
    assert_courier_counters,
    assert_delivery_state,
    assert_fee_lines,
    assert_grant_ledger,
    assert_instant,
    assert_payer_mix,
    assert_reliability_scores,
    assert_window_occupancy,
    attempts_for,
    build_courier,
    build_network,
    build_out_for_delivery,
    build_queued_delivery,
    build_ready_order,
    build_window,
    exhaust_attempt_ladder,
    factories,
    find_by,
    latest_case,
    make_courier_headers,
    read_assignment,
    read_courier,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    record_attempt,
    reserve_delivery,
    set_clock,
    utc_ts,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
LONG_WINDOW = {"window_end": utc_ts(3, 22), "capacity_slots": 1}


@pytest.fixture
def accepted_leg_on_a_long_window(api):
    """A standard bag accepted by Ray Ortiz on a 14:00Z to 22:00Z window."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW)
    activated = build_courier(api)
    advance_to_assigned(api, scn, courier=activated)
    return scn, activated


class TestCourierCannotGoDarkWhileHoldingWork:
    """"submitting `OFFLINE` while `AVAILABLE` takes them off, but only when
    `active_delivery_count` is 0 — trying to go dark while holding accepted work
    is `ERR_INVALID_COURIER_STATE`."
    """

    def test_going_offline_is_refused_while_an_accepted_leg_is_held(
        self, api, accepted_leg_on_a_long_window
    ):
        """The forward transition already worked; the reverse one is gated.

        "Acceptance sets the assignment to `ACCEPTED` with `responded_at` from the
        clock, advances the delivery `QUEUED → ASSIGNED` and writes its
        `courier_id`, raises the courier's `active_delivery_count` by one, and
        moves the courier `AVAILABLE → ON_ROUTE`."

        Design: Corner/state_machines/courier_cannot_go_offline_while_holding_an_active_delivery
        """
        scn, activated = accepted_leg_on_a_long_window
        assert activated["status"] == "AVAILABLE"
        assert activated["version"] == 2

        on_route = read_courier(api, scn.courier["id"])
        assert on_route["status"] == "ON_ROUTE"
        assert on_route["active_delivery_count"] == 1

        response = api.set_courier_status(
            scn.courier["id"],
            factories.courier_status_payload("OFFLINE"),
            headers=scn.courier_headers,
        )
        validate_error(response, "ERR_INVALID_COURIER_STATE", 409)
        assert read_courier(api, scn.courier["id"])["status"] == "ON_ROUTE"

    def test_releasing_the_leg_lets_the_courier_clock_off(
        self, api, accepted_leg_on_a_long_window
    ):
        """A cancel hands the courier back, and the same request then succeeds.

        "it revokes any assignment that is `OFFERED` or `ACCEPTED` with a null
        `revoked_by_ops_user_id`, decrementing `active_delivery_count` for an
        accepted one and returning the courier to `AVAILABLE` at 0"

        Design: Corner/state_machines/courier_cannot_go_offline_while_holding_an_active_delivery
        """
        scn, _activated = accepted_leg_on_a_long_window
        validate_success(
            api.cancel_delivery(scn.delivery["id"], headers=scn.pharmacy_headers)
        )

        released = read_courier(api, scn.courier["id"])
        assert released["active_delivery_count"] == 0
        assert released["status"] == "AVAILABLE"

        offline = validate_success(
            api.set_courier_status(
                scn.courier["id"],
                factories.courier_status_payload("OFFLINE"),
                headers=scn.courier_headers,
            )
        )
        assert offline["status"] == "OFFLINE"

        assignment = read_assignment(api, scn.assignment["id"])
        assert assignment["status"] == "REVOKED"
        assert assignment["revoked_by_ops_user_id"] is None


@pytest.fixture
def a_freshly_reserved_bag(api):
    """One standard bag reserved on an empty capacity-1 window."""
    net = build_network(api)
    order = build_ready_order(api, net, **STANDARD_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=1)
    delivery = reserve_delivery(api, net, order["id"], window["id"])
    return net, order, window, delivery


class TestDeliveryStartsQueuedAndPriced:
    """"On success a `Delivery` row appears with `custody_status` `QUEUED` and
    `settlement_status` `PROVISIONAL`"
    """

    def test_both_dimensions_start_together_with_the_snapshotted_proof_fields(
        self, api, a_freshly_reserved_bag
    ):
        """Custody and settlement each open at their own initial value.

        "Three values are snapshotted off the order at this instant and never
        re-derived afterwards: `handling_class`, `signature_required`, and
        `required_id_verification`."

        Design: Corner/state_machines/delivery_starts_in_queued_and_provisional_with_a_priced_allocation
        """
        _net, _order, _window, delivery = a_freshly_reserved_bag
        assert_delivery_state(delivery, "QUEUED", "PROVISIONAL")
        assert delivery["courier_id"] is None
        assert delivery["attempt_count"] == 0
        assert delivery["handling_class"] == "STANDARD"
        assert delivery["signature_required"] is False
        assert delivery["required_id_verification"] == "DOB_MATCH"
        assert delivery["version"] == 1

    def test_the_reservation_is_what_prices_the_bag(self, api, a_freshly_reserved_bag):
        """A provisional bill, a committed pool and a full window, all at once.

        "The window's `reserved_slots` rises by one and it flips to `FULL` if that
        reaches `capacity_slots`; the order moves to `DISPATCHED`; and the bill is
        built."

        Design: Corner/state_machines/delivery_starts_in_queued_and_provisional_with_a_priced_allocation
        """
        net, order, window, delivery = a_freshly_reserved_bag
        allocation = active_allocation(api, delivery["id"])
        assert allocation["variant"] == "PROVISIONAL"
        assert_fee_lines(allocation, Z1_STANDARD_LINES)
        assert_payer_mix(
            allocation,
            patient_gross_share_cents=157,
            plan_grant_cents=150,
            patient_payable_cents=0,
            pharmacy_payable_cents=1416,
        )

        assert_grant_ledger(
            read_grant(api, net.grant["id"]),
            remaining_cents=99_850,
            committed_cents=150,
            consumed_cents=0,
            status="ACTIVE",
        )
        assert_window_occupancy(
            read_window(api, window["id"]),
            reserved_slots=1,
            available_slots=0,
            status="FULL",
        )
        assert read_order(api, order["id"])["status"] == "DISPATCHED"


@pytest.fixture
def an_offer_left_to_go_stale(api):
    """An offer made at 13:45Z and never answered, with the clock now at 13:56Z."""
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER)
    courier = build_courier(api)
    set_clock(api, utc_ts(3, 13, 45))
    assignment = validate_success(
        api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        ),
        201,
    )
    set_clock(api, utc_ts(3, 13, 56))
    scn.courier = courier
    scn.assignment = assignment
    return scn


class TestSweepExpiresAStaleOffer:
    """"First, every assignment still `OFFERED` whose `offer_expires_at` the clock
    has reached or passed moves `OFFERED → EXPIRED`, appending its courier to that
    delivery's `excluded_courier_ids`."
    """

    def test_the_sweep_expires_the_offer_and_excludes_its_courier(
        self, api, an_offer_left_to_go_stale
    ):
        """No courier action can reach EXPIRED; only the sweep can.

        "The response reports `expired_offer_count`, `closed_window_count`,
        `offers_created_count`, and `offered_delivery_ids`."

        Design: Corner/state_machines/routing_run_expires_a_stale_offer_and_excludes_that_courier
        """
        scn = an_offer_left_to_go_stale
        assert_instant(scn.assignment["offer_expires_at"], utc_ts(3, 13, 55))

        sweep = validate_success(api.run_routing_sweep(OPS_HEADERS))
        assert sweep["expired_offer_count"] == 1
        assert sweep["closed_window_count"] == 0
        assert sweep["offers_created_count"] == 0
        assert sweep["offered_delivery_ids"] == []

        assert read_assignment(api, scn.assignment["id"])["status"] == "EXPIRED"
        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["courier_id"] is None
        assert delivery["excluded_courier_ids"] == [scn.courier["id"]]

    def test_a_second_sweep_finds_nothing_left_to_do(self, api, an_offer_left_to_go_stale):
        """The pass is idempotent once the only candidate is excluded.

        "deliveries whose pool is empty are skipped silently rather than erroring"

        Design: Corner/state_machines/routing_run_expires_a_stale_offer_and_excludes_that_courier
        """
        scn = an_offer_left_to_go_stale
        validate_success(api.run_routing_sweep(OPS_HEADERS))

        again = validate_success(api.run_routing_sweep(OPS_HEADERS))
        assert again["expired_offer_count"] == 0
        assert again["offers_created_count"] == 0

        assert read_window(api, scn.window["id"])["reserved_slots"] == 1


class TestCustodyRungsCannotBeSkipped:
    """"`Delivery.custody_status` is in the operation's allowed from-set —
    otherwise `ERR_INVALID_CUSTODY_STATE`."
    """

    def test_departing_or_attempting_before_pickup_is_refused(
        self, api, accepted_leg_on_a_long_window
    ):
        """The actor and the payload are impeccable; only the rung is missing.

        "Pickup requires the delivery to be `ASSIGNED`, the acting courier to be
        its `courier_id`, and the order behind it to be `DISPATCHED` — an order in
        any other state is `ERR_INVALID_ORDER_STATE`."

        Design: Corner/state_machines/custody_transitions_out_of_order_return_invalid_custody_state
        """
        scn, _activated = accepted_leg_on_a_long_window
        validate_error(
            api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        assert read_delivery(api, scn.delivery["id"])["custody_status"] == "ASSIGNED"
        validate_error(
            api.record_attempt(
                scn.delivery["id"],
                factories.attempt_payload("NO_ANSWER"),
                headers=scn.courier_headers,
            ),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )

        picked_up = validate_success(
            api.pickup_delivery(scn.delivery["id"], headers=scn.courier_headers)
        )
        assert picked_up["custody_status"] == "PICKED_UP"
        assert_instant(picked_up["picked_up_at"], utc_ts(3, 13, 45))

        validate_error(
            api.record_attempt(
                scn.delivery["id"],
                factories.attempt_payload("NO_ANSWER"),
                headers=scn.courier_headers,
            ),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )

        set_clock(api, utc_ts(3, 14))
        departed = validate_success(
            api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers)
        )
        assert departed["custody_status"] == "OUT_FOR_DELIVERY"

    def test_the_refused_calls_left_no_row_and_no_version_bump(
        self, api, accepted_leg_on_a_long_window
    ):
        """Only the three accepted transitions moved the counter.

        "`version` (integer) — a counter that increments by one on every mutation
        of the row, including mutations the server performs on its own initiative
        as a cascade from a request addressed at some other resource."

        Design: Corner/state_machines/custody_transitions_out_of_order_return_invalid_custody_state
        """
        scn, _activated = accepted_leg_on_a_long_window
        validate_error(
            api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        validate_error(
            api.record_attempt(
                scn.delivery["id"],
                factories.attempt_payload("NO_ANSWER"),
                headers=scn.courier_headers,
            ),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        validate_success(api.pickup_delivery(scn.delivery["id"], headers=scn.courier_headers))
        validate_error(
            api.record_attempt(
                scn.delivery["id"],
                factories.attempt_payload("NO_ANSWER"),
                headers=scn.courier_headers,
            ),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        set_clock(api, utc_ts(3, 14))
        validate_success(api.depart_delivery(scn.delivery["id"], headers=scn.courier_headers))

        assert attempts_for(api, scn.delivery["id"]) == []
        assert read_delivery(api, scn.delivery["id"])["version"] == 4


@pytest.fixture
def bag_awaiting_its_physical_return(api):
    """A ladder exhausted by three no-answers at 14:00Z, 15:00Z and 18:00Z."""
    scn = build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW
    )
    exhaust_attempt_ladder(api, scn)
    return scn


class TestConfirmReturnIsNotIdempotent:
    """"It advances the delivery `RETURN_PENDING → RETURNED` and the order
    `DISPATCHED → RETURNED_TO_STOCK`, bumping both versions."
    """

    def test_the_exhausted_ladder_leaves_a_bag_owed_back_and_a_case_open(
        self, api, bag_awaiting_its_physical_return
    ):
        """Three failures pin the count and start the return clock.

        "The third failure moves the delivery `OUT_FOR_DELIVERY → RETURN_PENDING`,
        pins `attempt_count` at 3, and sets `return_due_at` to the clock plus the
        dispensing site's `return_window_minutes`."

        Design: Corner/state_machines/second_confirm_return_is_rejected_after_the_first_one_lands
        """
        scn = bag_awaiting_its_physical_return
        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "RETURN_PENDING"
        assert delivery["attempt_count"] == 3
        assert_instant(delivery["return_due_at"], utc_ts(3, 22))

        case = latest_case(api, scn.delivery["id"])
        assert case["exception_type"] == "ATTEMPTS_EXHAUSTED"
        assert case["status"] == "OPEN"
        assert case["opened_by_ops_user_id"] is None

    def test_the_replayed_confirmation_is_rejected_rather_than_repeated(
        self, api, bag_awaiting_its_physical_return
    ):
        """The order-side cascade fires exactly once.

        "an exhausted ladder is still billable work, and the money question is
        left for adjudication or settlement to answer"

        Design: Corner/state_machines/second_confirm_return_is_rejected_after_the_first_one_lands
        """
        scn = bag_awaiting_its_physical_return
        returned = validate_success(
            api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
        )
        assert returned["custody_status"] == "RETURNED"
        after_first = read_order(api, scn.order["id"])
        assert after_first["status"] == "RETURNED_TO_STOCK"

        replay = api.confirm_return(scn.delivery["id"], headers=scn.pharmacy_headers)
        validate_error(replay, "ERR_INVALID_CUSTODY_STATE", 409)

        after_replay = read_order(api, scn.order["id"])
        assert after_replay["status"] == "RETURNED_TO_STOCK"
        assert after_replay["version"] == after_first["version"]
        assert read_delivery(api, scn.delivery["id"])["settlement_status"] == "PROVISIONAL"


@pytest.fixture
def a_cancelled_bag_and_a_spare_window(api):
    """A cancelled delivery, plus an untouched 16:00Z to 18:00Z window."""
    net = build_network(api)
    order = build_ready_order(api, net, **STANDARD_ORDER)
    first = build_window(api, net.zone["id"], capacity_slots=1)
    spare = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(3, 16),
        window_end=utc_ts(3, 18),
        capacity_slots=1,
    )
    delivery = reserve_delivery(api, net, order["id"], first["id"])
    cancelled = validate_success(
        api.cancel_delivery(
            delivery["id"],
            headers=net.pharmacy_headers,
            payload={"notes": "patient will collect in store"},
        )
    )
    return net, order, first, spare, cancelled


class TestCancelledDeliveryIsTerminal:
    """"A delivery at `PICKED_UP` or beyond can no longer be cancelled;
    `ERR_INVALID_CUSTODY_STATE` is the answer."
    """

    def test_every_further_transition_is_locked_out(
        self, api, a_cancelled_bag_and_a_spare_window
    ):
        """Cancel, reschedule and dispatch all meet the same terminal value.

        "Cancellation advances custody to `CANCELLED`, drives `settlement_status`
        to `VOIDED`, and zeroes `fee_subtotal_cents`"

        Design: Corner/state_machines/terminal_cancelled_delivery_locks_every_further_transition
        """
        net, _order, _first, spare, cancelled = a_cancelled_bag_and_a_spare_window
        assert_delivery_state(cancelled, "CANCELLED", "VOIDED")
        assert cancelled["fee_subtotal_cents"] == 0

        validate_error(
            api.cancel_delivery(cancelled["id"], headers=net.pharmacy_headers),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        validate_error(
            api.reschedule_delivery(
                cancelled["id"],
                factories.reschedule_payload(spare["id"]),
                headers=net.pharmacy_headers,
            ),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        assert read_window(api, spare["id"])["reserved_slots"] == 0

        validate_error(
            api.dispatch_delivery(
                cancelled["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            "ERR_INVALID_CUSTODY_STATE",
            409,
        )
        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=cancelled["id"])
        )
        assert meta["total_count"] == 0

    def test_the_compensations_stay_applied_behind_the_locked_row(
        self, api, a_cancelled_bag_and_a_spare_window
    ):
        """The slot, the bill and the money stay released; the order is reusable.

        "and it drives the order `DISPATCHED → READY` so the bag can be scheduled
        again — but only when the cancelled delivery is the order's sole delivery
        whose custody is not `CANCELLED`"

        Design: Corner/state_machines/terminal_cancelled_delivery_locks_every_further_transition
        """
        net, order, first, _spare, cancelled = a_cancelled_bag_and_a_spare_window
        assert_window_occupancy(
            read_window(api, first["id"]),
            reserved_slots=0,
            available_slots=1,
            status="OPEN",
        )

        rows = allocations_for(api, cancelled["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "VOIDED"

        assert_grant_ledger(
            read_grant(api, net.grant["id"]),
            remaining_cents=100_000,
            committed_cents=0,
            consumed_cents=0,
            status="ACTIVE",
        )
        assert read_order(api, order["id"])["status"] == "READY"


@pytest.fixture
def two_couriers_and_one_offer(api):
    """Ray Ortiz onboarded at 09:00Z, Ida Nunez at 09:30Z, and one offer on the table.

    The two couriers are otherwise identical, so the selector's third key — the
    earlier `created_at` — is what has to decide between them, and the two
    onboarding instants are kept apart so that key is not itself a tie.
    """
    scn = build_queued_delivery(api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW)
    first = build_courier(api)
    set_clock(api, utc_ts(3, 9, 30))
    second = build_courier(api, display_name="Ida Nunez")
    set_clock(api, utc_ts(3, 13, 45))
    offer = validate_success(
        api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        ),
        201,
    )
    return scn, first, second, offer


class TestDeclinedOfferKeepsCustodyStill:
    """"It sets the assignment to `DECLINED` with `responded_at` from the clock,
    may carry an optional `notes`, appends the courier to the delivery's
    `excluded_courier_ids` so the selector will never route this delivery to them
    again, and leaves custody at `QUEUED`"
    """

    def test_declining_excludes_the_courier_without_touching_custody(
        self, api, two_couriers_and_one_offer
    ):
        """A dead end for the offer, a no-op for the bag and for the courier.

        "Declining requires the same ownership and the same `OFFERED` status."

        Design: Corner/state_machines/declining_an_offer_keeps_the_delivery_queued_and_excludes_the_courier
        """
        scn, first, _second, offer = two_couriers_and_one_offer
        assert offer["courier_id"] == first["id"]

        declined = validate_success(
            api.decline_assignment(
                offer["id"],
                headers=make_courier_headers(first["id"]),
                payload={"notes": "bag will not fit the remaining route"},
            )
        )
        assert declined["status"] == "DECLINED"
        assert_instant(declined["responded_at"], utc_ts(3, 13, 45))

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["courier_id"] is None
        assert delivery["excluded_courier_ids"] == [first["id"]]

        courier = read_courier(api, first["id"])
        assert_courier_counters(
            courier, attempt_total_count=0, active_delivery_count=0, status="AVAILABLE"
        )

    def test_the_next_dispatch_goes_to_the_second_ranked_courier(
        self, api, two_couriers_and_one_offer
    ):
        """Exclusion is what makes the re-offer land somewhere new.

        "Candidates are then ordered by `rolling_reliability_score` descending,
        ties broken by `active_delivery_count` ascending, and any remaining ties
        broken by `created_at` ascending — never by identifier."

        Design: Corner/state_machines/declining_an_offer_keeps_the_delivery_queued_and_excludes_the_courier
        """
        scn, first, second, offer = two_couriers_and_one_offer
        validate_success(
            api.decline_assignment(offer["id"], headers=make_courier_headers(first["id"]))
        )

        reoffer = validate_success(
            api.dispatch_delivery(
                scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
            ),
            201,
        )
        assert reoffer["courier_id"] == second["id"]
        assert reoffer["status"] == "OFFERED"
        assert reoffer["rank_score"] == pytest.approx(100.00, abs=0.01)
        assert_instant(reoffer["offer_expires_at"], utc_ts(3, 13, 55))

        _rows, meta = validate_paginated(
            api.list_courier_assignments(OPS_HEADERS, delivery_id=scn.delivery["id"])
        )
        assert meta["total_count"] == 2


class TestOrderHoldLoopIsBounded:
    """"Pulling a `READY` order back to `INTAKE` for re-verification requires the
    order to be `READY` — otherwise `ERR_ORDER_NOT_READY` — and requires
    `hold_count` to be below 2; the third attempt is rejected with
    `ERR_MAX_HOLDS_EXCEEDED`."
    """

    def test_two_revisions_are_allowed_and_the_third_is_refused(self, api):
        """The cyclic machine terminates on hold_count, not on time.

        "The `INTAKE` to `READY` to `INTAKE` revision loop is thus bounded at two
        round trips."

        Design: Corner/state_machines/third_hold_on_an_order_returns_max_holds_exceeded
        """
        net = build_network(api)
        order = build_ready_order(api, net, **STANDARD_ORDER)

        first = validate_success(
            api.hold_order(
                order["id"],
                headers=net.pharmacy_headers,
                payload={"notes": "prescriber callback"},
            )
        )
        assert first["status"] == "INTAKE"
        assert first["hold_count"] == 1
        validate_success(api.mark_order_ready(order["id"], headers=net.pharmacy_headers))

        second = validate_success(
            api.hold_order(
                order["id"], headers=net.pharmacy_headers, payload={"notes": "dose changed"}
            )
        )
        assert second["status"] == "INTAKE"
        assert second["hold_count"] == 2
        validate_success(api.mark_order_ready(order["id"], headers=net.pharmacy_headers))

        third = api.hold_order(
            order["id"], headers=net.pharmacy_headers, payload={"notes": "third revision"}
        )
        validate_error(third, "ERR_MAX_HOLDS_EXCEEDED", 409)

        unchanged = read_order(api, order["id"])
        assert unchanged["status"] == "READY"
        assert unchanged["hold_count"] == 2

        window = build_window(api, net.zone["id"], capacity_slots=1)
        delivery = reserve_delivery(api, net, order["id"], window["id"])
        assert delivery["custody_status"] == "QUEUED"


class TestRevokingAnAcceptedLeg:
    """"Revocation requires the assignment to be `OFFERED` or `ACCEPTED`, and for
    an accepted leg requires the delivery's custody to still be `QUEUED` or
    `ASSIGNED`."
    """

    def test_the_revocation_unwinds_three_rows_and_keeps_the_slot(
        self, api, accepted_leg_on_a_long_window
    ):
        """Assignment, delivery and courier all walk backwards together.

        "It sets the assignment to `REVOKED`, stamps `revoked_by_ops_user_id` with
        the acting `X-User-ID`, appends the courier to `excluded_courier_ids`, and
        — when custody was `ASSIGNED` — walks it back `ASSIGNED → QUEUED` and
        nulls the delivery's `courier_id`."

        Design: Corner/state_machines/revoking_an_accepted_assignment_returns_the_delivery_to_queued
        """
        scn, _activated = accepted_leg_on_a_long_window
        revoked = validate_success(
            api.revoke_assignment(
                scn.assignment["id"],
                headers=OPS_HEADERS,
                payload={"notes": "courier vehicle breakdown"},
            )
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_by_ops_user_id"] == OPS_USER_A

        delivery = read_delivery(api, scn.delivery["id"])
        assert delivery["custody_status"] == "QUEUED"
        assert delivery["courier_id"] is None
        assert delivery["excluded_courier_ids"] == [scn.courier["id"]]

        courier = read_courier(api, scn.courier["id"])
        assert courier["active_delivery_count"] == 0
        assert courier["status"] == "AVAILABLE"

        assert_window_occupancy(
            read_window(api, scn.window["id"]),
            reserved_slots=1,
            available_slots=0,
            status="FULL",
        )

    def test_the_bill_and_the_order_are_untouched_but_the_pool_is_now_empty(
        self, api, accepted_leg_on_a_long_window
    ):
        """The bag is still owed, so the money stands and the exclusion bites.

        "The re-entry into `QUEUED` closes the routing-override cycle and seeds
        the exclusion set, and the operator who performed it has just disqualified
        themselves from adjudicating any exception on that delivery (§3.8)."

        Design: Corner/state_machines/revoking_an_accepted_assignment_returns_the_delivery_to_queued
        """
        scn, _activated = accepted_leg_on_a_long_window
        validate_success(
            api.revoke_assignment(
                scn.assignment["id"],
                headers=OPS_HEADERS,
                payload={"notes": "courier vehicle breakdown"},
            )
        )

        assert read_order(api, scn.order["id"])["status"] == "DISPATCHED"
        allocation = active_allocation(api, scn.delivery["id"])
        assert allocation["variant"] == "PROVISIONAL"
        assert allocation["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS

        response = api.dispatch_delivery(
            scn.delivery["id"], headers=OPS_HEADERS, payload=factories.dispatch_payload()
        )
        validate_error(response, "ERR_NO_ELIGIBLE_COURIER", 409)


@pytest.fixture
def a_bag_delivered_on_the_first_run(api):
    """A standard bag handed over at 14:00Z against a DOB_MATCH check."""
    scn = build_out_for_delivery(
        api, order_kwargs=STANDARD_ORDER, window_kwargs=LONG_WINDOW
    )
    record_attempt(
        api,
        scn,
        "DELIVERED",
        id_verification_method="DOB_MATCH",
        recipient_relationship="SELF",
        pod_photo_ref="pod-9931",
    )
    return scn


class TestSettlementJoinsTheTwoDimensions:
    """"The delivery's `settlement_status` moves `PROVISIONAL → FINALIZED`, its
    `fee_subtotal_cents` mirrors the final allocation's, and its `custody_status`
    does not move at all — it stays `DELIVERED` or `RETURNED`."
    """

    def test_the_handover_cascade_leaves_the_money_dimension_alone(
        self, api, a_bag_delivered_on_the_first_run
    ):
        """Custody is finished, the bill is not, and the order still waits.

        "The delivery's `settlement_status` does **not** move — the bill is still
        `PROVISIONAL` and stays that way until settlement."

        Design: Corner/state_machines/settlement_bubbles_the_order_to_closed_and_finalizes_the_fee
        """
        scn = a_bag_delivered_on_the_first_run
        delivery = read_delivery(api, scn.delivery["id"])
        assert_delivery_state(delivery, "DELIVERED", "PROVISIONAL")
        assert_instant(delivery["delivered_at"], utc_ts(3, 14))
        assert read_order(api, scn.order["id"])["status"] == "DISPATCHED"

        assert read_assignment(api, scn.assignment["id"])["status"] == "COMPLETED"
        courier = read_courier(api, scn.courier["id"])
        assert_courier_counters(
            courier,
            attempt_total_count=1,
            delivered_count=1,
            active_delivery_count=0,
            status="AVAILABLE",
        )
        assert_reliability_scores(courier, rolling=100.00, lifetime=100.00)

        assert_window_occupancy(
            read_window(api, scn.window["id"]),
            reserved_slots=0,
            available_slots=1,
            status="OPEN",
        )

    def test_settling_rebuilds_the_bill_and_bubbles_the_order_to_closed(
        self, api, a_bag_delivered_on_the_first_run
    ):
        """One run means the FINAL vector equals the PROVISIONAL one exactly.

        "The `PROVISIONAL` allocation is set to `SUPERSEDED` and its
        `plan_grant_cents` is released from the pool's `committed_cents`. A fresh
        allocation is then computed with `variant` `FINAL` and `status` `ACTIVE`"

        Design: Corner/state_machines/settlement_bubbles_the_order_to_closed_and_finalizes_the_fee
        """
        scn = a_bag_delivered_on_the_first_run
        settled = validate_success(
            api.settle_delivery(scn.delivery["id"], headers=OPS_HEADERS)
        )
        assert settled["settlement_status"] == "FINALIZED"
        assert settled["fee_subtotal_cents"] == Z1_STANDARD_SUBTOTAL_CENTS

        rows = allocations_for(api, scn.delivery["id"])
        assert len(rows) == 2
        final = find_by(rows, variant="FINAL")
        assert final["status"] == "ACTIVE"
        assert_fee_lines(final, Z1_STANDARD_LINES)
        assert_payer_mix(
            final,
            patient_gross_share_cents=157,
            plan_grant_cents=150,
            patient_payable_cents=0,
            pharmacy_payable_cents=1416,
        )
        assert find_by(rows, variant="PROVISIONAL")["status"] == "SUPERSEDED"

        assert_grant_ledger(
            read_grant(api, scn.net.grant["id"]),
            remaining_cents=99_850,
            committed_cents=0,
            consumed_cents=150,
            status="ACTIVE",
        )
        assert read_order(api, scn.order["id"])["status"] == "CLOSED"
