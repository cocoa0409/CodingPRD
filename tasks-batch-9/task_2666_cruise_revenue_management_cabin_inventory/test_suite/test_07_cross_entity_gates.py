"""
Operations blocked by the state of an entity that is neither the target nor its parent.

Both scenarios follow the same shape: the target entity is in a perfectly legal
state, a third entity refuses the call, and the identical call succeeds once that
third entity moves - with nothing about the target having changed in between.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ERR_GROUP_BLOCK_NOT_DEFINITE,
    ERR_TARGET_CATEGORY_UNAVAILABLE,
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    fixtures as fx,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def _group_booking_ready_to_confirm(api):
    """A group-drawn booking whose every booking-local precondition is satisfied.

    The booking is OPTION with its 25,000-cent deposit paid on an OPEN_FOR_SALE
    sailing; the only thing standing in the way of confirmation is that the block
    it drew from is still TENTATIVE.
    """
    world = fx.simple_world(
        api,
        voyage_code="CGB-2701",
        nights=4,
        total_lower_berths=20,
        physical_cabins=5,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    world.block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        cabins_held=2,
        review_date="2026-09-01T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    guest = fx.make_guest(api, prior_sailings_count=0)
    booking = fx.make_booking(
        api,
        world.sailing["id"],
        world.category["id"],
        guest["id"],
        occupancy_adults=1,
        group_block_id=world.block["id"],
    )
    assert booking["net_ticket_cents"] == 87500
    assert booking["deposit_due_cents"] == 25000
    fx.pay(api, booking["id"], "DEPOSIT", 25000)
    world.guest = guest
    world.booking = fx.read_booking(api, booking["id"])
    assert world.booking["booking_status"] == "OPTION"
    assert world.booking["payment_status"] == "DEPOSIT_PAID"
    return world


def test_confirm_is_refused_while_the_group_block_is_still_tentative(api):
    """Three of the four confirm conditions hold; the block's state is the fourth.

    PRD 3.5: "A ReservationAgent moves a booking OPTION -> CONFIRMED only when
    four conditions hold together: booking_status is currently OPTION ...;
    payment_status is DEPOSIT_PAID or PAID_IN_FULL, so the deposit has actually
    landed ...; the sailing is OPEN_FOR_SALE ...; and, if the booking carries
    group_block_id, that block has reached DEFINITE (otherwise
    ERR_GROUP_BLOCK_NOT_DEFINITE)."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_group_block_definite
    """
    world = _group_booking_ready_to_confirm(api)

    response = api.confirm_booking(world.booking["id"], RESERVATION_AGENT)
    validate_error(response, ERR_GROUP_BLOCK_NOT_DEFINITE, 409)

    booking = fx.read_booking(api, world.booking["id"])
    assert booking["booking_status"] == "OPTION"
    assert booking["payment_status"] == "DEPOSIT_PAID"

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["confirmed_bookings_count"] == 0
    assert fx.read_block(api, world.block["id"])["status"] == "TENTATIVE"


def test_signing_the_block_definite_unblocks_the_identical_confirm(api):
    """Moving the third entity is the whole change, and the same call now works.

    PRD 3.3: "Signing a block into a contracted hold moves it TENTATIVE ->
    DEFINITE." PRD 3.5: "Confirmation raises the sailing's
    confirmed_bookings_count by 1, recomputes final_payment_risk_flag, and
    increments the booking's version by 1", and the money dimension is untouched
    because "Neither dimension drives the other automatically".

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_group_block_definite
    """
    world = _group_booking_ready_to_confirm(api)
    validate_error(
        api.confirm_booking(world.booking["id"], RESERVATION_AGENT),
        ERR_GROUP_BLOCK_NOT_DEFINITE,
        409,
    )

    signed = fx.sign_definite(
        api, world.block["id"], contract_reference="CT-7001", headers=GROUP_SALES_AGENT_2
    )
    assert signed["status"] == "DEFINITE"

    confirmed = validate_success(
        api.confirm_booking(world.booking["id"], RESERVATION_AGENT)
    )
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_PAID"

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["confirmed_bookings_count"] == 1

    inventory = fx.read_inventory(api, world.inventory["id"])
    # PRD 3.4: the picked-up cabin moved from the fence into booked_cabins.
    assert inventory["booked_cabins"] == 1
    assert inventory["group_held_cabins"] == 1
    assert inventory["available_cabins"] == 3
    assert_capacity_identity(inventory)


def _bid_at_the_floor_with_the_only_ov_cabin_taken(api):
    """An IA bidder at exactly the floor, blocked by another guest's OV booking.

    The OV allotment has exactly one physical cabin and no oversell appetite, and
    an unrelated guest is sitting in it, so the target allotment's
    available_cabins is 0 at the moment of the award.
    """
    world = fx.upgrade_bid_world(api, voyage_code="AUR-2701", ov_physical_cabins=1)
    bidder = fx.make_guest(api, prior_sailings_count=0)
    ia_booking = fx.make_booking(
        api, world.sailing["id"], world.ia["id"], bidder["id"], occupancy_adults=2
    )
    assert ia_booking["net_ticket_cents"] == 379990
    assert ia_booking["projected_onboard_gross_cents"] == 126000

    occupant = fx.make_guest(api, prior_sailings_count=0)
    world.ov_booking = fx.make_booking(
        api, world.sailing["id"], world.ov["id"], occupant["id"], occupancy_adults=2
    )
    assert fx.read_inventory(api, world.inventory_ov["id"])["available_cabins"] == 0

    fx.set_clock(api, "2026-11-11T17:00:00Z")
    world.bidder = bidder
    world.booking = ia_booking
    world.bid = fx.submit_bid(api, ia_booking, bidder["id"], world.ov["id"], 21000)
    assert world.bid["min_acceptable_per_guest_cents"] == 21000
    return world


def test_bid_award_is_refused_while_the_target_allotment_is_full(api):
    """The blocking row belongs to a different cabin category than the bidder's.

    PRD 3.7: "A RevenueManager moves a bid SUBMITTED -> ACCEPTED when the bid is
    in SUBMITTED ..., its bid_amount_per_guest_cents is at least
    min_acceptable_per_guest_cents ..., the target category's allotment on the
    booking's sailing has available_cabins of at least 1 (otherwise
    ERR_TARGET_CATEGORY_UNAVAILABLE)".

    Design: Difficulty/cross_entity_state_dependency/bid_award_requires_target_allotment_availability
    """
    world = _bid_at_the_floor_with_the_only_ov_cabin_taken(api)

    response = api.accept_bid(world.bid["id"], REVENUE_MANAGER)
    validate_error(response, ERR_TARGET_CATEGORY_UNAVAILABLE, 422)

    bid = fx.read_bid(api, world.bid["id"])
    assert bid["status"] == "SUBMITTED"
    assert bid["award_amount_cents"] is None

    booking = fx.read_booking(api, world.booking["id"])
    assert booking["assigned_cabin_category_id"] == world.ia["id"]
    assert booking["upgrade_charge_cents"] == 0
    _, meta = validate_paginated(
        api.list_payment_events(world.booking["id"], REVENUE_MANAGER)
    )
    assert meta["total_count"] == 0


def test_freeing_the_target_cabin_lets_the_identical_award_through(api):
    """Cancelling an unrelated booking frees the cabin and the award cascades.

    PRD 3.6: "From OPTION or CONFIRMED, the allotment's booked_cabins falls by 1
    and available_cabins is recomputed." PRD 3.7 then fixes the cascade:
    "award_amount_cents is bid_amount_per_guest_cents multiplied by guest_count;
    the booking's assigned_cabin_category_id becomes the target category and its
    upgrade_charge_cents becomes the award amount; a payment event of kind
    UPGRADE_CHARGE for the award amount with note UPGRADE_AWARD is appended ...
    the booking's projected_onboard_gross_cents and projected_onboard_net_cents
    are recomputed against the target category's spend indices".

    Design: Difficulty/cross_entity_state_dependency/bid_award_requires_target_allotment_availability
    """
    world = _bid_at_the_floor_with_the_only_ov_cabin_taken(api)
    validate_error(
        api.accept_bid(world.bid["id"], REVENUE_MANAGER),
        ERR_TARGET_CATEGORY_UNAVAILABLE,
        422,
    )

    fx.cancelled_booking(api, world.ov_booking["id"])
    freed = fx.read_inventory(api, world.inventory_ov["id"])
    assert freed["booked_cabins"] == 0
    assert freed["available_cabins"] == 1

    accepted = validate_success(api.accept_bid(world.bid["id"], REVENUE_MANAGER))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["min_acceptable_per_guest_cents"] == 21000
    assert accepted["award_amount_cents"] == 42000

    booking = fx.read_booking(api, world.booking["id"])
    assert booking["assigned_cabin_category_id"] == world.ov["id"]
    # PRD 3.7: the sold category is a record of what was bought, never rewritten.
    assert booking["cabin_category_id"] == world.ia["id"]
    assert booking["upgrade_charge_cents"] == 42000
    assert booking["net_ticket_cents"] == 379990
    # 7 nights x 2 lower-berth guests x the OV index of 11,000.
    assert booking["projected_onboard_gross_cents"] == 154000

    events, meta = validate_paginated(
        api.list_payment_events(world.booking["id"], REVENUE_MANAGER)
    )
    assert meta["total_count"] == 1
    assert events[0]["kind"] == "UPGRADE_CHARGE"
    assert events[0]["amount_cents"] == 42000

    inv_ov = fx.read_inventory(api, world.inventory_ov["id"])
    assert inv_ov["booked_cabins"] == 1
    assert inv_ov["available_cabins"] == 0

    inv_ia = fx.read_inventory(api, world.inventory_ia["id"])
    assert inv_ia["booked_cabins"] == 0
    # PRD 2.7: ceil(60 x 0.10) is 6, and the appetite of 4 is the smaller arm.
    assert inv_ia["effective_oversell_cabins"] == 4
    assert inv_ia["available_cabins"] == 64
    assert_capacity_identity(inv_ia)
