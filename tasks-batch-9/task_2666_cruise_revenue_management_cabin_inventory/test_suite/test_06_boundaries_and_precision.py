"""
Values sitting exactly on a declared threshold, and the instant they tip over it.

PRD 2.6 fixes the rounding discipline these boundaries are measured against:
"Wherever a monetary amount is produced by multiplying by a fraction or dividing,
the result is rounded half up to a whole cent - that is, a residue of exactly one
half cent rounds away from zero."
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ERR_FINAL_PAYMENT_OVERDUE,
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def _ocean_view(api):
    """The 2-lower-berth OV category all three alert-boundary sailings share."""
    return fx.make_category(
        api,
        code="OV",
        tier_rank=2,
        max_occupancy=4,
        lower_berths=2,
        onboard_spend_lower_per_night_cents=11000,
        onboard_spend_upper_per_night_cents=7000,
    )


def _sailing_priced_at(api, category, guest, voyage_code, base_fare_cents):
    """A 4-berth / 5-night voyage with one 2-adult booking at the given base fare.

    Every such sailing has 20 available lower-berth days and 110,000 cents of
    projected onboard revenue, so the base fare alone moves RALBD.
    """
    world = fx.simple_world(
        api,
        voyage_code=voyage_code,
        embark_date="2027-03-01T16:00:00Z",
        nights=5,
        total_lower_berths=4,
        category=category,
        physical_cabins=2,
        oversell_allowance=0,
        fare_overrides={
            "window_open_days_to_sail": 730,
            "window_close_days_to_sail": 0,
            "base_lower_berth_fare_cents": base_fare_cents,
            "third_berth_fare_cents": 50000,
            "fourth_berth_fare_cents": 40000,
        },
    )
    world.booking = fx.make_booking(
        api, world.sailing["id"], category["id"], guest["id"], occupancy_adults=2
    )
    return world


def test_ralbd_net_exactly_on_the_alert_floor_is_not_flagged(api):
    """20,000 exactly stays quiet; 19,900 raises the alert.

    PRD 3.9: "revenue_alert is set when ralbd_net_cents is **strictly** below
    20,000 cents (200.00 in whole currency units) - a sailing sitting exactly on
    the floor is not flagged - and the alert always reads the net variant, never
    the gross one."

    Design: Difficulty/boundary_precision_check/ralbd_net_exactly_at_alert_floor_is_not_flagged
    """
    category = _ocean_view(api)
    guest = fx.make_guest(api, prior_sailings_count=0)

    on_the_floor = _sailing_priced_at(api, category, guest, "RAL-A", 145000)
    below_the_floor = _sailing_priced_at(api, category, guest, "RAL-C", 144000)

    a = validate_success(api.revenue_summary(on_the_floor.sailing["id"], REVENUE_MANAGER))
    assert a["available_lower_berth_days_gross"] == 20
    assert a["available_lower_berth_days_net"] == 20
    assert a["gross_ticket_revenue_cents"] == 290000
    assert a["projected_onboard_revenue_cents"] == 110000
    assert a["ralbd_gross_cents"] == 20000
    assert a["ralbd_net_cents"] == 20000
    assert a["revenue_alert"] is False
    assert on_the_floor.booking["net_ticket_cents"] == 290000

    c = validate_success(
        api.revenue_summary(below_the_floor.sailing["id"], REVENUE_MANAGER)
    )
    assert c["gross_ticket_revenue_cents"] == 288000
    assert c["ralbd_net_cents"] == 19900
    assert c["revenue_alert"] is True
    assert below_the_floor.booking["net_ticket_cents"] == 288000


def test_the_alert_reads_the_rounded_ralbd_not_the_raw_quotient(api):
    """399,990 over 20 days is 19,999.5, which rounds half up onto the floor.

    PRD 3.9: "Each variant is then a single division of total revenue by its own
    denominator, rounded half up exactly once, written to ralbd_gross_cents and
    ralbd_net_cents respectively", and only then is the strict comparison of PRD
    3.9's alert rule applied to the stored figure. PRD 2.5 adds that version
    "increments by exactly 1 on every mutation of that row", so the summary
    reads - which mutate nothing - leave it where it was.

    Design: Difficulty/boundary_precision_check/ralbd_net_exactly_at_alert_floor_is_not_flagged
    """
    category = _ocean_view(api)
    guest = fx.make_guest(api, prior_sailings_count=0)
    world = _sailing_priced_at(api, category, guest, "RAL-B", 144995)

    version_before = fx.read_sailing(api, world.sailing["id"])["version"]

    summary = validate_success(api.revenue_summary(world.sailing["id"], REVENUE_MANAGER))
    assert summary["gross_ticket_revenue_cents"] == 289990
    assert summary["projected_onboard_revenue_cents"] == 110000
    # 289,990 + 110,000 == 399,990; 399,990 / 20 == 19,999.5 -> 20,000.
    assert summary["ralbd_net_cents"] == 20000
    assert summary["revenue_alert"] is False
    assert world.booking["net_ticket_cents"] == 289990

    validate_success(api.revenue_summary(world.sailing["id"], REVENUE_MANAGER))
    assert fx.read_sailing(api, world.sailing["id"])["version"] == version_before


def _two_deposited_siblings(api):
    """Two identical 2-adult IA bookings with their deposits paid.

    Each prices at 379,990 with a deposit of 75,998 and a balance of 303,992, and
    both share the 2026-10-27T17:00:00Z final-payment deadline.
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    siblings = []
    for _ in range(2):
        pair = fx.guest_with_booking(api, world, occupancy_adults=2)
        assert pair.booking["net_ticket_cents"] == 379990
        assert pair.booking["deposit_due_cents"] == 75998
        fx.pay(api, pair.booking["id"], "DEPOSIT", 75998)
        booking = fx.read_booking(api, pair.booking["id"])
        assert booking["payment_status"] == "DEPOSIT_PAID"
        assert booking["balance_due_cents"] == 303992
        siblings.append(booking)
    world.siblings = siblings
    return world


