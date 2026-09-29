"""Patrons, philanthropy, and the four-step subscription package price."""

from test_helpers import (
    BOX_OFFICE,
    ApiErrorId,
    build_renewal_window_world,
    create_package,
    create_patron,
    inventory_for,
    read_concert,
    read_patron,
    read_subscription,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Donor standing and priority score
# --------------------------------------------------------------------------
def test_donor_level_threshold_is_inclusive_at_the_friend_boundary(api):
    """PRD 3.4: "Because the comparisons are inclusive, a total of exactly 250,000
    cents is a `FRIEND` while 249,999 cents is not."
    PRD 3.4: "It does **not** touch `lifetime_cash_in_cents`,
    `credit_balance_cents`, or any ticket or subscription figure — §2.10 keeps
    philanthropy and commerce in separate books."
    PRD 3.4: "The score is then the patron's `consecutive_renewal_years` multiplied
    by 100, plus the points their `donor_level` carries — 0 for `NONE`, 50 for
    `FRIEND`, 150 for `SUSTAINER`, 400 for `BENEFACTOR` and 900 for `LAUREATE` —
    plus seniority in years multiplied by 10."

    Design: Corner/calculations/donor_level_threshold_is_inclusive_at_250000
    """
    set_clock("2026-09-01T00:00:00Z", BOX_OFFICE)
    patron = create_patron(full_name="Noel Vance", email="noel-donor@patron.test")

    below = validate_success(api.record_donation(patron["id"], 249999, BOX_OFFICE))
    assert below["donor_level"] == "NONE"
    assert below["renewal_priority_score"] == 0, "no seniority and no donor points yet"

    at_threshold = validate_success(api.record_donation(patron["id"], 1, BOX_OFFICE))
    assert at_threshold["donor_level"] == "FRIEND"
    assert at_threshold["renewal_priority_score"] == 50

    final = read_patron(patron["id"])
    assert final["lifetime_donation_cents"] == 250000
    assert final["lifetime_cash_in_cents"] == 0, "gifts never touch the cash ledger"
    assert final["credit_balance_cents"] == 0


def test_renewal_priority_score_sums_renewals_donor_points_and_seniority(api):
    """PRD 3.4: "Seniority in years is zero when `subscriber_since_year` is null;
    otherwise it is the calendar year of the logical clock less
    `subscriber_since_year`, and never less than zero — a patron whose recorded
    first year lies in the future scores zero seniority rather than a negative
    figure."
    PRD 3.4: "The score is then the patron's `consecutive_renewal_years` multiplied
    by 100, plus the points their `donor_level` carries — 0 for `NONE`, 50 for
    `FRIEND`, 150 for `SUSTAINER`, 400 for `BENEFACTOR` and 900 for `LAUREATE` —
    plus seniority in years multiplied by 10."

    Design: Corner/calculations/renewal_priority_score_sums_its_three_components
    """
    set_clock("2026-09-01T00:00:00Z", BOX_OFFICE)
    patron = create_patron(full_name="Iris Lund", email="iris-score@patron.test",
                           subscriber_since_year=2016)

    scored = validate_success(api.record_donation(patron["id"], 1000000, BOX_OFFICE))

    assert scored["donor_level"] == "SUSTAINER"
    assert scored["renewal_priority_score"] == 250, (
        "150 SUSTAINER points plus 10 clock-years of seniority at 10 points each"
    )
    assert scored["consecutive_renewal_years"] == 0
    assert scored["lifetime_donation_cents"] == 1000000


# --------------------------------------------------------------------------
# Package construction gates
# --------------------------------------------------------------------------
def test_donor_seating_benefit_is_reported_before_seat_availability(api):
    """PRD 2.6: "Every write request is evaluated against a fixed ladder of checks,
    and the ladder is strictly ordered: the first check that fails determines the
    response, and no later check is evaluated."
    PRD 2.6: "Availability is the **last** thing checked, so a request that is both
    unaffordable in seats and defective in some earlier respect always reports the
    earlier defect."
    PRD 3.5: "The **donor seating benefit** reserves the best rooms for the
    orchestra's principal supporters: if the chosen section's
    `donor_priority_rank` is 1 or 2, the patron's `donor_level` must be
    `BENEFACTOR` or `LAUREATE`, and a lesser standing is refused with
    `ERR_DONOR_BENEFIT_REQUIRED`."

    Design: Corner/validations/donor_benefit_check_beats_seat_capacity_check
    """
    world = build_renewal_window_world(
        section_specs=[{"name": "ORCHESTRA", "capacity": 2, "price_multiplier_bp": 15000,
                        "donor_priority_rank": 1, "min_renewal_priority_score": 0}]
    )
    patron = create_patron(full_name="Noel Vance", email="noel-benefit@patron.test")

    response = api.create_subscription(
        {
            "patron_id": patron["id"],
            "season_id": world.season["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 3,
            "concert_ids": world.concert_ids,
        },
        BOX_OFFICE,
    )
    error = validate_error(response, ApiErrorId.ERR_DONOR_BENEFIT_REQUIRED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_SEATS.value, (
        "3 seats in a 2-seat section also breaks availability, but that rung is last"
    )

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["held_count"] == 0

    _, meta = validate_paginated(
        api.list_subscriptions(BOX_OFFICE, params={"patron_id": patron["id"]})
    )
    assert meta["total_count"] == 0


def test_package_containing_a_draft_concert_is_refused(api):
    """PRD 3.5: "**Package membership** requires that `concert_ids` be non-empty,
    contain no duplicate entries, and consist entirely of concerts belonging to the
    same `season_id` as the package whose `programming_status` is `PROGRAMMED` or
    `LOCKED`; a violation of any of those is `ERR_PACKAGE_CONCERT_MISMATCH`."

    Design: Corner/validations/package_containing_draft_concert_returns_concert_mismatch
    """
    world = build_renewal_window_world(
        section_specs=[{"_balcony": True}], concert_count=2, program_indexes=[0]
    )
    programmed, still_draft = world.concerts
    patron = create_patron(full_name="Vera Kimmel", email="vera-mismatch@patron.test")

    response = api.create_subscription(
        {
            "patron_id": patron["id"],
            "season_id": world.season["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 1,
            "concert_ids": [programmed["id"], still_draft["id"]],
        },
        BOX_OFFICE,
    )
    validate_error(response, ApiErrorId.ERR_PACKAGE_CONCERT_MISMATCH.value, 422)

    for concert in (programmed, still_draft):
        element = inventory_for(read_concert(concert["id"]), world.section["id"])
        assert element["held_count"] == 0, "a refused package holds no seats anywhere"


# --------------------------------------------------------------------------
# Package pricing
# --------------------------------------------------------------------------
def test_package_lines_are_rounded_before_they_are_summed(api):
    """PRD 3.5: "Step one fixes the per-line unit price,
    `locked_unit_price_cents`: for a `NEW` package it is the season's
    `base_ticket_price_cents` multiplied by the section's `price_multiplier_bp`,
    divided by 10,000 and rounded half up to a whole cent."
    PRD 3.5: "Step two sums the **already-rounded** lines: taking the concerts in
    ascending order of `performance_start_utc` with ties broken by ascending
    concert `created_at`, each concert contributes a line total of
    `locked_unit_price_cents` multiplied by `seat_count`, and those line totals are
    added to produce a subtotal. Rounding happens per concert line, not once over a
    raw sum, and the difference is real money."

    Design: Difficulty/combinatorial_formula/package_price_per_line_rounding_order
    """
    world = build_renewal_window_world(
        season_overrides={"base_ticket_price_cents": 6333, "loyalty_discount_bp": 500},
        section_specs=[{"_balcony": True}],
        concert_count=3,
    )
    patron = create_patron(full_name="Vera Kimmel", email="vera-round@patron.test")

    package = create_package(
        patron["id"], world.season["id"], world.section["id"], world.concert_ids
    )

    assert package["locked_unit_price_cents"] == 5066, (
        "6333 times 8000bp is 5066.4, which rounds half up to 5066"
    )
    assert package["price_cents"] == 14438, (
        "three rounded lines of 5066 sum to 15198, less the 500bp three-concert tier"
    )


def test_package_price_is_not_the_sum_then_round_figure(api):
    """PRD 2.5: "This matters because the system deliberately rounds *per line*
    rather than once over a raw total in subscription pricing, and rounds after
    each of several sequential multiplications in single-ticket pricing."
    PRD 3.5: "Step three applies the **package discount**, whose tier is keyed on
    how many concerts the package contains: a package of 8 or more concerts earns
    1500 basis points off, one of 5 to 7 concerts earns 1000 basis points, one of 3
    or 4 concerts earns 500 basis points, and one of fewer than 3 concerts earns
    nothing."

    Design: Difficulty/combinatorial_formula/package_price_per_line_rounding_order
    """
    world = build_renewal_window_world(
        season_overrides={"base_ticket_price_cents": 6333, "loyalty_discount_bp": 500},
        section_specs=[{"_balcony": True}],
        concert_count=3,
    )
    patron = create_patron(full_name="Vera Kimmel", email="vera-round2@patron.test")

    package = create_package(
        patron["id"], world.season["id"], world.section["id"], world.concert_ids
    )

    assert package["price_cents"] != 14439, (
        "14439 is the sum-then-round result and is one cent too high"
    )
    assert package["price_cents"] == 14438
    assert package["status"] == "PENDING_PAYMENT"
    for concert_id in world.concert_ids:
        element = inventory_for(read_concert(concert_id), world.section["id"])
        assert element["held_count"] == 1


def test_five_concert_package_selects_the_thousand_basis_point_tier(api):
    """PRD 3.5: "Step three applies the **package discount**, whose tier is keyed on
    how many concerts the package contains: a package of 8 or more concerts earns
    1500 basis points off, one of 5 to 7 concerts earns 1000 basis points, one of 3
    or 4 concerts earns 500 basis points, and one of fewer than 3 concerts earns
    nothing."
    PRD 3.5: "A package also publishes `fulfilled_concert_count`, the number of its
    `concert_ids` whose concert has a `performance_status` other than `CANCELLED`."

    Design: Corner/calculations/package_discount_tier_at_five_concerts
    """
    world = build_renewal_window_world(
        section_specs=[{"_balcony": True}], concert_count=5
    )
    patron = create_patron(full_name="Vera Kimmel", email="vera-tier@patron.test")

    package = create_package(
        patron["id"], world.season["id"], world.section["id"], world.concert_ids
    )

    assert package["locked_unit_price_cents"] == 4800
    assert package["price_cents"] == 21600, "24000 less the 1000bp five-concert tier"
    assert package["fulfilled_concert_count"] == 5

    element = inventory_for(read_concert(world.concert_ids[-1]), world.section["id"])
    assert element["held_count"] == 1


def test_subscription_creation_returns_the_computed_price_immediately(api):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD 3.5: "Step one fixes the per-line unit price,
    `locked_unit_price_cents`: for a `NEW` package it is the season's
    `base_ticket_price_cents` multiplied by the section's `price_multiplier_bp`,
    divided by 10,000 and rounded half up to a whole cent."
    PRD 2.9: "`available_count` is the element's `capacity` less its `held_count`
    less its `sold_count`."

    Design: Corner/consistency_model/subscription_create_response_already_carries_computed_price
    """
    world = build_renewal_window_world(
        section_specs=[{"_balcony": True}], concert_count=3
    )
    patron = create_patron(full_name="Iris Lund", email="iris-immediate@patron.test",
                           subscriber_since_year=2018)

    response = api.create_subscription(
        {
            "patron_id": patron["id"],
            "season_id": world.season["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 1,
            "concert_ids": world.concert_ids,
        },
        BOX_OFFICE,
    )
    package = validate_success(response, 201)

    assert package["price_cents"] == 13680, "returned in the same 201 body"
    assert package["locked_unit_price_cents"] == 4800
    assert package["status"] == "PENDING_PAYMENT"

    middle = read_concert(world.concert_ids[1])
    element = inventory_for(middle, world.section["id"])
    assert element["held_count"] == 1
    assert element["available_count"] == 49

    assert read_patron(patron["id"])["lifetime_cash_in_cents"] == 0, (
        "nothing is charged until the package is paid"
    )


def test_paying_an_active_package_twice_is_refused(api):
    """PRD 3.5: "Paying a package moves it from `PENDING_PAYMENT` to `ACTIVE`; a
    package in any other status is refused with `ERR_SUBSCRIPTION_NOT_PENDING`."
    PRD 3.5: "The patron's `consecutive_renewal_years` is then set — to exactly 1
    when the package's `package_type` is `NEW`, or incremented by 1 when it is
    `RENEWAL` — and their `renewal_priority_score` is recomputed and persisted from
    the new figure."

    Design: Corner/state_machines/pay_subscription_twice_returns_not_pending
    """
    world = build_renewal_window_world(section_specs=[{"_balcony": True}])
    patron = create_patron(full_name="Iris Lund", email="iris-paytwice@patron.test",
                           subscriber_since_year=2018)
    package = create_package(
        patron["id"], world.season["id"], world.section["id"], world.concert_ids
    )
    validate_success(api.pay_subscription(package["id"], BOX_OFFICE))

    response = api.pay_subscription(package["id"], BOX_OFFICE)
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_NOT_PENDING.value, 409)

    settled = read_subscription(package["id"])
    assert settled["status"] == "ACTIVE"
    assert settled["price_cents"] == 4800

    buyer = read_patron(patron["id"])
    assert buyer["lifetime_cash_in_cents"] == 4800, "the refused call must not double-charge"
    assert buyer["consecutive_renewal_years"] == 1

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["sold_count"] == 1
    assert element["held_count"] == 0
