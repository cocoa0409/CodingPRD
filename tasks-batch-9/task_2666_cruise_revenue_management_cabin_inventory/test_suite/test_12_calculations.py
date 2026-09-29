"""
The derived vectors: fare buildup, aggregate input sets, tier constants, rounding.

Every figure here is re-derived by hand in the docstring or the comment beside it,
because PRD 2.6 fixes the rounding mode and PRD 3.4 fixes the order of the steps.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_UPGRADE_PATH_INVALID,
    GROUP_SALES_AGENT,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_instant_equals,
    assert_two_decimal_pct,
    factories as f,
    fixtures as fx,
    ids_of,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_the_plainest_booking_still_fills_every_declared_output(api):
    """No promotion, no loyalty offer, no upper berths - and nothing is left null.

    PRD 3.4 step 1: "booked_days_to_sail is the sailing's embark_date minus the current
    instant, expressed in seconds, divided by 86,400 and floored." Step 2: "The selected
    rule's identifier is stored in fare_rule_id and its current version is captured in
    pinned_fare_rule_version." Step 4: "berth_discount_pct is chosen from
    lower_berth_subtotal_cents alone, before any upper-berth money exists ... at least
    250,000 cents gives 0.10". Step 11: "deposit_due_cents is the larger of two figures:
    25,000 cents ... per guest, multiplied by guest_count; and net_ticket_cents
    multiplied by one fifth, rounded half up." Step 12: "payment_terms is ...  STANDARD
    when booked_days_to_sail is strictly greater." Step 13: "At creation the last three
    are 0, so the balance equals the net ticket."

    Design: Corner/calculations/booking_fare_buildup_emits_its_whole_output_vector
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
            ),
            RESERVATION_AGENT,
        ),
        201,
    )

    # 2026-08-01T00:00:00Z to 2027-01-10T17:00:00Z is 162 whole days.
    assert booking["booked_days_to_sail"] == 162
    assert booking["fare_rule_id"] == world.fare_rule["id"]
    assert booking["pinned_fare_rule_version"] == world.fare_rule["version"]

    assert booking["guest_count"] == 2
    assert booking["lower_berth_subtotal_cents"] == 379990
    # 379,990 clears the 250,000 floor, so the tier applies even with no upper berths.
    assert float(booking["berth_discount_pct"]) == 0.10
    assert_two_decimal_pct(booking["berth_discount_pct"], "berth_discount_pct")
    assert booking["third_berth_net_cents"] == 0
    assert booking["fourth_berth_net_cents"] == 0

    assert booking["gross_ticket_cents"] == 379990
    assert booking["promo_discount_cents"] == 0
    assert booking["loyalty_discount_cents"] == 0
    assert booking["net_ticket_cents"] == 379990
    # max(25,000 x 2, round(379,990 / 5) == 75,998).
    assert booking["deposit_due_cents"] == 75998

    assert booking["payment_terms"] == "STANDARD"
    assert_instant_equals(
        booking["deposit_due_date"], "2026-08-08T00:00:00Z", "deposit_due_date"
    )
    assert_instant_equals(
        booking["final_payment_due_date"],
        "2026-10-27T17:00:00Z",
        "final_payment_due_date",
    )
    assert booking["amount_paid_cents"] == 0
    assert booking["balance_due_cents"] == 379990

    # 7 nights x (2 adults x 9,000), with no upper-berth headcount.
    assert booking["projected_onboard_gross_cents"] == 126000
    assert booking["projected_onboard_net_cents"] == 126000

    pinned = fx.read_fare_rule(api, world.fare_rule["id"])
    assert pinned["bookings_pinned_count"] == 1