def test_final_payment_posted_at_exactly_the_due_instant_is_on_time(api):
    """The deadline comparison is inclusive to the second.

    PRD 3.5: "It requires booking_status to be OPTION or CONFIRMED, requires the
    current instant to be no later than final_payment_due_date - the comparison is
    inclusive, so a payment posted at exactly the due instant is on time, while a
    later one is refused with ERR_FINAL_PAYMENT_OVERDUE". PRD 3.4 fixes the
    deadline itself as "the sailing's embark_date less its
    final_payment_days_before days".

    Design: Difficulty/boundary_precision_check/final_payment_at_exact_due_instant_is_on_time
    """
    world = _two_deposited_siblings(api)
    on_time = world.siblings[0]
    assert_instant_equals(
        on_time["final_payment_due_date"],
        "2026-10-27T17:00:00Z",
        "final_payment_due_date",
    )

    fx.set_clock(api, "2026-10-27T17:00:00Z")
    validate_success(
        api.post_payment(
            on_time["id"], f.payment_payload("FINAL_PAYMENT", 303992), RESERVATION_AGENT
        ),
        201,
    )

    booking = fx.read_booking(api, on_time["id"])
    assert booking["payment_status"] == "PAID_IN_FULL"
    assert booking["amount_paid_cents"] == 379990
    assert booking["balance_due_cents"] == 0

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["paid_in_full_bookings_count"] == 1


def test_final_payment_one_second_late_is_refused(api):
    """One second past the deadline is late, and the ledger stays at one row.

    PRD 3.5: a final payment "requires the current instant to be no later than
    final_payment_due_date ... while a later one is refused with
    ERR_FINAL_PAYMENT_OVERDUE". PRD 2.4 makes the comparison an instant
    comparison, not a date one.

    Design: Difficulty/boundary_precision_check/final_payment_at_exact_due_instant_is_on_time
    """
    world = _two_deposited_siblings(api)
    late = world.siblings[1]

    fx.set_clock(api, "2026-10-27T17:00:01Z")
    response = api.post_payment(
        late["id"], f.payment_payload("FINAL_PAYMENT", 303992), RESERVATION_AGENT
    )
    validate_error(response, ERR_FINAL_PAYMENT_OVERDUE, 422)

    booking = fx.read_booking(api, late["id"])
    assert booking["payment_status"] == "DEPOSIT_PAID"
    assert booking["amount_paid_cents"] == 75998
    assert booking["balance_due_cents"] == 303992

    _, meta = validate_paginated(api.list_payment_events(late["id"], REVENUE_MANAGER))
    assert meta["total_count"] == 1


