"""The six-step quote and the three-step protection premium, exercised on the
branches where a selector — not just a sum — changes."""

from test_helpers import (
    CauseCode,
    LoyaltyTier,
    PlanTier,
    SettlementStatus,
    TowingTier,
    VehicleClass,
    assert_booking_quote_identity,
    factories,
    fixtures,
    validate_success,
)


def _confirm(api, world, booking_id):
    """Owner approval followed by the renter's own confirmation call."""
    fixtures.approve_booking(api, world, booking_id)
    return validate_success(api.confirm_booking(booking_id, world.renter_headers), 200)


def _alternate_plan(api, **overrides):
    """A second protection plan under a distinct tier."""
    return fixtures.create_protection_plan(api, **overrides)


def test_a_pickup_quote_keys_the_loyalty_tier_on_the_pre_discount_figure(api):
    """PRD 3.5: "Step two selects the `loyalty_tier` from that **pre-discount
    figure and from nothing else**: a pre-discount figure of at least 150000 cents
    selects `LOYALTY_TIER_2` at 700 basis points, a figure of at least 100000 cents
    but below 150000 selects `LOYALTY_TIER_1` at 400 basis points, and anything
    below 100000 cents selects `NONE` at 0 basis points." On a `PICKUP` booking
    "`delivery_fee_cents` is 0, because no delivery assignment exists yet", so the
    pre-discount figure stops short of the second band even though the grand total
    clears it.

    Design: Difficulty/combinatorial_formula/quote_mode_pickup_tier_keyed_on_pre_discount_not_grand_total
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["base_subtotal_cents"] == 110896
    assert confirmed["premium_cents"] == 24951
    assert confirmed["delivery_fee_cents"] == 0
    assert confirmed["loyalty_tier"] == LoyaltyTier.TIER_1
    assert confirmed["loyalty_discount_cents"] == 5434
    assert confirmed["service_fee_cents"] == 15650
    assert confirmed["estimated_overage_cents"] == 0
    assert confirmed["quoted_total_cents"] == 146063


def test_the_pickup_hold_matches_the_quoted_total_to_the_cent(api):
    """PRD 3.7: "the quote is recomputed from scratch ... all through the six steps
    of §3.5, picking up any delivery fee that landed in the meantime — and
    `hold_amount_cents` is set to the resulting `quoted_total_cents`." PRD 3.5
    fixes the last step: "Step six computes `estimated_overage_cents` from the
    declared estimates as described in §3.7 and sets `quoted_total_cents` to the
    discounted subtotal plus `service_fee_cents` plus `estimated_overage_cents`."

    Design: Difficulty/combinatorial_formula/quote_mode_pickup_tier_keyed_on_pre_discount_not_grand_total
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    confirmed = _confirm(api, world, booking["id"])

    assert_booking_quote_identity(confirmed)
    assert confirmed["quoted_total_cents"] == 146063
    assert confirmed["hold_amount_cents"] == 146063
    assert confirmed["settlement_status"] == SettlementStatus.HELD


def test_a_scheduled_dropoff_fee_pushes_the_quote_into_the_second_loyalty_band(api):
    """PRD 3.6 prices the delivery: "The new row's `delivery_fee_cents` is then
    computed as the listing's `delivery_base_fee_cents`, plus the listing's
    `delivery_per_mile_cents` multiplied by the assignment's `distance_miles`, plus
    the assignment's `setup_fee_cents`". That term enters step one, and PRD 3.5
    keys the band on the result: "Step one adds `base_subtotal_cents`,
    `premium_cents` and `delivery_fee_cents` into a pre-discount figure".

    Design: Difficulty/combinatorial_formula/quote_mode_campground_dropoff_delivery_term_crosses_into_tier_2
    """
    world = fixtures.seed_marketplace(api)
    booking, _assignment = fixtures.seed_scheduled_dropoff(api, world)

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["delivery_fee_cents"] == 31000
    assert confirmed["loyalty_tier"] == LoyaltyTier.TIER_2
    assert confirmed["loyalty_discount_cents"] == 11679


def test_the_dropoff_service_fee_is_billed_on_the_discounted_subtotal(api):
    """PRD 3.5: "Step four subtracts that discount from the pre-discount figure to
    give the discounted subtotal. Step five computes `service_fee_cents` as the
    discounted subtotal multiplied by 1200 basis points — a flat twelve percent —
    divided by 10000 and rounded half up; the fee base is the discounted subtotal
    and **excludes overages entirely**." A larger delivery term therefore moves the
    fee base as well as the band.

    Design: Difficulty/combinatorial_formula/quote_mode_campground_dropoff_delivery_term_crosses_into_tier_2
    """
    world = fixtures.seed_marketplace(api)
    booking, _assignment = fixtures.seed_scheduled_dropoff(api, world)

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["service_fee_cents"] == 18620
    assert confirmed["quoted_total_cents"] == 173788
    assert confirmed["hold_amount_cents"] == 173788
    assert_booking_quote_identity(confirmed)