def test_cancelled_and_waitlisted_rows_keep_their_money_but_leave_the_totals(api):
    """A priced waitlist row is the trap: it stores a fare and contributes nothing.

    PRD 3.9: the occupancy sums run "Over every booking of the sailing whose
    booking_status is OPTION, CONFIRMED, or SAILED", and the RALBD numerator "is built
    from the same booking set". PRD 3.4 adds the projection rule: "Whatever their own
    stored projection says, bookings whose booking_status is WAITLISTED or CANCELLED
    contribute 0 to the sailing's projected_onboard_revenue_cents." PRD 1: "a waitlisted
    booking is promoted only when a group review or an operations sweep actually frees a
    cabin, never as a side effect of another guest cancelling."

    Design: Corner/calculations/cancelled_and_waitlisted_bookings_are_excluded_from_sailing_aggregates
    """
    world = fx.simple_world(
        api,
        voyage_code="FLT-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=2,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    keeper = fx.guest_with_booking(api, world, occupancy_adults=2)
    doomed = fx.guest_with_booking(api, world, occupancy_adults=2)
    queued = fx.guest_with_booking(api, world, occupancy_adults=2, allow_waitlist=True)
    assert queued.booking["booking_status"] == "WAITLISTED"

    cancelled = validate_success(
        api.cancel_booking(
            doomed.booking["id"], {"reason": "GUEST_REQUEST"}, RESERVATION_AGENT
        )
    )
    assert cancelled["booking_status"] == "CANCELLED"
    # 162 days to sail is inside the penalty-free band.
    assert cancelled["provisional_penalty_cents"] == 0
    # The row keeps every figure it was sold at.
    assert cancelled["net_ticket_cents"] == 100000
    assert cancelled["projected_onboard_gross_cents"] == 72000

    still_queued = fx.read_booking(api, queued.booking["id"])
    assert still_queued["booking_status"] == "WAITLISTED"
    assert still_queued["net_ticket_cents"] == 100000
    assert still_queued["projected_onboard_gross_cents"] == 72000

    sailing = fx.read_sailing(api, world.sailing["id"])
    # Only the keeper is summed, out of three priced bookings.
    assert sailing["gross_ticket_revenue_cents"] == 100000
    assert sailing["projected_onboard_revenue_cents"] == 72000
    assert sailing["lower_berths_sold"] == 2
    assert float(sailing["occupancy_pct"]) == 5.0
    assert sailing["available_lower_berth_days_gross"] == 160
    assert sailing["available_lower_berth_days_net"] == 160
    # (100,000 + 72,000) over 160 is exactly 1,075.
    assert sailing["ralbd_gross_cents"] == 1075
    assert sailing["ralbd_net_cents"] == 1075
    assert sailing["revenue_alert"] is True
    assert sailing["confirmed_bookings_count"] == 0
    assert sailing["final_payment_risk_flag"] is False

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 1
    assert inventory["waitlisted_bookings_count"] == 1
    # The cabin the cancellation freed is not handed to the queue.
    assert inventory["available_cabins"] == 1
    assert_capacity_identity(inventory)
    assert keeper.booking["booking_status"] == "OPTION"


def test_every_loyalty_floor_is_probed_from_below_at_and_above(api):
    """Tier membership and a non-zero offer are two different facts.

    PRD 3.4: "From that count the loyalty position is derived immediately, evaluated
    highest band first with inclusive floors: 6 or more prior sailings gives a
    loyalty_tier of PLATINUM and a repeat_guest_offer_pct of 0.05; 3 or more gives GOLD
    and 0.03; 1 or more gives MEMBER and 0.00; fewer than 1 gives NONE and 0.00. A
    MEMBER therefore earns recognition but no automatic discount."

    Design: Corner/calculations/loyalty_bands_apply_at_their_exact_inclusive_floors
    """
    fx.set_clock(api)
    expected = {
        0: ("NONE", 0.0),
        1: ("MEMBER", 0.0),
        2: ("MEMBER", 0.0),
        3: ("GOLD", 0.03),
        5: ("GOLD", 0.03),
        6: ("PLATINUM", 0.05),
        7: ("PLATINUM", 0.05),
    }
    for priors, (tier, pct) in expected.items():
        guest = fx.make_guest(api, prior_sailings_count=priors)
        assert guest["prior_sailings_count"] == priors
        assert guest["loyalty_tier"] == tier, f"{priors} priors should be {tier}"
        assert float(guest["repeat_guest_offer_pct"]) == pct, f"{priors} priors"
        assert_two_decimal_pct(guest["repeat_guest_offer_pct"], "repeat_guest_offer_pct")
        assert guest["bookings_count"] == 0

    golds, meta = validate_paginated(
        api.list_guests(REVENUE_MANAGER, params={"loyalty_tier": "GOLD"})
    )
    # Only the 3-prior and 5-prior guests sit in the GOLD band.
    assert meta["total_count"] == 2
    assert sorted(guest["prior_sailings_count"] for guest in golds) == [3, 5]


def test_occupancy_and_ralbd_round_half_up_not_to_even(api):
    """A 32-berth ship puts every ratio on a trailing 5, which banker's rounding fails.

    PRD 2.6: "Wherever a monetary amount is produced by multiplying by a fraction or
    dividing, the result is rounded half up to a whole cent - that is, a residue of
    exactly one half cent rounds away from zero", and "occupancy_pct is a number
    carrying exactly two decimals, rounded half up." PRD 3.9: "occupancy_pct is
    lower_berths_sold divided by total_lower_berths, multiplied by 100 and rounded half
    up to exactly two decimals", and each RALBD variant "is then a single division of
    total revenue by its own denominator, rounded half up exactly once".

    Design: Corner/calculations/occupancy_pct_and_ralbd_round_half_up_at_two_and_zero_decimals
    """
    world = fx.simple_world(
        api,
        voyage_code="PRC-2701",
        nights=4,
        total_lower_berths=32,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )

    solo = fx.guest_with_booking(api, world, occupancy_adults=1)
    first = fx.read_sailing(api, world.sailing["id"])
    # 1 / 32 x 100 is 3.125, which goes up to 3.13 rather than down to 3.12.
    assert first["lower_berths_sold"] == 1
    assert float(first["occupancy_pct"]) == 3.13
    assert_two_decimal_pct(first["occupancy_pct"], "occupancy_pct")

    fx.guest_with_booking(api, world, occupancy_adults=2)
    second = fx.read_sailing(api, world.sailing["id"])
    # 3 / 32 x 100 is 9.375.
    assert float(second["occupancy_pct"]) == 9.38
    assert_two_decimal_pct(second["occupancy_pct"], "occupancy_pct")

    fx.guest_with_booking(api, world, occupancy_adults=2)
    third = fx.read_sailing(api, world.sailing["id"])
    # 5 / 32 x 100 is 15.625, which goes up to 15.63 rather than down to 15.62.
    assert float(third["occupancy_pct"]) == 15.63
    assert_two_decimal_pct(third["occupancy_pct"], "occupancy_pct")
    assert third["inventory_posture"] == "OPEN"

    # 50,000 x 1.75 for the solo party, and max(25,000, round(87,500 / 5)) after it.
    assert solo.booking["net_ticket_cents"] == 87500
    assert solo.booking["deposit_due_cents"] == 25000

    assert third["gross_ticket_revenue_cents"] == 287500
    assert third["projected_onboard_revenue_cents"] == 180000
    assert third["available_lower_berth_days_gross"] == 128
    # (287,500 + 180,000) over 128 is 3,652.34375, so 3,652.
    assert third["ralbd_gross_cents"] == 3652


def test_the_waitlist_promotes_the_oldest_row_not_the_richest(api):
    """First-come beats revenue: the cheapest row wins because it queued first.

    PRD 3.3: "Eligible bookings are ranked by created_at ascending first - the queue is
    first-come, first-served - then, among bookings sharing a creation instant, by
    net_ticket_cents descending ... The server then loops: while available_cabins is at
    least 1 and the eligible pool is non-empty, the head of the ordered pool is promoted
    WAITLISTED to OPTION and available_cabins is recomputed before the next iteration is
    considered." And: "The promoted booking keeps its net_ticket_cents, its
    fare_rule_id, and its pinned_fare_rule_version exactly as they were pinned at
    creation ... What does change is the money clock: deposit_due_date is reset to the
    current instant plus the sailing's deposit_due_days_after_booking days." PRD 3.9
    runs both halves in one sweep: step 3 reviews the block, step 4 promotes "into
    cabins freed by step 3".

    Design: Corner/calculations/waitlist_queue_promotes_the_oldest_row_not_the_richest
    """
    world = fx.simple_world(
        api,
        voyage_code="QUE-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=1,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        cabins_held=1,
        review_date="2026-09-01T00:00:00Z",
        release_policy="FULL_RELEASE",
    )
    fenced = fx.read_inventory(api, world.inventory["id"])
    assert fenced["available_cabins"] == 0

    # The clock is advanced between the three sales so created_at strictly ascends.
    oldest = fx.guest_with_booking(api, world, occupancy_adults=1, allow_waitlist=True)
    fx.set_clock(api, "2026-08-02T00:00:00Z")
    middle = fx.guest_with_booking(api, world, occupancy_adults=2, allow_waitlist=True)
    fx.set_clock(api, "2026-08-03T00:00:00Z")
    richest = fx.guest_with_booking(
        api, world, occupancy_adults=2, third_berth_guests=1, allow_waitlist=True
    )
    # The queue is cheapest-first by creation order: 87,500 then 100,000 then 120,000.
    assert oldest.booking["net_ticket_cents"] == 87500
    assert middle.booking["net_ticket_cents"] == 100000
    assert richest.booking["net_ticket_cents"] == 120000
    for pair in (oldest, middle, richest):
        assert pair.booking["booking_status"] == "WAITLISTED"
    queued = fx.read_inventory(api, world.inventory["id"])
    assert queued["waitlisted_bookings_count"] == 3
    assert queued["available_cabins"] == 0

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.run_ops(api, world.sailing["id"])

    promoted = fx.read_booking(api, oldest.booking["id"])
    assert promoted["booking_status"] == "OPTION"
    # Promotion is not a repricing event.
    assert promoted["net_ticket_cents"] == 87500
    assert promoted["fare_rule_id"] == oldest.booking["fare_rule_id"]
    assert (
        promoted["pinned_fare_rule_version"]
        == oldest.booking["pinned_fare_rule_version"]
    )
    assert_instant_equals(
        promoted["deposit_due_date"], "2026-09-08T00:00:00Z", "deposit_due_date"
    )

    # Only one cabin came back, so the richer rows do not jump the queue.
    assert fx.read_booking(api, middle.booking["id"])["booking_status"] == "WAITLISTED"
    assert fx.read_booking(api, richest.booking["id"])["booking_status"] == "WAITLISTED"

    released = fx.read_block(api, block["id"])
    assert released["status"] == "RELEASED"
    assert released["cabins_held"] == 0

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 1
    assert inventory["waitlisted_bookings_count"] == 2
    assert inventory["group_held_cabins"] == 0
    assert inventory["available_cabins"] == 0
    assert inventory["released_cabins_total"] == 1
    assert_capacity_identity(inventory)

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["lower_berths_sold"] == 1
    assert float(sailing["occupancy_pct"]) == 2.5
    assert sailing["gross_ticket_revenue_cents"] == 87500
    assert sailing["projected_onboard_revenue_cents"] == 36000
    assert sailing["available_lower_berth_days_gross"] == 160
    assert sailing["available_lower_berth_days_net"] == 160
    # (87,500 + 36,000) over 160 is 771.875, so 772.
    assert sailing["ralbd_gross_cents"] == 772


def test_the_upgrade_ladder_stamps_a_depth_and_refuses_a_downward_edge(api):
    """Four rungs give 3, 2, 1, 0 from the bottom, and a stray category sits at 0.

    PRD 3.1: "A category with no upgrade target has an upgrade_chain_length of 0;
    otherwise its upgrade_chain_length is one greater than the upgrade_chain_length of
    the category it points at. An edge is legal only when the target's tier_rank is
    strictly greater than the new category's own tier_rank; otherwise the creation is
    rejected with ERR_UPGRADE_PATH_INVALID."

    Design: Corner/calculations/upgrade_chain_length_walks_the_self_referential_hierarchy
    """
    fx.set_clock(api)
    suite = fx.make_category(
        api,
        f.cabin_category_payload(
            code="SUITE",
            tier_rank=4,
            onboard_spend_lower_per_night_cents=20000,
            onboard_spend_upper_per_night_cents=12000,
        ),
    )
    balcony = fx.make_category(
        api,
        f.cabin_category_payload(
            code="BALCONY",
            tier_rank=3,
            onboard_spend_lower_per_night_cents=14000,
            onboard_spend_upper_per_night_cents=9000,
            upgrade_to_category_id=suite["id"],
        ),
    )
    ocean_view = fx.make_category(
        api,
        f.cabin_category_payload(
            code="OV",
            tier_rank=2,
            onboard_spend_lower_per_night_cents=11000,
            onboard_spend_upper_per_night_cents=7000,
            upgrade_to_category_id=balcony["id"],
        ),
    )
    inside = fx.make_category(
        api,
        f.cabin_category_payload(
            code="IA",
            tier_rank=1,
            is_guarantee=True,
            upgrade_to_category_id=ocean_view["id"],
        ),
    )
    spa = fx.make_category(
        api,
        f.cabin_category_payload(
            code="SPA",
            tier_rank=9,
            max_occupancy=2,
            onboard_spend_lower_per_night_cents=25000,
            onboard_spend_upper_per_night_cents=15000,
        ),
    )

    assert suite["upgrade_to_category_id"] is None
    assert suite["upgrade_chain_length"] == 0
    assert balcony["upgrade_chain_length"] == 1
    assert ocean_view["upgrade_chain_length"] == 2
    # The walk from IA terminates at SUITE, three edges up.
    assert inside["upgrade_chain_length"] == 3
    # A disconnected component is unaffected by the ladder beside it.
    assert spa["upgrade_chain_length"] == 0

    # Tier 9 is not strictly greater than tier 10, so the edge points downhill.
    validate_error(
        api.create_cabin_category(
            f.cabin_category_payload(
                code="DOWN",
                tier_rank=10,
                max_occupancy=2,
                onboard_spend_lower_per_night_cents=8000,
                onboard_spend_upper_per_night_cents=5000,
                upgrade_to_category_id=spa["id"],
            ),
            REVENUE_MANAGER,
        ),
        ERR_UPGRADE_PATH_INVALID,
        422,
    )

    _, meta = validate_paginated(api.list_cabin_categories(REVENUE_MANAGER))
    # The refused row was never stored.
    assert meta["total_count"] == 5

    pointing_at_ov, ov_meta = validate_paginated(
        api.list_cabin_categories(
            REVENUE_MANAGER, params={"upgrade_to_category_id": ocean_view["id"]}
        )
    )
    assert ov_meta["total_count"] == 1
    assert ids_of(pointing_at_ov) == [inside["id"]]
