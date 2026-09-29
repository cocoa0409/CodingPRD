"""
Quantities that must reconcile after a whole sequence of moves, not just after one.

Cash retained across a cancellation settlement has to equal the final penalty to
the cent, and an allotment's physical plus oversell capacity has to equal its
available plus booked plus group-held cabins after every group and booking move.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_instant_equals,
    assert_settlement_cash_identity,
    fixtures as fx,
)


def _booking_paid_in_full_then_cancelled_at_sixty_days(api):
    """A 2-adult IA booking paid to the cent, then cancelled with 60 days to sail.

    The fare is 379,990, the deposit 75,998 and the balance 303,992; the final
    payment lands exactly on the 2026-10-27T17:00:00Z deadline. The cancellation is
    filed at 2026-11-11T17:00:00Z, which is 60 days before the 2027-01-10T17:00:00Z
    embarkation and therefore in the half-penalty band.
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api, world.sailing["id"], world.category["id"], guest["id"], occupancy_adults=2
    )
    assert booking["net_ticket_cents"] == 379990
    assert booking["deposit_due_cents"] == 75998
    assert_instant_equals(
        booking["final_payment_due_date"],
        "2026-10-27T17:00:00Z",
        "final_payment_due_date",
    )

    fx.pay(api, booking["id"], "DEPOSIT", 75998)
    fx.set_clock(api, "2026-10-27T17:00:00Z")
    fx.pay(api, booking["id"], "FINAL_PAYMENT", 303992)
    paid = fx.read_booking(api, booking["id"])
    assert paid["payment_status"] == "PAID_IN_FULL"
    assert paid["amount_paid_cents"] == 379990

    fx.set_clock(api, "2026-11-11T17:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(booking["id"], {"reason": "GUEST_REQUEST"}, RESERVATION_AGENT)
    )
    world.guest = guest
    world.booking = cancelled
    return world


def test_settled_cash_retained_equals_the_final_penalty(api):
    """The provisional quote is a record; the settlement redates and then reconciles.

    PRD 3.6: "Cancellation is a two-step affair ... The first step records the
    provisional penalty computed at the cancellation instant ... The second step
    recomputes the penalty at the settlement instant, which may differ from the
    provisional figure if the settlement happens on a later day and crosses a band
    edge, writes it to cancellation_penalty_cents, sets refund_cents to
    amount_paid_cents less the final penalty floored at zero ... and sets
    amount_paid_cents to what the cruise line actually retained." The retained cash
    therefore equals the final penalty exactly.

    Design: Difficulty/compensating_invariant/settled_cash_retained_equals_final_penalty
    """
    world = _booking_paid_in_full_then_cancelled_at_sixty_days(api)

    # 60 days to sail is the inclusive lower edge of the [60, 90) half-penalty band.
    assert world.booking["provisional_penalty_cents"] == 189995
    assert world.booking["cancellation_penalty_cents"] is None
    assert world.booking["refund_cents"] is None
    assert world.booking["booking_status"] == "CANCELLED"
    assert world.booking["payment_status"] == "PENALTY_ASSESSED"

    # One day later the booking has crossed into the [30, 60) three-quarter band.
    fx.set_clock(api, "2026-11-12T17:00:00Z")
    settled = validate_success(
        api.settle_cancellation(world.booking["id"], REVENUE_MANAGER)
    )

    assert settled["cancellation_penalty_cents"] == 284993
    # The provisional figure is history and is never overwritten.
    assert settled["provisional_penalty_cents"] == 189995
    assert settled["refund_cents"] == 94997
    assert settled["payment_status"] == "REFUNDED"
    assert settled["booking_status"] == "CANCELLED"
    assert_instant_equals(settled["settled_at"], "2026-11-12T17:00:00Z", "settled_at")

    # 379,990 paid less the 94,997 refunded is exactly the 284,993 penalty.
    assert settled["amount_paid_cents"] == 284993
    assert_settlement_cash_identity(settled)