def test_a_high_daily_floor_wins_the_premium_max_and_flips_the_loyalty_band(api):
    """PRD 3.5: "First the platform takes the larger of two candidates: the plan's
    `daily_premium_cents` multiplied by the booking's `nights`, and the booking's
    `base_subtotal_cents` multiplied by the plan's `premium_pct_of_base_bp`, divided
    by 10000 and rounded half up to whole cents. The larger of those two is the tier
    premium." A nine-thousand-cent nightly floor over four nights beats the
    percentage term, and the bigger premium carries the pre-discount figure into the
    second loyalty band.

    Design: Difficulty/combinatorial_formula/premium_mode_daily_floor_term_wins_the_max_and_flips_loyalty_tier
    """
    world = fixtures.seed_marketplace(api)
    premium_plan = _alternate_plan(
        api,
        tier=PlanTier.PREMIUM,
        daily_premium_cents=9000,
        deductible_cents=100000,
        excluded_causes=[],
    )
    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, premium_plan["id"], world.policy_id
            ),
            world.renter_headers,
        ),
        201,
    )

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["base_subtotal_cents"] == 110896
    assert confirmed["premium_cents"] == 45000
    assert confirmed["loyalty_tier"] == LoyaltyTier.TIER_2
    assert confirmed["loyalty_discount_cents"] == 10913


def test_the_towing_surcharge_is_taken_on_the_winning_floor_term(api):
    """PRD 3.5: "Next, when the listing's `requires_towing` is true and the
    booking's frozen `towing_verified_tier` is exactly `BASIC`, a towing surcharge
    equal to 2500 basis points — a quarter — of the tier premium is computed,
    divided by 10000 and rounded half up". The tier premium is whichever candidate
    won the max, so the surcharge follows the floor term and the whole quote moves
    with it.

    Design: Difficulty/combinatorial_formula/premium_mode_daily_floor_term_wins_the_max_and_flips_loyalty_tier
    """
    world = fixtures.seed_marketplace(api)
    premium_plan = _alternate_plan(
        api,
        tier=PlanTier.PREMIUM,
        daily_premium_cents=9000,
        deductible_cents=100000,
        excluded_causes=[],
    )
    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, premium_plan["id"], world.policy_id
            ),
            world.renter_headers,
        ),
        201,
    )
    assert booking["towing_verified_tier"] == TowingTier.BASIC

    confirmed = _confirm(api, world, booking["id"])

    # 36000 floor term plus a quarter of it, not a quarter of the 19961 percentage term.
    assert confirmed["premium_cents"] == 45000
    assert confirmed["service_fee_cents"] == 17398
    assert confirmed["quoted_total_cents"] == 162381
    assert_booking_quote_identity(confirmed)


def test_a_small_coverage_ceiling_caps_the_premium_after_the_surcharge(api):
    """PRD 3.5: "Finally the premium is capped: `premium_cents` is the smaller of
    the tier premium plus the surcharge, and 1500 basis points — fifteen percent —
    of the plan's `coverage_ceiling_cents`, that second figure being divided by
    10000 and rounded half up." A hundred-thousand-cent ceiling caps at 15000,
    discarding both inner terms.

    Design: Difficulty/combinatorial_formula/premium_mode_coverage_ceiling_cap_binds_the_min
    """
    world = fixtures.seed_marketplace(api)
    capped_plan = _alternate_plan(
        api,
        tier=PlanTier.BASIC,
        daily_premium_cents=4900,
        premium_pct_of_base_bp=1800,
        deductible_cents=250000,
        coverage_ceiling_cents=100000,
        excluded_causes=[CauseCode.AWNING_WIND, CauseCode.INTERIOR_STAIN],
        eligible_vehicle_classes=[
            VehicleClass.TRAVEL_TRAILER,
            VehicleClass.FIFTH_WHEEL,
        ],
    )
    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, capped_plan["id"], world.policy_id
            ),
            world.renter_headers,
        ),
        201,
    )

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["base_subtotal_cents"] == 110896
    assert confirmed["premium_cents"] == 15000


def test_the_capped_premium_leaves_the_quote_in_the_first_loyalty_band(api):
    """PRD 3.5: "Step two selects the `loyalty_tier` from that **pre-discount figure
    and from nothing else**". Because the cap pushes the premium down rather than up,
    the pre-discount figure stays inside "a figure of at least 100000 cents but below
    150000 selects `LOYALTY_TIER_1` at 400 basis points".

    Design: Difficulty/combinatorial_formula/premium_mode_coverage_ceiling_cap_binds_the_min
    """
    world = fixtures.seed_marketplace(api)
    capped_plan = _alternate_plan(
        api,
        tier=PlanTier.BASIC,
        daily_premium_cents=4900,
        premium_pct_of_base_bp=1800,
        deductible_cents=250000,
        coverage_ceiling_cents=100000,
        excluded_causes=[CauseCode.AWNING_WIND, CauseCode.INTERIOR_STAIN],
        eligible_vehicle_classes=[
            VehicleClass.TRAVEL_TRAILER,
            VehicleClass.FIFTH_WHEEL,
        ],
    )
    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, capped_plan["id"], world.policy_id
            ),
            world.renter_headers,
        ),
        201,
    )

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["loyalty_tier"] == LoyaltyTier.TIER_1
    assert confirmed["loyalty_discount_cents"] == 5036
    assert confirmed["service_fee_cents"] == 14503
    assert confirmed["quoted_total_cents"] == 135363
    assert_booking_quote_identity(confirmed)


