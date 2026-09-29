"""
The error catalogue: which code wins, and what the refusal leaves behind.

Every refusal here is checked twice - once on the code and status, and once on the
state the rejected request must not have moved, because PRD 2.10 makes the *first*
failure the whole response and PRD 2.2 gives a rejected write no side effects.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_BID_BELOW_FLOOR,
    ERR_BID_NOT_COUNTERED,
    ERR_BID_NOT_PENDING,
    ERR_BID_WINDOW_CLOSED,
    ERR_BOOKING_NOT_IN_OPTION,
    ERR_DEPOSIT_BELOW_MINIMUM,
    ERR_DEPOSIT_NOT_PAID,
    ERR_DUPLICATE_CATEGORY_CODE,
    ERR_DUPLICATE_GUEST_EMAIL,
    ERR_DUPLICATE_INVENTORY,
    ERR_DUPLICATE_PROMO_CODE,
    ERR_DUPLICATE_TIER_RANK,
    ERR_DUPLICATE_VOYAGE_CODE,
    ERR_FARE_RULE_NOT_FOUND,
    ERR_FINAL_PAYMENT_SHORT,
    ERR_GROUP_BLOCK_CLOSED,
    ERR_GROUP_BLOCK_EXHAUSTED,
    ERR_GROUP_BLOCK_NOT_FOUND,
    ERR_ITINERARY_CHANGE_NOT_FOUND,
    ERR_MAX_REVIEW_EXTENSIONS_EXCEEDED,
    ERR_NOT_GUARANTEE_BOOKING,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_PAYMENT_STATE_INVALID,
    ERR_PROMO_WINDOW_NOT_CURRENT,
    ERR_PROMOTION_NOT_FOUND,
    ERR_SAILING_INVENTORY_NOT_FOUND,
    ERR_UPGRADE_BID_NOT_FOUND,
    GROUP_SALES_AGENT,
    GROUP_SALES_AGENT_2,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_instant_equals,
    assert_two_decimal_pct,
    assert_version_is,
    factories as f,
    fixtures as fx,
    ids_of,
    make_guest_headers,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_five_specific_duplicate_codes_beat_the_generic_shape_error(api):
    """Uniqueness lives in the shape tier, and the specific code wins every time.

    PRD 2.10 tier 4: "Uniqueness is checked at this same tier, and the specific code
    wins over the generic one: a repeated `voyage_code` gives
    `ERR_DUPLICATE_VOYAGE_CODE`, a repeated cabin-category `code` gives
    `ERR_DUPLICATE_CATEGORY_CODE`, a repeated `tier_rank` gives
    `ERR_DUPLICATE_TIER_RANK`, a repeated guest `email` gives
    `ERR_DUPLICATE_GUEST_EMAIL`, and a promotion `code` repeated within the same
    `sailing_id` gives `ERR_DUPLICATE_PROMO_CODE`. All six of these codes carry HTTP
    400." The sixth is the allotment: PRD 2.10 tier 19 lists `ERR_DUPLICATE_INVENTORY`
    among the capacity codes "all at HTTP 422". PRD 3.2 scopes the campaign code: "a
    `code` of at most 24 characters that must be unique among the promotions of that
    same sailing (a repeat is `ERR_DUPLICATE_PROMO_CODE`)".

    Design: Corner/errors/uniqueness_collisions_return_their_dedicated_duplicate_errors
    """
    world = fx.simple_world(api, voyage_code="DUP-2701")
    opened_version = world.sailing["version"]
    promo = fx.make_promotion(
        api,
        world.sailing["id"],
        opened_version,
        code="SUMMERGA",
        starts_on="2026-08-01T00:00:00Z",
        ends_on="2026-08-10T00:00:00Z",
    )
    assert promo["status"] == "SCHEDULED"
    other = fx.make_sailing(api, voyage_code="DUP-2702", embark_date="2027-02-14T17:00:00Z")
    guest = fx.make_guest(api, email="ada@example.com", prior_sailings_count=0)

    # Same voyage code, everything else different: the ship and the dates do not save it.
    validate_error(
        api.create_sailing(
            f.sailing_payload(
                voyage_code="DUP-2701",
                ship_code="BOREALIS",
                embark_date="2027-03-01T17:00:00Z",
                nights=10,
                total_lower_berths=400,
            ),
            REVENUE_MANAGER,
        ),
        ERR_DUPLICATE_VOYAGE_CODE,
        400,
    )

    # The code collides even though the tier_rank is free.
    validate_error(
        api.create_cabin_category(
            f.cabin_category_payload(code="IA", tier_rank=9),
            REVENUE_MANAGER,
        ),
        ERR_DUPLICATE_CATEGORY_CODE,
        400,
    )
    # And the tier_rank collides even though the code is free.
    validate_error(
        api.create_cabin_category(
            f.cabin_category_payload(code="SPA", tier_rank=1),
            REVENUE_MANAGER,
        ),
        ERR_DUPLICATE_TIER_RANK,
        400,
    )

    validate_error(
        api.create_guest(
            f.guest_payload(email="ada@example.com", full_name="Ada Twin"),
            RESERVATION_AGENT,
        ),
        ERR_DUPLICATE_GUEST_EMAIL,
        400,
    )

    # An identical interval is both a duplicate code and a cadence clash; tier 4
    # is evaluated before tier 16, so only the duplicate surfaces.
    validate_error(
        api.create_promotion(
            f.promotion_payload(
                world.sailing["id"],
                fx.read_sailing(api, world.sailing["id"])["version"],
                code="SUMMERGA",
                starts_on="2026-08-01T00:00:00Z",
                ends_on="2026-08-10T00:00:00Z",
            ),
            REVENUE_MANAGER,
        ),
        ERR_DUPLICATE_PROMO_CODE,
        400,
    )

    # One allotment per sailing and cabin category pair.
    validate_error(
        api.create_sailing_inventory(
            f.sailing_inventory_payload(
                world.sailing["id"],
                world.category["id"],
                physical_cabins=25,
                oversell_allowance=0,
            ),
            REVENUE_MANAGER,
        ),
        ERR_DUPLICATE_INVENTORY,
        422,
    )

    inventory = fx.read_inventory(api, world.inventory["id"])
    # The rejected re-creation left the stored allotment exactly as it was.
    assert inventory["physical_cabins"] == 60
    assert inventory["oversell_allowance"] == 4
    assert_version_is(inventory, world.inventory["version"])

    sailing = fx.read_sailing(api, world.sailing["id"])
    # Only the accepted campaign bumped the parent sailing.
    assert sailing["version"] == opened_version + 1

    # The same campaign code on a different sailing is not a duplicate at all.
    twin = fx.make_promotion(api, other["id"], other["version"], code="SUMMERGA")
    assert twin["status"] == "SCHEDULED"
    assert twin["sailing_id"] == other["id"]

    both, meta = validate_paginated(
        api.list_promotions(REVENUE_MANAGER, params={"code": "SUMMERGA"})
    )
    assert meta["total_count"] == 2
    assert sorted(ids_of(both)) == sorted([promo["id"], twin["id"]])
    assert guest["email"] == "ada@example.com"


def test_each_path_id_carries_its_own_not_found_code(api):
    """Nine unknown ids, nine dedicated codes, and no state or version leak.

    PRD 2.10 tier 5: "**Path existence**, on every endpoint carrying an id in its path
    - each path id is resolved left to right, and the first unresolvable one determines
    the code: `ERR_SAILING_NOT_FOUND`, `ERR_CABIN_CATEGORY_NOT_FOUND`,
    `ERR_SAILING_INVENTORY_NOT_FOUND`, `ERR_FARE_RULE_NOT_FOUND`,
    `ERR_PROMOTION_NOT_FOUND`, `ERR_GROUP_BLOCK_NOT_FOUND`, `ERR_GUEST_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_UPGRADE_BID_NOT_FOUND`,
    `ERR_ITINERARY_CHANGE_NOT_FOUND`. All carry HTTP 404." Because that tier sits above
    optimistic concurrency (tier 9) and own-state preconditions (tier 10), an unknown id
    can never degrade into `ERR_STALE_INVENTORY_VERSION` at 412 or a 409 state code.

    Design: Corner/errors/every_entity_has_its_own_not_found_code_on_the_path
    """
    world = fx.simple_world(api, voyage_code="NFD-2701")
    live_version = world.inventory["version"]

    validate_error(
        api.get_sailing_inventory(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_SAILING_INVENTORY_NOT_FOUND,
        404,
    )
    # The body carries a version that is valid for the *real* allotment; tier 5 still
    # answers first, so the answer is 404 rather than 412.
    validate_error(
        api.patch_sailing_inventory(
            NON_EXISTENT_UUID,
            {"oversell_allowance": 2, "expected_inventory_version": live_version},
            REVENUE_MANAGER,
        ),
        ERR_SAILING_INVENTORY_NOT_FOUND,
        404,
    )

    validate_error(
        api.get_fare_rule(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_FARE_RULE_NOT_FOUND,
        404,
    )

    validate_error(
        api.get_promotion(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_PROMOTION_NOT_FOUND,
        404,
    )
    # An action on an unknown id is not a state conflict.
    validate_error(
        api.activate_promotion(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_PROMOTION_NOT_FOUND,
        404,
    )

    validate_error(
        api.get_group_block(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_GROUP_BLOCK_NOT_FOUND,
        404,
    )

    validate_error(
        api.get_upgrade_bid(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_UPGRADE_BID_NOT_FOUND,
        404,
    )
    validate_error(
        api.counter_bid(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_UPGRADE_BID_NOT_FOUND,
        404,
    )

    validate_error(
        api.get_itinerary_change(NON_EXISTENT_UUID, REVENUE_MANAGER),
        ERR_ITINERARY_CHANGE_NOT_FOUND,
        404,
    )

    inventory = fx.read_inventory(api, world.inventory["id"])
    # The allowance the phantom PATCH asked for never reached the real row.
    assert inventory["oversell_allowance"] == 4
    assert_version_is(inventory, live_version)


def test_the_three_money_gates_fire_at_one_cent_either_side(api):
    """A deposit one cent short, an overpayment one cent long, a final one cent light.

    PRD 3.5: a `DEPOSIT` "requires `amount_cents` to be at least `deposit_due_cents`
    (otherwise `ERR_DEPOSIT_BELOW_MINIMUM`), and requires `amount_cents` not to exceed
    `balance_due_cents` (otherwise `ERR_PAYMENT_EXCEEDS_BALANCE`)". For a
    `FINAL_PAYMENT`: "An amount above the balance is refused with
    `ERR_PAYMENT_EXCEEDS_BALANCE`; an amount below it is refused with
    `ERR_FINAL_PAYMENT_SHORT`, because a partial settlement must be posted as a
    `PARTIAL` instead." And a `PARTIAL` requires "only that `amount_cents` be strictly
    less than `balance_due_cents`". PRD 2.10 tier 20 puts all three codes at HTTP 422.

    Design: Corner/errors/payment_amount_gates_reject_short_deposits_short_finals_and_overpayments
    """
    world = fx.simple_world(
        api,
        voyage_code="PAY-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    pair = fx.guest_with_booking(api, world, occupancy_adults=2)
    booking = pair.booking
    assert booking["net_ticket_cents"] == 100000
    # max(25,000 x 2, round(100,000 / 5) == 20,000).
    assert booking["deposit_due_cents"] == 50000
    assert booking["balance_due_cents"] == 100000

    # One cent under the minimum deposit.
    validate_error(
        api.post_payment(
            booking["id"], f.payment_payload("DEPOSIT", 49999), RESERVATION_AGENT
        ),
        ERR_DEPOSIT_BELOW_MINIMUM,
        422,
    )
    # Over the minimum, but one cent past the whole balance.
    validate_error(
        api.post_payment(
            booking["id"], f.payment_payload("DEPOSIT", 100001), RESERVATION_AGENT
        ),
        ERR_PAYMENT_EXCEEDS_BALANCE,
        422,
    )

    untouched = fx.read_booking(api, booking["id"])
    assert untouched["payment_status"] == "AWAITING_DEPOSIT"
    assert untouched["amount_paid_cents"] == 0
    assert untouched["balance_due_cents"] == 100000
    _, empty_meta = validate_paginated(
        api.list_payment_events(booking["id"], RESERVATION_AGENT)
    )
    # Two refusals appended nothing to an append-only ledger.
    assert empty_meta["total_count"] == 0

    deposit = validate_success(
        api.post_payment(
            booking["id"], f.payment_payload("DEPOSIT", 50000), RESERVATION_AGENT
        ),
        201,
    )
    assert deposit["kind"] == "DEPOSIT"
    assert deposit["amount_cents"] == 50000
    assert deposit["resulting_payment_status"] == "DEPOSIT_PAID"
    assert deposit["note"] is None
    deposited = fx.read_booking(api, booking["id"])
    assert deposited["payment_status"] == "DEPOSIT_PAID"
    assert deposited["amount_paid_cents"] == 50000
    assert deposited["balance_due_cents"] == 50000
    assert_instant_equals(
        deposited["final_payment_due_date"],
        "2026-10-27T17:00:00Z",
        "final_payment_due_date",
    )

    # One cent under the balance is not a final payment, it is an instalment.
    validate_error(
        api.post_payment(
            booking["id"], f.payment_payload("FINAL_PAYMENT", 49999), RESERVATION_AGENT
        ),
        ERR_FINAL_PAYMENT_SHORT,
        422,
    )
    # The very same amount is legal as a PARTIAL, and the money state does not move.
    partial = validate_success(
        api.post_payment(
            booking["id"], f.payment_payload("PARTIAL", 49999), RESERVATION_AGENT
        ),
        201,
    )
    assert partial["resulting_payment_status"] == "DEPOSIT_PAID"
    instalment = fx.read_booking(api, booking["id"])
    assert instalment["payment_status"] == "DEPOSIT_PAID"
    assert instalment["amount_paid_cents"] == 99999
    assert instalment["balance_due_cents"] == 1

    # Two cents against a one-cent balance overshoots.
    validate_error(
        api.post_payment(
            booking["id"], f.payment_payload("PARTIAL", 2), RESERVATION_AGENT
        ),
        ERR_PAYMENT_EXCEEDS_BALANCE,
        422,
    )

    final = validate_success(
        api.post_payment(
            booking["id"], f.payment_payload("FINAL_PAYMENT", 1), RESERVATION_AGENT
        ),
        201,
    )
    assert final["resulting_payment_status"] == "PAID_IN_FULL"
    closed = fx.read_booking(api, booking["id"])
    assert closed["payment_status"] == "PAID_IN_FULL"
    assert closed["amount_paid_cents"] == 100000
    assert closed["balance_due_cents"] == 0
    assert closed["delinquent_since"] is None

    ledger, meta = validate_paginated(
        api.list_payment_events(booking["id"], RESERVATION_AGENT)
    )
    # Three accepted postings, three rows, in posting order.
    assert meta["total_count"] == 3
    assert [row["kind"] for row in ledger] == ["DEPOSIT", "PARTIAL", "FINAL_PAYMENT"]
    assert [row["amount_cents"] for row in ledger] == [50000, 49999, 1]
    assert [row["resulting_payment_status"] for row in ledger] == [
        "DEPOSIT_PAID",
        "DEPOSIT_PAID",
        "PAID_IN_FULL",
    ]

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["paid_in_full_bookings_count"] == 1
    assert sailing["confirmed_bookings_count"] == 0
    # No confirmed booking, so collection health cannot be at risk.
    assert sailing["final_payment_risk_flag"] is False


def test_a_state_conflict_and_a_missing_deposit_are_different_refusals(api):
    """409 is not one code: the money state and the deposit gate answer separately.

    PRD 3.5: confirmation needs "`booking_status` ... currently `OPTION` (otherwise
    `ERR_BOOKING_NOT_IN_OPTION`); `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL`,
    so the deposit has actually landed (otherwise `ERR_DEPOSIT_NOT_PAID`)". And: "A
    payment whose `kind` has no declared transition from the booking's current
    `payment_status` - a `DEPOSIT` posted when the booking is already `PAID_IN_FULL`, or
    any payment posted after `REFUNDED` - is refused with `ERR_PAYMENT_STATE_INVALID`."
    PRD 2.10 puts `ERR_PAYMENT_STATE_INVALID` in tier 10 and the money gates in tier 20,
    so a wrong-state posting never reports an amount problem. PRD 3.5 also fixes the
    sailing-level view: "`final_payment_risk_flag` is raised when
    `confirmed_bookings_count` is above 0 **and** twice `paid_in_full_bookings_count` is
    strictly less than `confirmed_bookings_count`".

    Design: Corner/errors/confirm_and_payment_state_conflicts_are_told_apart
    """
    world = fx.simple_world(
        api,
        voyage_code="CNF-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    ada = fx.guest_with_booking(api, world, occupancy_adults=2)
    bo = fx.guest_with_booking(api, world, occupancy_adults=2)
    assert ada.booking["booking_status"] == "OPTION"
    assert ada.booking["payment_status"] == "AWAITING_DEPOSIT"

    # The status gate passes and the deposit gate fails.
    validate_error(
        api.confirm_booking(ada.booking["id"], RESERVATION_AGENT),
        ERR_DEPOSIT_NOT_PAID,
        409,
    )
    # There is no FINAL_PAYMENT edge out of AWAITING_DEPOSIT, whatever the amount.
    validate_error(
        api.post_payment(
            ada.booking["id"],
            f.payment_payload("FINAL_PAYMENT", 100000),
            RESERVATION_AGENT,
        ),
        ERR_PAYMENT_STATE_INVALID,
        409,
    )
    still_ada = fx.read_booking(api, ada.booking["id"])
    assert still_ada["booking_status"] == "OPTION"
    assert still_ada["payment_status"] == "AWAITING_DEPOSIT"
    assert_version_is(still_ada, ada.booking["version"])

    fx.pay(api, bo.booking["id"], "DEPOSIT", 50000)
    confirmed = fx.confirm(api, bo.booking["id"])
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "DEPOSIT_PAID"

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["confirmed_bookings_count"] == 1
    assert sailing["paid_in_full_bookings_count"] == 0
    # 2 x 0 is strictly below 1, so fewer than half of the confirmed have paid.
    assert sailing["final_payment_risk_flag"] is True

    # Now the status gate is the one that fails.
    validate_error(
        api.confirm_booking(bo.booking["id"], RESERVATION_AGENT),
        ERR_BOOKING_NOT_IN_OPTION,
        409,
    )
    # A second deposit has no declared transition; the shortfall is never reported.
    validate_error(
        api.post_payment(
            bo.booking["id"], f.payment_payload("DEPOSIT", 25000), RESERVATION_AGENT
        ),
        ERR_PAYMENT_STATE_INVALID,
        409,
    )

    final_bo = fx.read_booking(api, bo.booking["id"])
    assert final_bo["booking_status"] == "CONFIRMED"
    assert final_bo["amount_paid_cents"] == 50000
    assert_version_is(final_bo, confirmed["version"])
    _, meta = validate_paginated(
        api.list_payment_events(bo.booking["id"], RESERVATION_AGENT)
    )
    assert meta["total_count"] == 1


def test_the_bid_window_the_floor_and_two_wrong_statuses_each_answer(api):
    """Too early, one cent short, wrong state, then too late - four different answers.

    PRD 3.7: "bidding is only open in a window measured in days to sail: from 3 days
    before departure up to 60 days before departure, both bounds inclusive. Outside that
    window - too early or too late - every bid operation is refused with
    `ERR_BID_WINDOW_CLOSED`." The floor: "`min_acceptable_per_guest_cents` is then the
    fare gap multiplied by 0.40 (two fifths) and rounded half up, less the onboard uplift
    divided by `guest_count` and rounded half up, with the whole result floored at zero
    ... A bid below the applicable floor is refused with `ERR_BID_BELOW_FLOOR`." The
    negotiation cycle: a counter requires "the bid must currently be `SUBMITTED`
    (otherwise `ERR_BID_NOT_PENDING`)", and a re-bid requires "the bid must be in
    `COUNTERED` (otherwise `ERR_BID_NOT_COUNTERED`), the new `bid_amount_per_guest_cents`
    must be at least `countered_min_per_guest_cents` ... and the bid window must still be
    open".

    Design: Corner/errors/bid_gates_cover_the_window_the_floor_and_both_wrong_statuses
    """
    fx.set_clock(api, "2026-11-01T17:00:00Z")
    ocean_view = fx.make_category(api, f.ocean_view_category_payload())
    inside = fx.make_guarantee_category(api, upgrade_to_category_id=ocean_view["id"])
    world = fx.simple_world(
        api,
        clock="2026-11-01T17:00:00Z",
        voyage_code="BID-2701",
        final_payment_days_before=30,
        category=inside,
        physical_cabins=60,
        oversell_allowance=4,
        fare_overrides=dict(FLAT_FARE_50K, base_lower_berth_fare_cents=189995),
        open_now=False,
    )
    upper = fx.add_allotment_and_fare(
        api,
        world,
        ocean_view,
        physical_cabins=30,
        oversell_allowance=0,
        fare_overrides=dict(FLAT_FARE_50K, base_lower_berth_fare_cents=289995),
    )
    fx.open_sailing(api, world.sailing["id"])

    pair = fx.guest_with_booking(api, world, occupancy_adults=2)
    guest_headers = make_guest_headers(pair.guest["id"])
    # 2026-11-01T17:00Z to 2027-01-10T17:00Z is exactly 70 days.
    assert pair.booking["booked_days_to_sail"] == 70
    assert pair.booking["guest_count"] == 2

    # 70 days out is above the 60-day upper bound.
    validate_error(
        api.submit_upgrade_bid(
            pair.booking["id"],
            f.upgrade_bid_payload(ocean_view["id"], 40000),
            guest_headers,
        ),
        ERR_BID_WINDOW_CLOSED,
        422,
    )

    fx.set_clock(api, "2026-11-26T17:00:00Z")
    # Fare gap 289,995 - 189,995 = 100,000, so 0.40 x 100,000 = 40,000. Onboard uplift
    # is 7 nights x 2 guests x (7,000 - 6,000) = 14,000, and 14,000 / 2 = 7,000. The
    # floor is 40,000 - 7,000 = 33,000.
    validate_error(
        api.submit_upgrade_bid(
            pair.booking["id"],
            f.upgrade_bid_payload(ocean_view["id"], 32999),
            guest_headers,
        ),
        ERR_BID_BELOW_FLOOR,
        422,
    )

    bid = validate_success(
        api.submit_upgrade_bid(
            pair.booking["id"],
            f.upgrade_bid_payload(ocean_view["id"], 33000),
            guest_headers,
        ),
        201,
    )
    assert bid["status"] == "SUBMITTED"
    assert bid["min_acceptable_per_guest_cents"] == 33000
    assert bid["bid_amount_per_guest_cents"] == 33000
    assert bid["counter_rounds"] == 0
    assert bid["guest_count"] == 2
    # 2026-11-26T17:00Z to 2027-01-10T17:00Z is 45 days.
    assert bid["submitted_days_to_sail"] == 45
    assert bid["countered_min_per_guest_cents"] is None

    # A re-bid is the guest's move out of COUNTERED, not out of SUBMITTED.
    validate_error(
        api.rebid(
            bid["id"], {"bid_amount_per_guest_cents": 40000}, guest_headers
        ),
        ERR_BID_NOT_COUNTERED,
        409,
    )
    unmoved = fx.read_bid(api, bid["id"])
    assert unmoved["bid_amount_per_guest_cents"] == 33000
    assert_version_is(unmoved, bid["version"])

    countered = validate_success(api.counter_bid(bid["id"], REVENUE_MANAGER))
    assert countered["status"] == "COUNTERED"
    assert countered["counter_rounds"] == 1
    # The floor is re-derived at the same instant, so it lands on the same figure.
    assert countered["countered_min_per_guest_cents"] == 33000
    assert countered["version"] == bid["version"] + 1

    # Awarding is only available from SUBMITTED.
    validate_error(
        api.accept_bid(bid["id"], REVENUE_MANAGER),
        ERR_BID_NOT_PENDING,
        409,
    )

    fx.set_clock(api, "2027-01-08T17:00:00Z")
    # 2 days out is below the 3-day lower bound, so the cycle can no longer be closed.
    validate_error(
        api.rebid(
            bid["id"], {"bid_amount_per_guest_cents": 40000}, guest_headers
        ),
        ERR_BID_WINDOW_CLOSED,
        422,
    )

    stranded = fx.read_bid(api, bid["id"])
    # Only the sweep expires a bid; a refused re-bid leaves it mid-negotiation.
    assert stranded["status"] == "COUNTERED"
    assert stranded["counter_rounds"] == 1
    assert stranded["bid_amount_per_guest_cents"] == 33000
    assert stranded["award_amount_cents"] is None
    assert stranded["decline_reason"] is None

    booking = fx.read_booking(api, pair.booking["id"])
    assert booking["assigned_cabin_category_id"] == inside["id"]
    assert booking["upgrade_charge_cents"] == 0
    target_inventory = fx.read_inventory(api, upper.inventory["id"])
    assert target_inventory["booked_cabins"] == 0
    assert target_inventory["available_cabins"] == 30

    bids, meta = validate_paginated(
        api.list_upgrade_bids(REVENUE_MANAGER, params={"booking_id": pair.booking["id"]})
    )
    assert meta["total_count"] == 1
    assert ids_of(bids) == [bid["id"]]


def test_a_signed_block_is_closed_an_extended_one_is_capped_and_a_full_one_is_exhausted(api):
    """Three group refusals from three different tiers, on two blocks side by side.

    PRD 3.3: "Signing also freezes the held count: review transitions are not available
    from `DEFINITE`, and attempting either a review or a review extension on a block in
    `DEFINITE` or `RELEASED` is refused with `ERR_GROUP_BLOCK_CLOSED`." On extensions:
    "the block's `review_extension_count` must currently be below 2 (otherwise
    `ERR_MAX_REVIEW_EXTENSIONS_EXCEEDED`) - so at most two extensions are ever possible
    per block. The extension writes `review_date` from `new_review_date`, raises
    `review_extension_count` by 1, increments the block's `version` by 1, and leaves
    `cabins_held` and the allotment's `group_held_cabins` entirely unchanged." On the
    fence: "A group booking - one carrying `group_block_id` - draws on its own fence
    instead: the block's `cabins_held` minus its `picked_up_cabins` must be at least 1,
    otherwise the sale is refused with `ERR_GROUP_BLOCK_EXHAUSTED`, and a group booking
    is **never** waitlisted regardless of `allow_waitlist`."

    Design: Corner/errors/group_block_gates_cover_closure_extension_limit_and_exhaustion
    """
    world = fx.simple_world(
        api,
        voyage_code="GBK-2701",
        nights=4,
        total_lower_berths=40,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
    )
    alpha = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        agency_name="Alpha Tours",
        cabins_held=2,
        review_date="2026-08-16T00:00:00Z",
        release_policy="ATTRITION_50",
    )
    signed = fx.sign_definite(
        api, alpha["id"], contract_reference="CTR-ALPHA-1", headers=GROUP_SALES_AGENT_2
    )
    assert signed["status"] == "DEFINITE"
    beta = fx.make_group_block(
        api,
        world.sailing["id"],
        world.category["id"],
        headers=GROUP_SALES_AGENT,
        agency_name="Beta Travel",
        cabins_held=2,
        review_date="2026-08-10T00:00:00Z",
        release_policy="FULL_RELEASE",
    )

    # A contracted block has left the review cycle entirely.
    validate_error(
        api.review_group_block(alpha["id"], GROUP_SALES_AGENT),
        ERR_GROUP_BLOCK_CLOSED,
        409,
    )
    validate_error(
        api.extend_review(
            alpha["id"], {"new_review_date": "2026-09-01T00:00:00Z"}, GROUP_SALES_AGENT
        ),
        ERR_GROUP_BLOCK_CLOSED,
        409,
    )
    closed = fx.read_block(api, alpha["id"])
    assert closed["cabins_held"] == 2
    assert_version_is(closed, signed["version"])

    first = validate_success(
        api.extend_review(
            beta["id"], {"new_review_date": "2026-08-20T00:00:00Z"}, GROUP_SALES_AGENT
        )
    )
    assert first["status"] == "TENTATIVE"
    assert first["review_extension_count"] == 1
    assert_instant_equals(first["review_date"], "2026-08-20T00:00:00Z", "review_date")
    assert first["cabins_held"] == 2

    second = validate_success(
        api.extend_review(
            beta["id"], {"new_review_date": "2026-08-30T00:00:00Z"}, GROUP_SALES_AGENT
        )
    )
    assert second["review_extension_count"] == 2
    assert_instant_equals(second["review_date"], "2026-08-30T00:00:00Z", "review_date")
    assert second["version"] == first["version"] + 1

    # The third extension is one past the cap.
    validate_error(
        api.extend_review(
            beta["id"], {"new_review_date": "2026-09-10T00:00:00Z"}, GROUP_SALES_AGENT
        ),
        ERR_MAX_REVIEW_EXTENSIONS_EXCEEDED,
        422,
    )
    capped = fx.read_block(api, beta["id"])
    assert capped["review_extension_count"] == 2
    assert_instant_equals(capped["review_date"], "2026-08-30T00:00:00Z", "review_date")
    assert_version_is(capped, second["version"])

    ada = fx.make_guest(api)
    bo = fx.make_guest(api)
    cy = fx.make_guest(api)
    for guest in (ada, bo):
        booking = validate_success(
            api.create_booking(
                f.booking_payload(
                    world.sailing["id"],
                    world.category["id"],
                    guest["id"],
                    occupancy_adults=2,
                    group_block_id=alpha["id"],
                ),
                RESERVATION_AGENT,
            ),
            201,
        )
        assert booking["booking_status"] == "OPTION"
        assert booking["group_block_id"] == alpha["id"]

    picked = fx.read_block(api, alpha["id"])
    assert picked["picked_up_cabins"] == 2
    # Pickups do not shrink the contracted hold; they only consume it.
    assert picked["cabins_held"] == 2

    # The fence is empty even though the allotment itself still has room, and
    # allow_waitlist cannot rescue a group sale.
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                cy["id"],
                occupancy_adults=2,
                group_block_id=alpha["id"],
                allow_waitlist=True,
            ),
            RESERVATION_AGENT,
        ),
        ERR_GROUP_BLOCK_EXHAUSTED,
        422,
    )

    inventory = fx.read_inventory(api, world.inventory["id"])
    assert inventory["booked_cabins"] == 2
    # Alpha's fence emptied as its cabins became bookings; Beta still holds two.
    assert inventory["group_held_cabins"] == 2
    assert inventory["waitlisted_bookings_count"] == 0
    assert inventory["available_cabins"] == 6
    assert_capacity_identity(inventory)

    sailing = fx.read_sailing(api, world.sailing["id"])
    assert sailing["lower_berths_sold"] == 4
    assert float(sailing["occupancy_pct"]) == 10.0
    assert_two_decimal_pct(sailing["occupancy_pct"], "occupancy_pct")
    assert sailing["available_lower_berth_days_gross"] == 160
    # Beta's 2 cabins fence 4 lower berths, so 36 berths x 4 nights remain net.
    assert sailing["available_lower_berth_days_net"] == 144


def test_a_guarantee_can_only_be_named_into_a_real_cabin_and_only_inside_its_window(api):
    """The same code refuses two opposite mistakes, and a campaign wakes on its first day.

    PRD 3.7: "The booking must have been sold into a guarantee category and the named
    target must be a non-guarantee category on the same sailing; a booking whose
    `cabin_category_id` is not a guarantee category, or a target that is itself a
    guarantee category or belongs to another sailing, is refused with
    `ERR_NOT_GUARANTEE_BOOKING`." On success: "the guarantee fare is honoured -
    `net_ticket_cents` does not change - while the cabin count moves between allotments:
    the guarantee allotment's `booked_cabins` falls by 1, the named allotment's
    `booked_cabins` rises by 1, and `available_cabins` is recomputed on both. The
    booking's `projected_onboard_gross_cents` and `projected_onboard_net_cents` are
    recomputed against the named category's spend indices". PRD 3.2 on activation: it
    "requires the current instant to lie inside the inclusive `starts_on`-to-`ends_on`
    interval (otherwise `ERR_PROMO_WINDOW_NOT_CURRENT`)".

    Design: Corner/errors/guarantee_assignment_and_promotion_window_gates_are_reachable
    """
    fx.set_clock(api)
    inside_a = fx.make_guarantee_category(api)
    inside_b = fx.make_category(
        api,
        f.cabin_category_payload(
            code="IB",
            tier_rank=2,
            is_guarantee=True,
            onboard_spend_lower_per_night_cents=9500,
            onboard_spend_upper_per_night_cents=6200,
        ),
    )
    ocean_view = fx.make_category(api, f.ocean_view_category_payload(tier_rank=3))
    balcony = fx.make_category(api, f.balcony_category_payload(tier_rank=4))

    sailing = fx.make_sailing(api, voyage_code="GTY-2701")
    inv_ia = fx.make_inventory(
        api, sailing["id"], inside_a["id"], physical_cabins=60, oversell_allowance=4
    )
    fx.make_inventory(
        api, sailing["id"], inside_b["id"], physical_cabins=10, oversell_allowance=1
    )
    inv_ov = fx.make_inventory(
        api, sailing["id"], ocean_view["id"], physical_cabins=30, oversell_allowance=0
    )
    fx.make_inventory(
        api, sailing["id"], balcony["id"], physical_cabins=20, oversell_allowance=0
    )
    fx.make_fare_rule(
        api,
        sailing["id"],
        inside_a["id"],
        **dict(FLAT_FARE_50K, base_lower_berth_fare_cents=189995),
    )
    fx.make_fare_rule(
        api,
        sailing["id"],
        ocean_view["id"],
        **dict(FLAT_FARE_50K, base_lower_berth_fare_cents=289995),
    )
    opened = fx.open_sailing(api, sailing["id"])
    promo = fx.make_promotion(
        api,
        sailing["id"],
        opened["version"],
        code="FALLSALE",
        starts_on="2026-09-01T00:00:00Z",
        ends_on="2026-09-10T00:00:00Z",
        max_redemptions=5,
    )
    assert promo["status"] == "SCHEDULED"

    nell = fx.make_guest(api)
    ada = fx.make_guest(api)
    named_booking = fx.make_booking(
        api, sailing["id"], ocean_view["id"], nell["id"], occupancy_adults=2
    )
    guarantee_booking = fx.make_booking(
        api, sailing["id"], inside_a["id"], ada["id"], occupancy_adults=2
    )
    assert named_booking["net_ticket_cents"] == 579990
    assert guarantee_booking["net_ticket_cents"] == 379990
    # 7 nights x 2 adults x 9,000 while the cabin is still only a promise.
    assert guarantee_booking["projected_onboard_gross_cents"] == 126000

    # The booking was sold into a named category, so there is nothing to assign.
    validate_error(
        api.assign_guarantee(
            named_booking["id"],
            {"assigned_cabin_category_id": balcony["id"]},
            RESERVATION_AGENT,
        ),
        ERR_NOT_GUARANTEE_BOOKING,
        422,
    )
    # And a guarantee may not be resolved into another guarantee.
    validate_error(
        api.assign_guarantee(
            guarantee_booking["id"],
            {"assigned_cabin_category_id": inside_b["id"]},
            RESERVATION_AGENT,
        ),
        ERR_NOT_GUARANTEE_BOOKING,
        422,
    )

    assigned = validate_success(
        api.assign_guarantee(
            guarantee_booking["id"],
            {"assigned_cabin_category_id": ocean_view["id"]},
            RESERVATION_AGENT,
        )
    )
    assert assigned["assigned_cabin_category_id"] == ocean_view["id"]
    # The category the guest bought is untouched, and so is the fare.
    assert assigned["cabin_category_id"] == inside_a["id"]
    assert assigned["net_ticket_cents"] == 379990
    # 7 nights x 2 adults x 11,000 once the ocean-view indices apply.
    assert assigned["projected_onboard_gross_cents"] == 154000
    assert assigned["projected_onboard_net_cents"] == 154000
    assert assigned["version"] == guarantee_booking["version"] + 1

    guarantee_allotment = fx.read_inventory(api, inv_ia["id"])
    assert guarantee_allotment["booked_cabins"] == 0
    # 60 physical plus 4 effective oversell cabins, all free again.
    assert guarantee_allotment["available_cabins"] == 64
    assert_capacity_identity(guarantee_allotment)
    named_allotment = fx.read_inventory(api, inv_ov["id"])
    assert named_allotment["booked_cabins"] == 2
    assert named_allotment["available_cabins"] == 28
    assert_capacity_identity(named_allotment)

    refreshed = fx.read_sailing(api, sailing["id"])
    assert refreshed["projected_onboard_revenue_cents"] == 308000
    assert refreshed["gross_ticket_revenue_cents"] == 959980
    assert refreshed["available_lower_berth_days_gross"] == 1400
    assert refreshed["available_lower_berth_days_net"] == 1400
    # (959,980 + 308,000) over 1,400 is 905.7, so 906.
    assert refreshed["ralbd_gross_cents"] == 906
    assert refreshed["ralbd_net_cents"] == 906
    assert float(refreshed["occupancy_pct"]) == 2.0
    assert refreshed["inventory_posture"] == "OPEN"

    # 2026-08-01 is a month before the campaign opens.
    validate_error(
        api.activate_promotion(promo["id"], REVENUE_MANAGER),
        ERR_PROMO_WINDOW_NOT_CURRENT,
        422,
    )
    dormant = fx.read_promotion(api, promo["id"])
    assert dormant["status"] == "SCHEDULED"
    assert_version_is(dormant, promo["version"])

    fx.set_clock(api, "2026-09-01T00:00:00Z")
    # starts_on is inclusive, so the very first instant of the interval is enough.
    live = fx.activate_promotion(api, promo["id"])
    assert live["status"] == "ACTIVE"
    assert live["version"] == promo["version"] + 1