def _two_blocks_at_the_same_review_date(api):
    """A fully picked-up block and a wholly unpicked one, both due for review.

    FULL holds 3 cabins and has 3 group-drawn bookings, so its unpicked count is
    0; HALF holds the other 2 with no pick-up at all. The clock is left standing
    on the shared review date.
    """
    world = fx.simple_world(
        api,
        voyage_code="GRP-2701",
        nights=4,
        total_lower_berths=20,
        physical_cabins=5,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    world.full = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        agency_name="Full Pickup Agency",
        cabins_held=3,
        review_date="2026-08-16T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    world.half = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        agency_name="Half Pickup Agency",
        cabins_held=2,
        review_date="2026-08-16T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    guest = fx.make_guest(api, prior_sailings_count=0)
    world.guest = guest
    world.picked_up = [
        fx.make_booking(
            api,
            world.sailing["id"],
            world.category["id"],
            guest["id"],
            occupancy_adults=1,
            group_block_id=world.full["id"],
        )
        for _ in range(3)
    ]
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    return world


def test_review_of_a_fully_picked_up_block_is_a_legal_self_loop(api):
    """floor(0 x 0.5) is 0, and a zero release is a transition, not an error.

    PRD 3.3: "When the released quantity is zero, because the block is fully
    picked up or because an ATTRITION_50 block held a single unpicked cabin that
    floored to nothing, the review is still a legal transition: the block takes
    the TENTATIVE -> TENTATIVE zero-release self-loop, its review_count rises by
    1, its review_date is pushed out by 14 days, cabins_held and the allotment's
    group_held_cabins are left untouched, and no waitlist promotion runs. A zero
    release is never an error."

    Design: Difficulty/boundary_precision_check/zero_unpicked_cabins_at_review_is_self_loop_not_error
    """
    world = _two_blocks_at_the_same_review_date(api)

    reviewed = validate_success(
        api.review_group_block(world.full["id"], GROUP_SALES_AGENT_2)
    )

    assert reviewed["status"] == "TENTATIVE"
    assert reviewed["cabins_held"] == 3
    assert reviewed["picked_up_cabins"] == 3
    assert reviewed["released_cabins_total"] == 0
    assert reviewed["review_count"] == 1
    # The self-loop is not a review extension, so that counter stays put.
    assert reviewed["review_extension_count"] == 0
    assert_instant_equals(
        reviewed["review_date"], "2026-08-30T00:00:00Z", "review_date"
    )

    first = fx.read_booking(api, world.picked_up[0]["id"])
    # A solo guest pays 175 percent of 50,000, and the 25,000 per-guest floor
    # beats a fifth of 87,500.
    assert first["net_ticket_cents"] == 87500
    assert first["deposit_due_cents"] == 25000


def test_the_sibling_block_one_notch_above_the_boundary_releases_a_cabin(api):
    """2 unpicked cabins release 1, proving zero is a boundary not a dead path.

    PRD 3.3: "under FULL_RELEASE the released quantity is that entire remainder,
    and under ATTRITION_50 it is the remainder multiplied by one half and rounded
    down to a whole cabin." PRD 2.7 keeps the allotment reconciled: "available_cabins
    is sellable capacity minus booked_cabins minus group_held_cabins, floored at
    zero."

    Design: Difficulty/boundary_precision_check/zero_unpicked_cabins_at_review_is_self_loop_not_error
    """
    world = _two_blocks_at_the_same_review_date(api)

    validate_success(api.review_group_block(world.full["id"], GROUP_SALES_AGENT_2))
    half = validate_success(
        api.review_group_block(world.half["id"], GROUP_SALES_AGENT_2)
    )

    assert half["status"] == "PARTIALLY_RELEASED"
    assert half["cabins_held"] == 1
    assert half["released_cabins_total"] == 1
    assert half["review_count"] == 1

    inventory = fx.read_inventory(api, world.inventory["id"])
    # Only the HALF block still fences an unpicked cabin.
    assert inventory["group_held_cabins"] == 1
    assert inventory["booked_cabins"] == 3
    assert inventory["released_cabins_total"] == 1
    assert inventory["available_cabins"] == 1
    assert_capacity_identity(inventory)
