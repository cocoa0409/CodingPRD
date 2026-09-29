"""
The guard rails: berth safety, aggregate fences, conditional and temporal gates.

Each scenario drives one rule to its refusal and then to its acceptance, so the
distinguishing input is the only thing that changed between the two calls.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_BERTH_SEQUENCE_INVALID,
    ERR_INSUFFICIENT_GROUP_INVENTORY,
    ERR_MAX_OCCUPANCY_EXCEEDED,
    ERR_OVERSELL_NOT_PERMITTED,
    ERR_PROMO_AUDIENCE_MISMATCH,
    ERR_REVIEW_DATE_IN_PAST,
    ERR_REVIEW_DATE_NOT_REACHED,
    GROUP_SALES_AGENT,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_instant_equals,
    assert_two_decimal_pct,
    assert_version_is,
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


def test_the_two_berth_safety_rules_raise_two_different_codes(api):
    """A party of three that fits the cabin is still refused if it skips a berth.

    PRD 3.4: "Berth safety comes before money. The party must fit the cabin
    category: guest_count may not exceed max_occupancy and occupancy_adults may not
    exceed lower_berths, or the sale is refused with ERR_MAX_OCCUPANCY_EXCEEDED.
    Berths also fill in order - selling a fourth berth while third_berth_guests is 0
    is refused with ERR_BERTH_SEQUENCE_INVALID. Both checks run before the fare is
    derived, so a nonsensical party never produces a price."

    Design: Corner/validations/a_fourth_berth_over_an_empty_third_berth_is_rejected
    """
    fx.set_clock(api)
    inside = fx.make_category(
        api,
        f.cabin_category_payload(
            code="IA",
            tier_rank=1,
            max_occupancy=4,
            lower_berths=2,
            is_guarantee=True,
        ),
    )
    triple = fx.make_category(
        api,
        f.cabin_category_payload(
            code="TRIPLE",
            tier_rank=2,
            max_occupancy=3,
            lower_berths=2,
            onboard_spend_lower_per_night_cents=10000,
            onboard_spend_upper_per_night_cents=6500,
        ),
    )
    solo = fx.make_category(
        api,
        f.cabin_category_payload(
            code="SOLO",
            tier_rank=3,
            max_occupancy=2,
            lower_berths=1,
            onboard_spend_lower_per_night_cents=12000,
            onboard_spend_upper_per_night_cents=7000,
        ),
    )

    sailing = fx.make_sailing(api, voyage_code="BRT-2701")
    inv_ia = fx.make_inventory(
        api, sailing["id"], inside["id"], physical_cabins=20, oversell_allowance=0
    )
    fx.make_inventory(
        api, sailing["id"], triple["id"], physical_cabins=10, oversell_allowance=0
    )
    fx.make_inventory(
        api, sailing["id"], solo["id"], physical_cabins=10, oversell_allowance=0
    )
    for category, base, third, fourth in (
        (inside, 189995, 64997, 49997),
        (triple, 199995, 66000, 50000),
        (solo, 209995, 70000, 55000),
    ):
        fx.make_fare_rule(
            api,
            sailing["id"],
            category["id"],
            window_open_days_to_sail=730,
            window_close_days_to_sail=0,
            base_lower_berth_fare_cents=base,
            third_berth_fare_cents=third,
            fourth_berth_fare_cents=fourth,
        )
    fx.open_sailing(api, sailing["id"])
    guest = fx.make_guest(api, full_name="Bo Chen", prior_sailings_count=0)

    # A party of three would fit IA's four berths; the gap at berth three is the fault.
    validate_error(
        api.create_booking(
            f.booking_payload(
                sailing["id"],
                inside["id"],
                guest["id"],
                occupancy_adults=2,
                third_berth_guests=0,
                fourth_berth_guests=1,
            ),
            RESERVATION_AGENT,
        ),
        ERR_BERTH_SEQUENCE_INVALID,
        422,
    )

    # 4 guests over a max_occupancy of 3, with the berths filled in order.
    validate_error(
        api.create_booking(
            f.booking_payload(
                sailing["id"],
                triple["id"],
                guest["id"],
                occupancy_adults=2,
                third_berth_guests=1,
                fourth_berth_guests=1,
            ),
            RESERVATION_AGENT,
        ),
        ERR_MAX_OCCUPANCY_EXCEEDED,
        422,
    )

    # guest_count 2 is inside max_occupancy 2, but 2 adults need 2 lower berths.
    validate_error(
        api.create_booking(
            f.booking_payload(
                sailing["id"], solo["id"], guest["id"], occupancy_adults=2
            ),
            RESERVATION_AGENT,
        ),
        ERR_MAX_OCCUPANCY_EXCEEDED,
        422,
    )

    _, meta = validate_paginated(
        api.list_bookings(RESERVATION_AGENT, params={"sailing_id": sailing["id"]})
    )
    # No price was ever derived, so no row was ever written.
    assert meta["total_count"] == 0
    assert fx.read_inventory(api, inv_ia["id"])["booked_cabins"] == 0
    assert fx.read_guest(api, guest["id"])["bookings_count"] == 0


def test_a_cabin_filled_to_its_limit_in_order_is_priced_and_sold(api):
    """The accepted mirror image, which is the only path that prices upper berths.

    PRD 3.4 step 5: "third_berth_net_cents is third_berth_fare_cents multiplied by one
    minus berth_discount_pct, rounded half up to a whole cent, and then multiplied by
    third_berth_guests ... The berth discount applies to upper berths only; the
    lower-berth subtotal is never reduced by it." Step 11: "deposit_due_cents is the
    larger of two figures: 25,000 cents (250.00 in whole currency units) per guest,
    multiplied by guest_count; and net_ticket_cents multiplied by one fifth, rounded
    half up."

    Design: Corner/validations/a_party_of_four_in_a_four_berth_category_is_accepted
    """
    world = fx.simple_world(
        api,
        voyage_code="OKB-2701",
        category_overrides={"max_occupancy": 4, "lower_berths": 2},
        physical_cabins=60,
        oversell_allowance=4,
    )
    guest = fx.make_guest(api, full_name="Bo Chen", prior_sailings_count=0)

    booking = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
                third_berth_guests=1,
                fourth_berth_guests=1,
            ),
            RESERVATION_AGENT,
        ),
        201,
    )
    assert booking["booking_status"] == "OPTION"
    assert booking["guest_count"] == 4

    assert booking["lower_berth_subtotal_cents"] == 379990
    # 379,990 clears the 250,000 floor and misses the 400,000 one.
    assert float(booking["berth_discount_pct"]) == 0.10
    assert_two_decimal_pct(booking["berth_discount_pct"], "berth_discount_pct")
    # 64,997 x 0.90 is 58,497.3 and 49,997 x 0.90 is 44,997.3.
    assert booking["third_berth_net_cents"] == 58497
    assert booking["fourth_berth_net_cents"] == 44997

    # The discount never touches the 379,990 of lower-berth money.
    assert booking["gross_ticket_cents"] == 483484
    assert booking["net_ticket_cents"] == 483484
    # 25,000 x 4 beats round(483,484 / 5) == 96,697.
    assert booking["deposit_due_cents"] == 100000
    # 7 nights x (2 x 9,000 lower + 2 x 6,000 upper).
    assert booking["projected_onboard_gross_cents"] == 210000

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["lower_berths_sold"] == 2
    assert sailing["third_berths_sold"] == 1
    assert sailing["fourth_berths_sold"] == 1
    # 2 of 200 lower berths.
    assert float(sailing["occupancy_pct"]) == 1.0
    assert_two_decimal_pct(sailing["occupancy_pct"], "occupancy_pct")
    # (483,484 + 210,000) over 200 x 7 is 495.345...
    assert sailing["ralbd_gross_cents"] == 495

    inventory = fx.read_inventory(api, world.inventory["id"])
    # 60 physical plus 4 oversell, less the one cabin just sold.
    assert inventory["available_cabins"] == 63
    assert_capacity_identity(inventory)


def test_a_hold_is_measured_against_what_every_other_block_left_behind(api):
    """Two cabins were legal on an empty allotment and are illegal on this one.

    PRD 3.3: group block creation "requires the allotment to actually have room:
    available_cabins must be at least the requested cabins_held, otherwise the request
    is refused with ERR_INSUFFICIENT_GROUP_INVENTORY." PRD 2.7 makes that figure an
    aggregate one, because group_held_cabins is "the sum, over every group block on the
    same sailing and cabin category whose status is TENTATIVE, DEFINITE, or
    PARTIALLY_RELEASED, of that block's cabins_held minus its picked_up_cabins".

    Design: Corner/validations/group_block_creation_needs_the_whole_hold_free_at_once
    """
    world = fx.simple_world(
        api,
        voyage_code="AGG-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=5,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        agency_name="Meridian Travel",
        cabins_held=2,
        release_policy="ATTRITION_50",
    )
    fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        agency_name="Harbour Tours",
        cabins_held=2,
        release_policy="FULL_RELEASE",
    )
    fenced = fx.read_inventory(api, world.inventory["id"])
    assert fenced["group_held_cabins"] == 4
    assert fenced["available_cabins"] == 1

    # Two cabins would have been legal against the empty allotment.
    validate_error(
        api.create_group_block(
            f.group_block_payload(
                world.sailing["id"],
                world.category["id"],
                agency_name="Overreach Travel",
                cabins_held=2,
            ),
            GROUP_SALES_AGENT,
        ),
        ERR_INSUFFICIENT_GROUP_INVENTORY,
        422,
    )

    last = validate_success(
        api.create_group_block(
            f.group_block_payload(
                world.sailing["id"],
                world.category["id"],
                agency_name="Lastcabin Travel",
                cabins_held=1,
            ),
            GROUP_SALES_AGENT,
        ),
        201,
    )
    assert last["status"] == "TENTATIVE"
    assert last["cabins_held"] == 1

    # available_cabins is now 0, so even a single cabin is out of reach.
    validate_error(
        api.create_group_block(
            f.group_block_payload(
                world.sailing["id"],
                world.category["id"],
                agency_name="Toolate Travel",
                cabins_held=1,
            ),
            GROUP_SALES_AGENT,
        ),
        ERR_INSUFFICIENT_GROUP_INVENTORY,
        422,
    )

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["group_held_cabins"] == 5
    assert inventory["booked_cabins"] == 0
    assert inventory["available_cabins"] == 0
    assert_capacity_identity(inventory)

    _, meta = validate_paginated(
        api.list_group_blocks(
            GROUP_SALES_AGENT, params={"sailing_id": world.sailing["id"]}
        )
    )
    # Neither refused block was stored.
    assert meta["total_count"] == 3

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["available_lower_berth_days_gross"] == 160
    # 5 held cabins fence 10 lower berths, leaving 30 over 4 nights.
    assert sailing["available_lower_berth_days_net"] == 120


def test_the_same_allowance_write_is_refused_at_two_and_accepted_at_zero(api):
    """The rule keys on an appetite above zero, not on the field being present.

    PRD 3.1: "A non-zero oversell_allowance on a category whose is_guarantee is false is
    rejected with ERR_OVERSELL_NOT_PERMITTED, both at creation and on any later
    re-set." PRD 2.7: "if the category is not a guarantee category,
    effective_oversell_cabins is zero regardless of what oversell_allowance says."

    Design: Corner/validations/oversell_allowance_is_only_legal_on_a_guarantee_category
    """
    fx.set_clock(api)
    guarantee = fx.make_category(api, f.guarantee_category_payload())
    named = fx.make_category(api, f.ocean_view_category_payload())
    assert guarantee["is_guarantee"] is True
    assert named["is_guarantee"] is False

    sailing = fx.make_sailing(api, voyage_code="CND-2701")
    inv_named = fx.make_inventory(
        api, sailing["id"], named["id"], physical_cabins=30, oversell_allowance=0
    )
    named_version = inv_named["version"]

    inv_guarantee = validate_success(
        api.create_sailing_inventory(
            f.sailing_inventory_payload(
                sailing["id"],
                guarantee["id"],
                physical_cabins=60,
                oversell_allowance=4,
            ),
            REVENUE_MANAGER,
        ),
        201,
    )
    # An appetite of 4 is inside the ceiling of ceil(60 x 0.10) == 6.
    assert inv_guarantee["effective_oversell_cabins"] == 4
    assert inv_guarantee["available_cabins"] == 64
    guarantee_version = inv_guarantee["version"]

    # The version is current, so this is a domain refusal and not a stale-version one.
    validate_error(
        api.patch_sailing_inventory(
            inv_named["id"],
            {"oversell_allowance": 2, "expected_inventory_version": named_version},
            REVENUE_MANAGER,
        ),
        ERR_OVERSELL_NOT_PERMITTED,
        422,
    )
    untouched = fx.read_inventory(api, inv_named["id"])
    assert untouched["oversell_allowance"] == 0
    assert_version_is(untouched, named_version)

    # The identical write of 0 is always legal on a named category.
    zeroed = validate_success(
        api.patch_sailing_inventory(
            inv_named["id"],
            {"oversell_allowance": 0, "expected_inventory_version": named_version},
            REVENUE_MANAGER,
        )
    )
    assert_version_is(zeroed, named_version + 1)
    assert zeroed["effective_oversell_cabins"] == 0
    assert zeroed["available_cabins"] == 30

    lowered = validate_success(
        api.patch_sailing_inventory(
            inv_guarantee["id"],
            {"oversell_allowance": 2, "expected_inventory_version": guarantee_version},
            REVENUE_MANAGER,
        )
    )
    assert_version_is(lowered, guarantee_version + 1)
    assert lowered["effective_oversell_cabins"] == 2
    assert lowered["available_cabins"] == 62

    # Allotment maintenance never needed the sailing to be selling.
    assert fx.read_sailing(api, sailing["id"])["status"] == "PLANNED"


def test_the_review_guard_is_inclusive_and_the_extension_guard_is_strict(api):
    """One instant later the same refused call is a release, with nothing else changed.

    PRD 3.3: "A review is available from TENTATIVE or PARTIALLY_RELEASED, and only once
    the current instant has reached the block's review_date - an earlier attempt is
    refused with ERR_REVIEW_DATE_NOT_REACHED", while an extension "supplies
    new_review_date, which must be strictly after the current instant (otherwise
    ERR_REVIEW_DATE_IN_PAST)". On the release, "under ATTRITION_50 it is the remainder
    multiplied by one half and rounded down to a whole cabin", and "An empty eligible
    pool is a silent no-op, never an error."

    Design: Corner/validations/reviewing_a_block_before_its_review_date_is_refused
    """
    world = fx.simple_world(
        api,
        voyage_code="TMP-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    block = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        cabins_held=4,
        review_date="2026-08-16T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    created_version = block["version"]
    fenced = fx.read_sailing(api, world.sailing["id"])
    # 4 held cabins fence 8 lower berths, leaving 32 over 4 nights.
    assert fenced["available_lower_berth_days_net"] == 128

    # 2026-08-01 is 15 days short of the review date.
    validate_error(
        api.review_group_block(block["id"], GROUP_SALES_AGENT),
        ERR_REVIEW_DATE_NOT_REACHED,
        422,
    )
    early = fx.read_block(api, block["id"])
    assert early["status"] == "TENTATIVE"
    assert early["cabins_held"] == 4
    assert early["review_count"] == 0
    assert_version_is(early, created_version)

    validate_error(
        api.extend_review(
            block["id"],
            {"new_review_date": "2026-07-01T00:00:00Z"},
            GROUP_SALES_AGENT,
        ),
        ERR_REVIEW_DATE_IN_PAST,
        422,
    )
    unmoved = fx.read_block(api, block["id"])
    assert_instant_equals(
        unmoved["review_date"], "2026-08-16T00:00:00Z", "review_date"
    )
    assert unmoved["review_extension_count"] == 0

    # Exactly on the review date the guard admits the call.
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    reviewed = validate_success(api.review_group_block(block["id"], GROUP_SALES_AGENT))
    assert reviewed["status"] == "PARTIALLY_RELEASED"
    # floor(4 x 0.5) hands back 2 of the 4 unpicked cabins.
    assert reviewed["cabins_held"] == 2
    assert reviewed["released_cabins_total"] == 2
    assert reviewed["review_count"] == 1
    assert_version_is(reviewed, created_version + 1)

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["group_held_cabins"] == 2
    assert inventory["released_cabins_total"] == 2
    assert inventory["available_cabins"] == 8
    # There was nothing queued, so the waitlist pass did nothing at all.
    assert inventory["waitlisted_bookings_count"] == 0
    assert inventory["booked_cabins"] == 0
    assert_capacity_identity(inventory)

    sailing = fx.read_sailing(api, world.sailing["id"])
    # 2 held cabins now fence 4 lower berths, leaving 36 over 4 nights.
    assert sailing["available_lower_berth_days_net"] == 144
    assert sailing["available_lower_berth_days_gross"] == 160


def test_one_campaign_two_guests_and_only_the_returning_one_is_quoted(api):
    """The identical request body succeeds or fails on a fact stored elsewhere.

    PRD 3.4: a quoted campaign's "audience must match the booking, or the sale is
    refused with ERR_PROMO_AUDIENCE_MISMATCH ... a REPEAT_GUEST campaign requires the
    guest's loyalty_tier to be anything other than NONE", and "A successful quote raises
    the campaign's redemption_count by 1". Step 9: "loyalty_discount_cents is the sum of
    three independently rounded amounts: each post-promotion component multiplied by the
    guest's repeat_guest_offer_pct and rounded half up."

    Design: Corner/validations/a_repeat_guest_promotion_is_refused_for_a_guest_with_no_history
    """
    world = fx.simple_world(api, voyage_code="AUD-2701")
    promotion = fx.make_promotion(
        api,
        world.sailing["id"],
        world.sailing["version"],
        code="REPEATONLY",
        audience="REPEAT_GUEST",
    )
    fx.activate_promotion(api, promotion["id"])

    newcomer = fx.make_guest(
        api, full_name="Nell Newman", email="nell@example.com", prior_sailings_count=0
    )
    returner = fx.make_guest(
        api, full_name="Gil Gold", email="gil@example.com", prior_sailings_count=3
    )
    assert newcomer["loyalty_tier"] == "NONE"
    assert returner["loyalty_tier"] == "GOLD"

    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                newcomer["id"],
                occupancy_adults=2,
                promotion_id=promotion["id"],
            ),
            RESERVATION_AGENT,
        ),
        ERR_PROMO_AUDIENCE_MISMATCH,
        422,
    )
    # The audience gate sits before the money, so nothing was spent or counted.
    assert fx.read_promotion(api, promotion["id"])["redemption_count"] == 0
    assert fx.read_guest(api, newcomer["id"])["bookings_count"] == 0

    admitted = validate_success(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                returner["id"],
                occupancy_adults=2,
                promotion_id=promotion["id"],
            ),
            RESERVATION_AGENT,
        ),
        201,
    )
    # round(379,990 x 0.10).
    assert admitted["promo_discount_cents"] == 37999
    # round((379,990 - 37,999) x 0.03) == round(10,259.73).
    assert admitted["loyalty_discount_cents"] == 10260
    assert admitted["net_ticket_cents"] == 331731
    # max(25,000 x 2, round(331,731 / 5) == 66,346).
    assert admitted["deposit_due_cents"] == 66346

    quoted = fx.read_promotion(api, promotion["id"])
    assert quoted["redemption_count"] == 1
    # 1 of 5 redemptions, so the cap is nowhere near.
    assert quoted["status"] == "ACTIVE"

    _, meta = validate_paginated(
        api.list_bookings(RESERVATION_AGENT, params={"promotion_id": promotion["id"]})
    )
    assert meta["total_count"] == 1
