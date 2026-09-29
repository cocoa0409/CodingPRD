"""Two quantities that must balance after every request.

Grant money splits three ways and a cancellation has to put the split back
exactly as it was. Slot capacity is integer and a reschedule has to move one slot
between two windows without minting or losing it.
"""

import pytest

from test_helpers import (
    OPS_HEADERS,
    Z1_STANDARD_SUBTOTAL_CENTS,
    allocations_for,
    assert_delivery_state,
    assert_grant_conservation,
    assert_grant_ledger,
    assert_window_occupancy,
    build_network,
    build_ready_order,
    build_window,
    factories,
    find_by,
    read_delivery,
    read_grant,
    read_order,
    read_window,
    reserve_delivery,
    utc_ts,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

SINGLE_LINE_ORDER = {
    "rx_line_count": 1,
    "cold_chain_required": False,
    "controlled_schedule": "NONE",
    "total_rx_value_cents": 1000,
}
CANCEL_NOTES = {"notes": "Patient asked for pharmacy pickup instead."}


@pytest.fixture
def pool_funded_to_exactly_one_delivery(api):
    """A 150-cent pool with a 150-cent cap: one standard bag drains it."""
    net = build_network(
        api, grant={"grant_budget_cents": 150, "per_delivery_cap_cents": 150}
    )
    order = build_ready_order(api, net, **SINGLE_LINE_ORDER)
    window = build_window(api, net.zone["id"], capacity_slots=1)
    before = read_grant(api, net.grant["id"], headers=net.plan_admin_headers)
    return net, order, window, before


class TestGrantBudgetConservedAcrossCancel:
    """"A pool's `remaining_cents` is always its `grant_budget_cents` minus its
    `committed_cents` minus its `consumed_cents`."
    """

    def test_reserving_moves_the_whole_budget_from_remaining_to_committed(
        self, api, pool_funded_to_exactly_one_delivery
    ):
        """The split changes shape but the three parts still sum to the budget.

        "Money is *committed* while a provisional bill is in force and *consumed*
        once a final bill is in force: `committed_cents` is the sum of
        `plan_grant_cents` across that pool's allocations whose `status` is
        `ACTIVE` and whose `variant` is `PROVISIONAL`"

        Design: Difficulty/compensating_invariant/plan_grant_budget_conserved_across_reserve_and_cancel
        """
        net, order, window, before = pool_funded_to_exactly_one_delivery
        assert_grant_conservation(before)
        assert_grant_ledger(
            before,
            remaining_cents=150,
            committed_cents=0,
            consumed_cents=0,
            status="ACTIVE",
        )

        reserve_delivery(api, net, order["id"], window["id"])

        after = read_grant(api, net.grant["id"], headers=net.plan_admin_headers)
        assert_grant_conservation(after)
        assert_grant_ledger(
            after,
            remaining_cents=0,
            committed_cents=150,
            consumed_cents=0,
            status="EXHAUSTED",
        )

    def test_cancelling_restores_the_pre_reservation_split_with_no_residue(
        self, api, pool_funded_to_exactly_one_delivery
    ):
        """The compensating operation is exact, and it is recorded not erased.

        "Cancellation advances custody to `CANCELLED`, drives `settlement_status`
        to `VOIDED`, and zeroes `fee_subtotal_cents`; it releases the window slot
        with `FULL → OPEN` where applicable; it voids the `ACTIVE` allocation and
        releases its `plan_grant_cents` from the pool's `committed_cents`,
        returning the pool `EXHAUSTED → ACTIVE` if `remaining_cents` rises above
        0"

        Design: Difficulty/compensating_invariant/plan_grant_budget_conserved_across_reserve_and_cancel
        """
        net, order, window, before = pool_funded_to_exactly_one_delivery
        delivery = reserve_delivery(api, net, order["id"], window["id"])
        validate_success(
            api.cancel_delivery(
                delivery["id"], headers=net.pharmacy_headers, payload=dict(CANCEL_NOTES)
            )
        )

        restored = read_grant(api, net.grant["id"], headers=net.plan_admin_headers)
        assert_grant_conservation(restored)
        assert_grant_ledger(
            restored,
            remaining_cents=before["remaining_cents"],
            committed_cents=before["committed_cents"],
            consumed_cents=before["consumed_cents"],
            status="ACTIVE",
        )

        cancelled = read_delivery(api, delivery["id"])
        assert_delivery_state(cancelled, "CANCELLED", "VOIDED")
        assert cancelled["fee_subtotal_cents"] == 0

        rows = allocations_for(api, delivery["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "VOIDED"

        assert read_order(api, order["id"])["status"] == "READY"
        assert_window_occupancy(
            read_window(api, window["id"]),
            reserved_slots=0,
            available_slots=1,
            status="OPEN",
        )

    def test_a_second_cancellation_cannot_release_the_same_money_twice(
        self, api, pool_funded_to_exactly_one_delivery
    ):
        """The terminal custody value is what forbids a double release.

        "A delivery at `PICKED_UP` or beyond can no longer be cancelled;
        `ERR_INVALID_CUSTODY_STATE` is the answer."

        Design: Difficulty/compensating_invariant/plan_grant_budget_conserved_across_reserve_and_cancel
        """
        net, order, window, _before = pool_funded_to_exactly_one_delivery
        delivery = reserve_delivery(api, net, order["id"], window["id"])
        validate_success(
            api.cancel_delivery(
                delivery["id"], headers=net.pharmacy_headers, payload=dict(CANCEL_NOTES)
            )
        )

        response = api.cancel_delivery(
            delivery["id"], headers=net.pharmacy_headers, payload=dict(CANCEL_NOTES)
        )
        validate_error(response, "ERR_INVALID_CUSTODY_STATE", 409)

        assert read_grant(api, net.grant["id"], headers=net.plan_admin_headers)[
            "remaining_cents"
        ] == 150


@pytest.fixture
def one_bag_on_the_wider_of_two_windows(api):
    """A bag reserved on a capacity-2 window, with a capacity-1 window waiting.

    The clock stays at 09:00Z so both windows are more than two hours out and
    either one is reservable.
    """
    net = build_network(api)
    order = build_ready_order(api, net, **SINGLE_LINE_ORDER)
    wide = build_window(api, net.zone["id"], capacity_slots=2)
    narrow = build_window(
        api,
        net.zone["id"],
        window_start=utc_ts(3, 17),
        window_end=utc_ts(3, 19),
        capacity_slots=1,
    )
    delivery = reserve_delivery(api, net, order["id"], wide["id"])
    return net, order, wide, narrow, delivery


def _reserved_across_the_network(api, zone_id):
    rows, _meta = validate_paginated(
        api.list_delivery_windows(OPS_HEADERS, zone_id=zone_id)
    )
    return sum(row["reserved_slots"] for row in rows)


class TestWindowSlotConservedAcrossReschedule:
    """"`available_slots` is `capacity_slots` minus `reserved_slots`, never
    allowed below zero."
    """

    def test_the_slot_moves_between_the_two_windows_in_opposite_directions(
        self, api, one_bag_on_the_wider_of_two_windows
    ):
        """One release and one reservation, derived from membership on both sides.

        "On success the old window's `reserved_slots` drops by one with `FULL →
        OPEN` where applicable, the new window's rises with `OPEN → FULL` where
        applicable, and both windows bump their `version`."

        Design: Difficulty/compensating_invariant/window_slot_count_conserved_across_reschedule
        """
        net, _order, wide, narrow, delivery = one_bag_on_the_wider_of_two_windows
        assert_window_occupancy(
            read_window(api, wide["id"]),
            reserved_slots=1,
            available_slots=1,
            status="OPEN",
        )
        assert_window_occupancy(
            read_window(api, narrow["id"]),
            reserved_slots=0,
            available_slots=1,
            status="OPEN",
        )

        validate_success(
            api.reschedule_delivery(
                delivery["id"],
                factories.reschedule_payload(narrow["id"]),
                headers=net.pharmacy_headers,
            )
        )

        assert_window_occupancy(
            read_window(api, wide["id"]),
            reserved_slots=0,
            available_slots=2,
            status="OPEN",
        )
        assert_window_occupancy(
            read_window(api, narrow["id"]),
            reserved_slots=1,
            available_slots=0,
            status="FULL",
        )

    def test_the_network_wide_reserved_total_is_unchanged_by_the_move(
        self, api, one_bag_on_the_wider_of_two_windows
    ):
        """The slot was neither duplicated nor dropped, and it still points home.

        "Occupancy of a window is defined by membership, not by a counter.
        `reserved_slots` is the number of deliveries pointing at that window whose
        `custody_status` is `QUEUED`, `ASSIGNED`, `PICKED_UP`, `OUT_FOR_DELIVERY`,
        or `ATTEMPT_FAILED`"

        Design: Difficulty/compensating_invariant/window_slot_count_conserved_across_reschedule
        """
        net, _order, _wide, narrow, delivery = one_bag_on_the_wider_of_two_windows
        assert _reserved_across_the_network(api, net.zone["id"]) == 1

        validate_success(
            api.reschedule_delivery(
                delivery["id"],
                factories.reschedule_payload(narrow["id"]),
                headers=net.pharmacy_headers,
            )
        )
        assert _reserved_across_the_network(api, net.zone["id"]) == 1

        moved = read_delivery(api, delivery["id"])
        assert moved["window_id"] == narrow["id"]
        assert moved["custody_status"] == "QUEUED"

    def test_the_bill_is_re_derived_rather_than_committed_twice(
        self, api, one_bag_on_the_wider_of_two_windows
    ):
        """A paired supersede-and-recompute leaves one live commitment.

        "The `ACTIVE` `PROVISIONAL` allocation is superseded and a replacement
        computed for the new window, which releases the old `plan_grant_cents`
        from the pool's `committed_cents` and commits the new figure."

        Design: Difficulty/compensating_invariant/window_slot_count_conserved_across_reschedule
        """
        net, _order, _wide, narrow, delivery = one_bag_on_the_wider_of_two_windows
        validate_success(
            api.reschedule_delivery(
                delivery["id"],
                factories.reschedule_payload(narrow["id"]),
                headers=net.pharmacy_headers,
            )
        )

        rows = allocations_for(api, delivery["id"])
        assert len(rows) == 2
        assert find_by(rows, status="SUPERSEDED")["fee_subtotal_cents"] == (
            Z1_STANDARD_SUBTOTAL_CENTS
        )
        assert find_by(rows, status="ACTIVE")["variant"] == "PROVISIONAL"

        grant = read_grant(api, net.grant["id"], headers=net.plan_admin_headers)
        assert grant["committed_cents"] == 150
        assert_grant_conservation(grant)

    def test_the_filled_window_then_refuses_a_second_bag(
        self, api, one_bag_on_the_wider_of_two_windows
    ):
        """Zero available slots is enforced on the next arrival, not just reported.

        "The target window's `available_slots` is at least 1 — otherwise
        `ERR_WINDOW_FULL`. Guards reserving a delivery, rescheduling, and
        adjudicating. This is the aggregate check: each individual reservation is
        legal but the collective would exceed `capacity_slots`."

        Design: Difficulty/compensating_invariant/window_slot_count_conserved_across_reschedule
        """
        net, _order, wide, narrow, delivery = one_bag_on_the_wider_of_two_windows
        validate_success(
            api.reschedule_delivery(
                delivery["id"],
                factories.reschedule_payload(narrow["id"]),
                headers=net.pharmacy_headers,
            )
        )

        second_order = build_ready_order(api, net, **SINGLE_LINE_ORDER)
        second_delivery = reserve_delivery(api, net, second_order["id"], wide["id"])
        response = api.reschedule_delivery(
            second_delivery["id"],
            factories.reschedule_payload(narrow["id"]),
            headers=net.pharmacy_headers,
        )
        validate_error_is_one_of(response, ["ERR_WINDOW_FULL", "ERR_WINDOW_CLOSED"])

        assert_window_occupancy(
            read_window(api, narrow["id"]), reserved_slots=1, available_slots=0
        )
