"""
Nested and order-sensitive arithmetic in the fare buildup and the oversell nest.

PRD 3.4: "The fare is then built in a strictly pinned sequence of steps.
Reordering the berth-discount step relative to the discount steps, or collapsing
the per-component roundings into a single rounding of the total, produces a
different and wrong answer."
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_CATEGORY_SOLD_OUT,
    RESERVATION_AGENT,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
)

SMALL_OVERSELL_FARE = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 50000,
    "fourth_berth_fare_cents": 40000,
}


def _two_cabin_oversold_world(api):
    """2 physical IA cabins, an appetite of 5, and three solo bookings sold.

    PRD 2.7 caps the appetite at ceil(2 x 0.10) == 1 cabin, so sellable capacity
    is 3 and the three bookings exhaust it exactly.
    """
    world = fx.simple_world(
        api,
        voyage_code="OSL-2701",
        total_lower_berths=20,
        physical_cabins=2,
        oversell_allowance=5,
        fare_overrides=SMALL_OVERSELL_FARE,
    )
    world.sold = [
        fx.guest_with_booking(api, world, occupancy_adults=1) for _ in range(3)
    ]
    return world


def test_oversell_headroom_applies_the_ceiling_cap_before_the_smaller_arm(api):
    """The requested appetite of 5 is clipped to the ceiling-derived cap of 1.

    PRD 2.7: "first take physical_cabins multiplied by the oversell ceiling share
    of one tenth and round that product up to a whole cabin, giving the allowance
    cap; then, if the allotment's cabin category has is_guarantee set to true,
    take the smaller of oversell_allowance and that cap, and floor the outcome at
    zero." And: "Note the order: the ceiling is applied to the cap before the
    smaller of the two is chosen."

    Design: Difficulty/combinatorial_formula/oversell_allowance_min_max_ceil_nest_and_deposit_floor_max
    """
    world = _two_cabin_oversold_world(api)

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["oversell_allowance"] == 5
    assert inventory["effective_oversell_cabins"] == 1
    assert inventory["booked_cabins"] == 3
    assert inventory["available_cabins"] == 0

    # Sellable capacity is exhausted, so the fourth sale has nowhere to go.
    # PRD 3.4: "refused with ERR_CATEGORY_SOLD_OUT if it is false".
    guest = fx.make_guest(api)
    response = api.create_booking(
        f.booking_payload(
            world.sailing["id"],
            world.category["id"],
            guest["id"],
            occupancy_adults=1,
            allow_waitlist=False,
        ),
        RESERVATION_AGENT,
    )
    validate_error(response, ERR_CATEGORY_SOLD_OUT, 422)


def test_deposit_takes_the_per_guest_floor_when_it_beats_the_percentage_arm(api):
    """max(25,000 per guest, one fifth of the net ticket) resolves to the floor.

    PRD 3.4 step 11: "deposit_due_cents is the larger of two figures: 25,000
    cents (250.00 in whole currency units) per guest, multiplied by guest_count;
    and net_ticket_cents multiplied by one fifth, rounded half up." One solo
    guest on a net ticket of 87,500 gives arms of 25,000 and 17,500.

    Design: Difficulty/combinatorial_formula/oversell_allowance_min_max_ceil_nest_and_deposit_floor_max
    """
    world = _two_cabin_oversold_world(api)

    first = fx.read_booking(api, world.sold[0].booking["id"])
    # PRD 3.4 step 3: a solo traveller pays 175 percent of one lower-berth fare.
    assert first["lower_berth_subtotal_cents"] == 87500
    # PRD 3.4 step 4: 87,500 sits below the lowest 250,000-cent floor.
    assert first["berth_discount_pct"] == 0.00
    assert first["net_ticket_cents"] == 87500
    assert first["deposit_due_cents"] == 25000

    last = fx.read_booking(api, world.sold[2].booking["id"])
    assert last["deposit_due_cents"] == 25000


def _gold_guest_with_fifteen_percent_campaign(api):
    """AUR-2701, an ACTIVE 15 percent GENERAL campaign, and a GOLD guest."""
    world = fx.simple_world(api, voyage_code="AUR-2701")
    promo = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="EARLY15",
        audience="GENERAL",
        discount_pct=0.15,
        starts_on="2026-08-01T00:00:00Z",
        ends_on="2026-09-10T00:00:00Z",
        max_redemptions=5,
    )
    fx.activate_promotion(api, promo["id"])
    world.promo = promo
    world.guest = fx.make_guest(api, prior_sailings_count=4)
    return world


def test_promotional_discount_is_rounded_per_component_not_on_the_total(api):
    """56,999 + 8,775 = 65,774, which is not the 65,773 a single rounding gives.

    PRD 3.4 step 7: "promo_discount_cents is the sum of three independently
    rounded amounts: lower_berth_subtotal_cents multiplied by the campaign's
    discount_pct and rounded half up; third_berth_net_cents multiplied by
    discount_pct and rounded half up; and fourth_berth_net_cents multiplied by
    discount_pct and rounded half up." PRD 2.6 adds that "the sum of the rounded
    parts is the stored figure, and it is not equal in general to the rounded sum
    of the raw parts."

    Design: Difficulty/combinatorial_formula/promo_then_loyalty_per_component_rounding_order
    """
    world = _gold_guest_with_fifteen_percent_campaign(api)

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                world.guest["id"],
                third_berth_guests=1,
                promotion_id=world.promo["id"],
            ),
            RESERVATION_AGENT,
        ),
        201,
    )

    assert booking["lower_berth_subtotal_cents"] == 379990
    assert booking["third_berth_net_cents"] == 58497
    assert booking["gross_ticket_cents"] == 438487
    assert booking["promo_discount_cents"] == 65774
    assert booking["promo_discount_cents"] != 65773


def test_loyalty_offer_is_computed_on_the_post_promotion_components(api):
    """The 3 percent GOLD offer bites into 322,991 and 49,722, not the gross.

    PRD 3.4 step 9: "loyalty_discount_cents is the sum of three independently
    rounded amounts: each post-promotion component multiplied by the guest's
    repeat_guest_offer_pct and rounded half up. The loyalty offer therefore
    stacks on top of the campaign discount and is computed on the
    already-discounted components, never on the gross ones."

    Design: Difficulty/combinatorial_formula/promo_then_loyalty_per_component_rounding_order
    """
    world = _gold_guest_with_fifteen_percent_campaign(api)

    guest = fx.read_guest(api, world.guest["id"])
    # PRD 3.4: 3 or more prior sailings gives GOLD and 0.03.
    assert guest["loyalty_tier"] == "GOLD"
    assert guest["repeat_guest_offer_pct"] == 0.03

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                world.guest["id"],
                third_berth_guests=1,
                promotion_id=world.promo["id"],
            ),
            RESERVATION_AGENT,
        ),
        201,
    )

    assert booking["loyalty_discount_cents"] == 11182
    assert booking["net_ticket_cents"] == 361531
    assert booking["deposit_due_cents"] == 75000

    promo = fx.read_promotion(api, world.promo["id"])
    # PRD 3.4: a successful quote raises redemption_count by 1; the cap of 5 is
    # not reached, so the campaign stays ACTIVE.
    assert promo["redemption_count"] == 1
    assert promo["status"] == "ACTIVE"


def test_berth_discount_tier_is_read_from_the_lower_berth_subtotal_alone(api):
    """379,990 selects the 0.10 tier; the 438,487 gross would have selected 0.20.

    PRD 3.4 step 4: "berth_discount_pct is chosen from lower_berth_subtotal_cents
    alone, before any upper-berth money exists, evaluated highest tier first with
    inclusive floors: a subtotal of at least 600,000 cents (6,000.00 in whole
    currency units) gives 0.30; at least 400,000 cents gives 0.20; at least
    250,000 cents gives 0.10; anything below 250,000 cents gives 0.00."

    Design: Difficulty/combinatorial_formula/berth_tier_selected_from_lower_subtotal_before_upper_berths_priced
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                third_berth_guests=1,
            ),
            RESERVATION_AGENT,
        ),
        201,
    )

    assert booking["lower_berth_subtotal_cents"] == 379990
    assert booking["berth_discount_pct"] == 0.10
    assert booking["berth_discount_pct"] != 0.20
    # PRD 3.4 step 5: the discount applies to upper berths only.
    assert booking["third_berth_net_cents"] == 58497
    assert booking["gross_ticket_cents"] == 438487
    assert booking["promo_discount_cents"] == 0
    assert booking["loyalty_discount_cents"] == 0
    assert booking["net_ticket_cents"] == 438487