def test_the_settlement_ledger_carries_the_refund_and_the_rollup_drops_the_booking(api):
    """The retained cash is a ledger residue, never a third row of its own.

    PRD 2.8: "amount_paid_cents on the booking is the sum of amount_cents over its
    DEPOSIT, FINAL_PAYMENT, PARTIAL, and UPGRADE_CHARGE rows, less the sum over its
    REFUND rows; a refund row therefore reduces the paid total by its own positive
    magnitude." PRD 3.6 adds that the refund row carries "note set to
    CANCELLATION_SETTLEMENT and resulting_payment_status REFUNDED". PRD 3.9 then
    drops the booking from the roll-up entirely, because the revenue numerator is
    "built from the same booking set - booking_status in OPTION, CONFIRMED, or
    SAILED."

    Design: Difficulty/compensating_invariant/settled_cash_retained_equals_final_penalty
    """
    world = _booking_paid_in_full_then_cancelled_at_sixty_days(api)
    fx.set_clock(api, "2026-11-12T17:00:00Z")
    validate_success(api.settle_cancellation(world.booking["id"], REVENUE_MANAGER))

    events, meta = validate_paginated(
        api.list_payment_events(world.booking["id"], REVENUE_MANAGER)
    )
    assert meta["total_count"] == 3
    assert [event["kind"] for event in events] == [
        "DEPOSIT",
        "FINAL_PAYMENT",
        "REFUND",
    ]
    assert [event["amount_cents"] for event in events] == [75998, 303992, 94997]
    assert events[2]["note"] == "CANCELLATION_SETTLEMENT"
    assert events[2]["resulting_payment_status"] == "REFUNDED"
    # PRD 2.8: client-posted rows "leave note null".
    assert events[0]["note"] is None
    assert events[1]["note"] is None

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 0
    assert inventory["available_cabins"] == 64
    assert_capacity_identity(inventory)

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["gross_ticket_revenue_cents"] == 0
    # PRD 3.6: leaving PAID_IN_FULL for PENALTY_ASSESSED drops the counter.
    assert sailing["paid_in_full_bookings_count"] == 0


FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def _fenced_allotment_with_two_bookings(api):
    """An allotment of 10 cabins holding a group fence, a pickup, and an open sale.

    The allowance of 3 is capped by the ten-percent rule to 1 effective oversell
    cabin, so sellable capacity is 11 throughout. The block fences 3 cabins, one of
    which is then picked up by a group member, and a second guest buys out of open
    inventory. The clock is left standing on the block's review date.
    """
    world = fx.simple_world(
        api,
        voyage_code="INV-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=3,
        fare_overrides=FLAT_FARE_50K,
    )
    fresh = fx.read_inventory(api, world.inventory["id"])
    # PRD 2.7: the appetite of 3 is trimmed to ceil(10 x 0.10) == 1.
    assert fresh["effective_oversell_cabins"] == 1
    assert fresh["available_cabins"] == 11
    assert_capacity_identity(fresh)

    world.block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        cabins_held=3,
        review_date="2026-08-16T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    fenced = fx.read_inventory(api, world.inventory["id"])
    assert (fenced["booked_cabins"], fenced["group_held_cabins"]) == (0, 3)
    assert fenced["available_cabins"] == 8
    assert_capacity_identity(fenced)

    world.group_guest = fx.make_guest(api, prior_sailings_count=0)
    world.group_booking = fx.make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        world.group_guest["id"],
        occupancy_adults=1,
        group_block_id=world.block["id"],
    )
    picked_up = fx.read_inventory(api, world.inventory["id"])
    # PRD 3.4: the pickup's two movements cancel, so available_cabins is unmoved.
    assert (picked_up["booked_cabins"], picked_up["group_held_cabins"]) == (1, 2)
    assert picked_up["available_cabins"] == 8
    assert_capacity_identity(picked_up)

    world.open_guest = fx.make_guest(api, prior_sailings_count=0)
    world.open_booking = fx.make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        world.open_guest["id"],
        occupancy_adults=1,
    )
    sold = fx.read_inventory(api, world.inventory["id"])
    assert (sold["booked_cabins"], sold["group_held_cabins"]) == (2, 2)
    assert sold["available_cabins"] == 7
    assert_capacity_identity(sold)

    fx.set_clock(api, "2026-08-16T00:00:00Z")
    return world