def test_the_nightly_subtotal_rounds_each_night_before_adding(api):
    """PRD 3.5: "for each night of the sharing period, starting at `start_date` and
    running through the night before `end_date`, the platform resolves that night's
    seasonal multiplier by the selector of §3.1, multiplies the listing's
    `base_nightly_rate_cents` by that multiplier in basis points, divides by 10000,
    rounds the result half up to a whole number of cents, and adds that whole-cent
    figure to the running subtotal. The rounding happens **once per night, before
    the addition**." Three peak nights at 29070 plus one shoulder night at 23686 is
    110896; "Summing the unrounded per-night products and rounding the total once at
    the end produces a different number and is not the rule."

    Design: Difficulty/boundary_precision_check/nightly_subtotal_rounds_per_night_not_once_at_the_end
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["nights"] == 4
    assert confirmed["base_subtotal_cents"] == 29070 + 29070 + 29070 + 23686
    assert confirmed["base_subtotal_cents"] == 110896
    assert confirmed["base_subtotal_cents"] != 110895


def test_the_one_cent_rounding_difference_propagates_into_the_quote(api):
    """PRD 3.5: "The rounding happens **once per night, before the addition**." The
    single cent it creates then travels the whole chain, because "the order is not
    negotiable because the discount depends on a subtotal, the fee depends on the
    discounted subtotal, and the total depends on the fee."

    Design: Difficulty/boundary_precision_check/nightly_subtotal_rounds_per_night_not_once_at_the_end
    """
    world = fixtures.seed_marketplace(api)
    booking = fixtures.seed_requested_booking(api, world)

    confirmed = _confirm(api, world, booking["id"])

    assert confirmed["premium_cents"] == 24951
    assert confirmed["loyalty_tier"] == LoyaltyTier.TIER_1
    assert confirmed["loyalty_discount_cents"] == 5434
    assert confirmed["service_fee_cents"] == 15650
    assert confirmed["quoted_total_cents"] == 146063
    assert_booking_quote_identity(confirmed)


def test_the_protection_premium_composes_floor_surcharge_and_ceiling(api):
    """PRD 3.5: "The **protection premium**, `premium_cents`, is a floor, a
    surcharge and a ceiling applied in that order." On the canonical trailer the
    percentage term wins the max at 19961, "a towing surcharge equal to 2500 basis
    points — a quarter — of the tier premium" adds 4990, and the fifteen-percent
    ceiling on a three-million-cent plan does not bind.

    Design: Corner/calculations/protection_premium_takes_the_max_then_the_surcharge_then_the_cap
    """
    world = fixtures.seed_marketplace(api)

    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, world.plan_id, world.policy_id
            ),
            world.renter_headers,
        ),
        201,
    )

    assert booking["base_subtotal_cents"] == 110896
    assert booking["towing_verified_tier"] == TowingTier.BASIC
    assert booking["premium_cents"] == 19961 + 4990
    assert booking["premium_cents"] == 24951


def test_declared_overage_does_not_widen_the_service_fee_base(api):
    """PRD 3.5: "Step five computes `service_fee_cents` as the discounted subtotal
    multiplied by 1200 basis points — a flat twelve percent — divided by 10000 and
    rounded half up; the fee base is the discounted subtotal and **excludes overages
    entirely**." PRD 3.7 supplies the overage itself: "the amount by which
    `declared_miles` exceeds `nights` multiplied by `included_miles_per_night` — zero
    if it does not — multiplied by `mileage_overage_rate_cents_per_mile`".

    Design: Corner/calculations/service_fee_base_excludes_overages_and_uses_the_declared_bp
    """
    world = fixtures.seed_marketplace(api)

    booking = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id,
                world.renter_id,
                world.plan_id,
                world.policy_id,
                declared_miles=500,
            ),
            world.renter_headers,
        ),
        201,
    )

    assert booking["base_subtotal_cents"] == 110896
    assert booking["premium_cents"] == 24951
    assert booking["loyalty_tier"] == LoyaltyTier.TIER_1
    assert booking["loyalty_discount_cents"] == 5434
    # 100 miles beyond the 400-mile allowance at 65 cents a mile.
    assert booking["estimated_overage_cents"] == 6500
    assert booking["service_fee_cents"] == 15650
    assert booking["quoted_total_cents"] == 152563
    assert_booking_quote_identity(booking)