def test_undiscounted_booking_publishes_its_schedule_and_onboard_projection(api):
    """The same booking's deposit, schedule and onboard projection are pinned.

    PRD 3.4 step 12: "final_payment_due_date is the sailing's embark_date less
    its final_payment_days_before days, and deposit_due_date is the current
    instant plus the sailing's deposit_due_days_after_booking days. payment_terms
    is FULL_AT_BOOKING when booked_days_to_sail is less than or equal to the
    sailing's final_payment_days_before, and STANDARD when booked_days_to_sail is
    strictly greater." PRD 3.4 also fixes projected_onboard_gross_cents as "the
    sailing's nights multiplied by the sum of two products".

    Design: Difficulty/combinatorial_formula/berth_tier_selected_from_lower_subtotal_before_upper_berths_priced
    """
    world = fx.simple_world(api, voyage_code="AUR-2701")
    guest = fx.make_guest(api, prior_sailings_count=0)

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                third_berth_guests=1,
            ),
            RESERVATION_AGENT,
        ),
        201,
    )

    assert booking["guest_count"] == 3
    # 162 days to sail is strictly greater than the 75-day final-payment lead.
    assert booking["payment_terms"] == "STANDARD"
    # max(25,000 x 3, round_half_up(438,487 x 0.20)) == 87,697.
    assert booking["deposit_due_cents"] == 87697
    assert_instant_equals(
        booking["final_payment_due_date"],
        "2026-10-27T17:00:00Z",
        "final_payment_due_date",
    )
    assert_instant_equals(
        booking["deposit_due_date"], "2026-08-08T00:00:00Z", "deposit_due_date"
    )
    # 7 nights x (2 x 9,000 + 1 x 6,000).
    assert booking["projected_onboard_gross_cents"] == 168000
    assert booking["projected_onboard_net_cents"] == 168000