def test_the_capacity_identity_survives_a_fence_release(api):
    """Attrition bites the unpicked remainder only, and the identity still closes.

    PRD 2.7: "The capacity identity that must hold at all times is this:
    physical_cabins plus effective_oversell_cabins equals available_cabins plus
    booked_cabins plus group_held_cabins." PRD 3.3: under ATTRITION_50 the released
    quantity is the unpicked remainder "multiplied by one half and rounded down to a
    whole cabin", and "Picked-up cabins are protected first".

    Design: Difficulty/compensating_invariant/inventory_capacity_identity_across_group_and_booking_moves
    """
    world = _fenced_allotment_with_two_bookings(api)

    reviewed = validate_success(
        api.review_group_block(world.block["id"], GROUP_SALES_AGENT_2)
    )
    # 3 held less 1 picked up is 2 unpicked; floor(2 x 0.5) releases 1.
    assert reviewed["status"] == "PARTIALLY_RELEASED"
    assert reviewed["cabins_held"] == 2
    assert reviewed["picked_up_cabins"] == 1
    assert reviewed["released_cabins_total"] == 1
    assert reviewed["review_count"] == 1

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert (inventory["booked_cabins"], inventory["group_held_cabins"]) == (2, 1)
    assert inventory["available_cabins"] == 8
    assert inventory["released_cabins_total"] == 1
    assert inventory["waitlisted_bookings_count"] == 0
    assert_capacity_identity(inventory)


def test_the_capacity_identity_survives_both_cancellations(api):
    """An open cancellation frees a cabin outright; a group one hands it back to the fence.

    PRD 3.6: "From OPTION or CONFIRMED, the allotment's booked_cabins falls by 1 and
    available_cabins is recomputed", and "When the booking carried group_block_id,
    that block's picked_up_cabins is recomputed, which returns the cabin to the group
    fence." PRD 3.3 keeps the released cabin out of that fence for good, because the
    fence sums "that block's cabins_held minus its picked_up_cabins" and cabins_held
    was permanently reduced by the release.

    Design: Difficulty/compensating_invariant/inventory_capacity_identity_across_group_and_booking_moves
    """
    world = _fenced_allotment_with_two_bookings(api)
    validate_success(api.review_group_block(world.block["id"], GROUP_SALES_AGENT_2))

    open_cancelled = validate_success(
        api.cancel_booking(
            world.open_booking["id"], {"reason": "GUEST_REQUEST"}, RESERVATION_AGENT
        )
    )
    # 147 days to sail sits in the penalty-free band of PRD 3.6.
    assert open_cancelled["provisional_penalty_cents"] == 0
    after_open = fx.read_inventory(api, world.inventory["id"])
    assert (after_open["booked_cabins"], after_open["group_held_cabins"]) == (1, 1)
    assert after_open["available_cabins"] == 9
    assert_capacity_identity(after_open)

    group_cancelled = validate_success(
        api.cancel_booking(
            world.group_booking["id"], {"reason": "GUEST_REQUEST"}, RESERVATION_AGENT
        )
    )
    assert group_cancelled["provisional_penalty_cents"] == 0

    block = fx.read_block(api, world.block["id"])
    assert block["picked_up_cabins"] == 0
    assert block["cabins_held"] == 2
    assert block["released_cabins_total"] == 1

    final = fx.read_inventory(api, world.inventory["id"])
    assert (final["booked_cabins"], final["group_held_cabins"]) == (0, 2)
    # PRD 3.6: the freed cabin is not offered to the waitlist inside a cancellation.
    assert final["available_cabins"] == 9
    assert final["released_cabins_total"] == 1
    assert final["waitlisted_bookings_count"] == 0
    assert_capacity_identity(final)

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["lower_berths_sold"] == 0
    assert float(sailing["occupancy_pct"]) == 0.0
    assert sailing["inventory_posture"] == "OPEN"
    assert sailing["gross_ticket_revenue_cents"] == 0
