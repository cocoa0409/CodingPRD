"""
Three money compositions in which several pinned factors have to be combined in
the documented order: the five-step per-cover price with its nested clamp and
its scarcity ladder, the service charge rounded once per charge line and then
summed, and the rebooking fee whose band is read off the forfeiture the ladder
produced.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import make_guest_headers, make_restaurant_headers

# The instant every scenario below pins the logical clock to before anything
# else happens: far inside every hold, cutoff and cancellation window.
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# 2026-09-12 is a Saturday, "the strongest day at 12500" basis points.
SEATING_START_HIGH = "2026-09-12T22:00:00Z"
SEATING_END_HIGH = "2026-09-13T02:00:00Z"
SEATING_START_PEAK = "2026-09-12T17:00:00Z"
SEATING_END_PEAK = "2026-09-12T20:00:00Z"

# "Subtract the logical clock from the service's `seating_start_utc` and divide
# by 3600 seconds": exactly 48.0 hours before the Saturday dinner seating.
CANCEL_AT_48H = "2026-09-10T22:00:00Z"


def _pricing_world(api):
    """One restaurant, two same-Saturday services differing only in demand
    tier, one 20-seat class on each, and four holds on the HIGH class that walk
    that class up its own sell-through ladder.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Menu Pricing",
        course_count=8,
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        release_discount_bp=1500,
        min_party_size=1,
        max_party_size=8,
    )
    service_high = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START_HIGH,
        seating_end_utc=SEATING_END_HIGH,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
    )
    service_peak = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="LUNCH",
        seating_start_utc=SEATING_START_PEAK,
        seating_end_utc=SEATING_END_PEAK,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="PEAK",
    )
    tc_high = FX.create_ticket_class(
        api, restaurant["id"], service_high["id"], package["id"], seats_allocated=20
    )
    tc_peak = FX.create_ticket_class(
        api, restaurant["id"], service_peak["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service_high["id"])
    FX.publish_service(api, restaurant["id"], service_peak["id"])

    guests = [FX.create_guest(api, display_name=f"Pricer {n}") for n in range(1, 5)]
    # Party sizes 8, 7, 1, 1 take the class's committed share to 40, 75, 80 and
    # 85 percent of its allocation in turn.
    holds = [
        FX.hold_seats(
            api,
            tc_high["id"],
            guest["id"],
            party_size=party_size,
            primary_guest_name=guest["display_name"],
        )
        for guest, party_size in zip(guests, (8, 7, 1, 1))
    ]
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "package": package,
        "service_high": service_high,
        "service_peak": service_peak,
        "tc_high": tc_high,
        "tc_peak": tc_peak,
        "guests": guests,
        "holds": holds,
    }


class TestPerCoverPriceComposition:
    """Four pinned factors compose into one per-cover figure."""

    def test_each_hold_locks_the_price_its_own_scarcity_step_dictated(self, api):
        """Four successive holds lock 18000, 18000, 19440 and 20700 cents.

        "Where that figure has reached 8000 basis points — eighty percent of the
        allocation committed, holds included — the scarcity step is 1500 basis
        points. Where it has not reached 8000 but has reached 5000, the step is
        800 basis points. Below 5000 there is no step at all."

        Design: Difficulty/combinatorial_formula/price_quote_nested_clamp_and_scarcity_step_ladder
        """
        world = _pricing_world(api)
        expected = [18000, 18000, 19440, 20700]
        for hold, guest, want in zip(world["holds"], world["guests"], expected):
            reservation = FX.read_reservation(
                api, hold["id"], make_guest_headers(guest["id"])
            )
            assert reservation["price_locked_per_cover_cents"] == want, (
                f"the hold of party {reservation['party_size']} should have locked "
                f"{want} cents per cover, got "
                f"{reservation['price_locked_per_cover_cents']}"
            )
            # None of these seats came out of the released pool.
            assert reservation["is_release_priced"] is False

        # Steps one to three are the same 18000-cent list price for all four;
        # only the scarcity step of step four moved.
        assert C.list_price_per_cover(12000, "SAT", "HIGH", 0) == 18000
        assert C.list_price_per_cover(12000, "SAT", "HIGH", 7500) == 19440
        assert C.list_price_per_cover(12000, "SAT", "HIGH", 8000) == 20700

    def test_the_sell_through_a_hold_reads_excludes_its_own_seats(self, api):
        """The party of 7 still pays 18000 although its own seats cross 5000 bp.

        "Note that a mere hold moves it: a `PENDING` reservation counts against
        sell-through exactly as a confirmed one does, so an unpaid hold can
        already push the class into a higher scarcity price step."

        Design: Difficulty/combinatorial_formula/price_quote_nested_clamp_and_scarcity_step_ladder
        """
        world = _pricing_world(api)
        second_guest = world["guests"][1]
        second = FX.read_reservation(
            api, world["holds"][1]["id"], make_guest_headers(second_guest["id"])
        )
        # 8 seats were already held, so the class stood at 4000 basis points;
        # adding this party of 7 takes it to 7500, but the quote was struck
        # against 4000 and so carries no step at all.
        assert second["price_locked_per_cover_cents"] == 18000
        assert second["ticket_subtotal_cents"] == 126000

        third = FX.read_reservation(
            api, world["holds"][2]["id"], make_guest_headers(world["guests"][2]["id"])
        )
        assert third["price_locked_per_cover_cents"] == 19440

        ticket_class = FX.read_ticket_class(
            api, world["tc_high"]["id"], world["manager"]
        )
        A.assert_seat_pool(
            ticket_class, sold=0, held=17, released=0, available=3, status="OPEN"
        )
        assert ticket_class["sell_through_bp"] == 8500

    def test_price_quote_refreshes_both_prices_without_moving_a_seat(self, api):
        """The quote reports 20700 at list and 17595 off the released pool.

        "A quote request re-derives `sell_through_bp`,
        `list_price_per_cover_cents` and `release_price_per_cover_cents` from the
        current seat pool and returns the refreshed class; it persists no other
        change and moves no seat."

        Design: Difficulty/combinatorial_formula/price_quote_nested_clamp_and_scarcity_step_ladder
        """
        world = _pricing_world(api)
        guest_headers = make_guest_headers(world["guests"][0]["id"])
        before = FX.read_ticket_class(api, world["tc_high"]["id"], world["manager"])

        response = api.price_quote(world["tc_high"]["id"], guest_headers)
        validate_success(response, 200)
        quoted = get_success_data(response)

        assert quoted["sell_through_bp"] == 8500
        assert quoted["list_price_per_cover_cents"] == 20700
        # "The discount therefore comes off the scarcity-adjusted figure, never
        # off the pre-scarcity list price": 20700 less 1500 bp, not 18000 less
        # 1500 bp.
        assert quoted["release_price_per_cover_cents"] == 17595
        assert C.release_price_per_cover(20700, 1500) == 17595

        after = FX.read_ticket_class(api, world["tc_high"]["id"], world["manager"])
        A.assert_seat_pool(after, sold=0, held=17, released=0, available=3)
        assert after["seats_available"] == before["seats_available"]
        assert after["seats_held"] == before["seats_held"]

    def test_the_peak_saturday_cap_binds_on_the_combined_basis_points(self, api):
        """A Saturday PEAK cover quotes 21600 cents, not 21750.

        "The combined factor is first raised to the floor if it fell below it,
        and the result of that is then lowered to the cap if it rose above it.
        The ordering is not decorative: a configuration that crosses both bounds
        resolves to the cap, because the floor has already been applied by the
        time the cap is tested."

        Design: Difficulty/combinatorial_formula/price_quote_nested_clamp_and_scarcity_step_ladder
        """
        world = _pricing_world(api)
        guest_headers = make_guest_headers(world["guests"][0]["id"])

        response = api.price_quote(world["tc_peak"]["id"], guest_headers)
        validate_success(response, 200)
        quoted = get_success_data(response)

        # 12500 times 14500 divided by 10000 is 18125 basis points, which the
        # 18000 cap lowers before the base price is ever multiplied.
        assert C.combined_factor_bp("SAT", "PEAK") == 18125
        assert C.clamp_factor_bp(18125) == C.PRICE_CAP_BP
        assert quoted["list_price_per_cover_cents"] == 21600
        assert quoted["list_price_per_cover_cents"] != 21750
        assert quoted["release_price_per_cover_cents"] == 18360

        # This class was left untouched, so no scarcity step is in play here.
        assert quoted["sell_through_bp"] == 0
        A.assert_seat_pool(
            quoted, sold=0, held=0, released=0, available=20, status="OPEN"
        )


def _rounding_world(api):
    """A CONFIRMED party of two on a Saturday HIGH service, plus two add-ons
    whose line subtotals both land on an exact half cent of service charge.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=725)
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Tasting Menu Rounding",
        course_count=8,
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        min_party_size=1,
        max_party_size=8,
    )
    # "the primary sort key for the pinned per-line charge accumulation order":
    # Caviar Supplement sorts ahead of Wine Pairing.
    caviar = FX.create_add_on(
        api,
        restaurant["id"],
        name="Caviar Supplement",
        price_cents=4500,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=120,
    )
    wine = FX.create_add_on(
        api,
        restaurant["id"],
        name="Wine Pairing",
        price_cents=8500,
        prep_minutes_per_unit=0,
        max_qty_per_cover=2,
        order_cutoff_minutes=120,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START_HIGH,
        seating_end_utc=SEATING_END_HIGH,
        turn_time_minutes=150,
        seats_capacity=20,
        demand_tier="HIGH",
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])
    guest = FX.create_guest(api, display_name="Round Guest")
    reservation = FX.confirmed_reservation(
        api, ticket_class["id"], guest["id"], party_size=2
    )
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "caviar": caviar,
        "wine": wine,
        "service": service,
        "ticket_class": ticket_class,
        "guest": guest,
        "guest_headers": make_guest_headers(guest["id"]),
        "reservation": reservation,
    }


def _append_both_lines(api, world):
    """Order two units of each add-on, in the pinned name order."""
    caviar_line = FX.append_add_on_line(
        api,
        world["reservation"]["id"],
        world["guest"]["id"],
        world["caviar"]["id"],
        qty=2,
    )
    wine_line = FX.append_add_on_line(
        api,
        world["reservation"]["id"],
        world["guest"]["id"],
        world["wine"]["id"],
        qty=2,
    )
    return caviar_line, wine_line


class TestServiceChargeAccumulation:
    """Two half-cent add-on lines make the rounding site observable."""

    def test_each_line_rounds_its_own_service_charge_half_up(self, api):
        """The 9000-cent line charges 653 and the 17000-cent line charges 1233.

        "The ticket line and each add-on line are charged independently, each
        rounded half up on its own, and the rounded per-line figures are then
        summed."

        Design: Difficulty/combinatorial_formula/service_charge_per_line_rounding_vs_sum_then_round
        """
        world = _rounding_world(api)
        caviar_line, wine_line = _append_both_lines(api, world)

        caviar_line = get_success_data(
            api.get_reservation_add_on(caviar_line["id"], world["guest_headers"])
        )
        wine_line = get_success_data(
            api.get_reservation_add_on(wine_line["id"], world["guest_headers"])
        )

        # The unit price is frozen off the catalogue at order time.
        assert caviar_line["unit_price_cents_locked"] == 4500
        assert caviar_line["line_subtotal_cents"] == 9000
        # 9000 times 725 divided by 10000 is exactly 652.5 cents.
        assert caviar_line["line_service_charge_cents"] == 653
        assert C.apply_bp(9000, 725) == 653

        assert wine_line["unit_price_cents_locked"] == 8500
        assert wine_line["line_subtotal_cents"] == 17000
        # 17000 times 725 divided by 10000 is exactly 1232.5 cents.
        assert wine_line["line_service_charge_cents"] == 1233
        assert C.apply_bp(17000, 725) == 1233

    def test_the_rounded_lines_are_summed_rather_than_the_raw_subtotals(self, api):
        """The reservation charges 4496 cents of service charge, not 4495.

        "Summing the raw subtotals first and rounding the service charge once at
        the end is the wrong variant and diverges by cents; the per-line
        rounding is normative."

        Design: Difficulty/combinatorial_formula/service_charge_per_line_rounding_vs_sum_then_round
        """
        world = _rounding_world(api)
        _append_both_lines(api, world)

        reservation = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=36000,
            add_on_total=26000,
            service_charge=4496,
            grand_total=66496,
        )
        # 2610 on the ticket line plus 653 plus 1233.
        assert reservation["service_charge_cents"] == 2610 + 653 + 1233
        # Rounding the 62000-cent aggregate once would have charged 4495.
        assert reservation["service_charge_cents"] != 4495
        assert C.apply_bp(62000, 725) == 4495
        assert (
            C.charge_breakdown(18000, 2, 725, [(4500, 2), (8500, 2)])[
                "service_charge_cents"
            ]
            == 4496
        )

    def test_the_frozen_deposit_ignores_the_lines_that_arrived_after_it(self, api):
        """The deposit stays at 11583 while the grand total climbs to 66496.

        "Once the deposit is frozen it retains its frozen value and stops
        tracking the grand total altogether."

        Design: Difficulty/combinatorial_formula/service_charge_per_line_rounding_vs_sum_then_round
        """
        world = _rounding_world(api)
        before = world["reservation"]
        assert before["deposit_frozen"] is True
        A.assert_money_breakdown(
            before,
            grand_total=38610,
            deposit_due=11583,
            amount_paid=11583,
        )

        _append_both_lines(api, world)
        after = FX.read_reservation(
            api, world["reservation"]["id"], world["guest_headers"]
        )

        assert after["deposit_frozen"] is True
        assert after["deposit_due_cents"] == 11583
        assert after["grand_total_cents"] == 66496
        # 66496 less the 11583 already paid.
        assert after["balance_due_cents"] == 54913
        assert after["amount_paid_cents"] == 11583
        A.assert_payment_status(after, "DEPOSIT_PAID")
        A.assert_balance_due(after)


def _fee_band_world(api):
    """One published Saturday HIGH service carrying three classes, each with one
    deposit-paid CONFIRMED booking whose deposit lands in a different rebooking
    fee band.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api, service_charge_bp=725, refund_scrutiny_threshold_cents=300000
    )
    package_small = FX.create_package(
        api,
        restaurant["id"],
        name="Small Tasting",
        course_count=8,
        base_price_cents=12000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        min_party_size=1,
        max_party_size=8,
    )
    package_big = FX.create_package(
        api,
        restaurant["id"],
        name="Grand Tasting",
        course_count=12,
        base_price_cents=60000,
        prepayment_mode="DEPOSIT",
        deposit_bp=3000,
        forfeiture_schedule_code="STANDARD",
        forfeiture_basis="DEPOSIT_BASIS",
        min_party_size=1,
        max_party_size=8,
    )
    service = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-12",
        meal_period="DINNER",
        seating_start_utc=SEATING_START_HIGH,
        seating_end_utc=SEATING_END_HIGH,
        turn_time_minutes=150,
        seats_capacity=60,
        demand_tier="HIGH",
    )
    tc_small_one = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package_small["id"], seats_allocated=20
    )
    tc_small_two = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package_small["id"], seats_allocated=20
    )
    tc_big = FX.create_ticket_class(
        api, restaurant["id"], service["id"], package_big["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service["id"])

    guests = [FX.create_guest(api, display_name=f"Fee {n}") for n in range(1, 4)]
    # A party of 2 on the 12000-cent package, a party of 8 on a second class of
    # the same package, and a party of 3 on the 60000-cent package.
    bookings = [
        FX.confirmed_reservation(api, tc_small_one["id"], guests[0]["id"], party_size=2),
        FX.confirmed_reservation(api, tc_small_two["id"], guests[1]["id"], party_size=8),
        FX.confirmed_reservation(api, tc_big["id"], guests[2]["id"], party_size=3),
    ]
    return {
        "restaurant": restaurant,
        "manager": make_restaurant_headers(restaurant["id"]),
        "service": service,
        "ticket_classes": [tc_small_one, tc_small_two, tc_big],
        "guests": guests,
        "bookings": bookings,
    }


def _cancel_all_at_48_hours(api, world):
    """Cancel all three bookings at one and the same clock value."""
    FX.set_clock(api, CANCEL_AT_48H)
    settled = []
    for booking, guest in zip(world["bookings"], world["guests"]):
        FX.cancel(api, booking["id"], guest["id"])
        settled.append(
            FX.read_reservation(api, booking["id"], make_guest_headers(guest["id"]))
        )
    return settled


class TestRebookingFeeBand:
    """One band, one instant, three different fees."""

    def test_the_fee_band_follows_the_forfeiture_and_not_the_calendar(self, api):
        """Retentions of 6292, 24666 and 46437 embed fees of 500, 1500 and 3000.

        "The bands are: a raw forfeiture of exactly 0 cents attracts a fee of 0
        cents; a raw forfeiture of 9999 cents or less attracts 500 cents; a raw
        forfeiture of 39999 cents or less attracts 1500 cents; anything above
        that attracts 3000 cents."

        Design: Difficulty/combinatorial_formula/rebook_fee_band_keyed_on_forfeiture_amount
        """
        world = _fee_band_world(api)
        settled = _cancel_all_at_48_hours(api, world)

        # The band is 5000 basis points of the deposit for all three.
        expected = [
            (11583, 5792, 500, 6292),
            (46332, 23166, 1500, 24666),
            (86873, 43437, 3000, 46437),
        ]
        for reservation, (deposit, raw, fee, retained) in zip(settled, expected):
            assert reservation["deposit_due_cents"] == deposit
            assert C.apply_bp(deposit, 5000) == raw
            assert C.rebook_fee_cents(raw) == fee
            assert reservation["forfeited_cents"] == retained, (
                f"a raw forfeiture of {raw} cents should retain {raw} plus a "
                f"{fee}-cent fee, got {reservation['forfeited_cents']}"
            )
            assert reservation["forfeited_cents"] - raw == fee

        # Three fees, one instant, one band: the fee cannot have been read off
        # the hours to service.
        fees = [
            reservation["forfeited_cents"] - C.apply_bp(deposit, 5000)
            for reservation, (deposit, _, _, _) in zip(settled, expected)
        ]
        assert fees == [500, 1500, 3000]
        assert len(set(fees)) == 3

    def test_each_refund_is_what_the_capped_retention_left_behind(self, api):
        """Refunds of 5291, 21666 and 40436 cents, all PARTIALLY_REFUNDED.

        "The retained amount is the lesser of `amount_paid_cents` and the sum of
        the raw forfeiture and the rebooking fee; the shortfall is never chased."

        Design: Difficulty/combinatorial_formula/rebook_fee_band_keyed_on_forfeiture_amount
        """
        world = _fee_band_world(api)
        settled = _cancel_all_at_48_hours(api, world)

        expected = [(11583, 6292, 5291), (46332, 24666, 21666), (86873, 46437, 40436)]
        for reservation, (paid, retained, refund) in zip(settled, expected):
            assert reservation["amount_paid_cents"] == paid
            assert reservation["forfeited_cents"] == retained
            assert reservation["refunded_cents"] == refund
            # None of the three retentions reached what the guest had paid, so
            # the cap did not bind and a refund survived in every case.
            assert retained < paid
            A.assert_payment_status(reservation, "PARTIALLY_REFUNDED")
            A.assert_fulfillment_status(reservation, "CANCELLED")
            A.assert_settled_ledger_identity(reservation)
            assert reservation["cancel_settlement_basis"] == "DEPOSIT_BASIS"

    def test_the_deposit_is_the_basis_the_band_bit_on(self, api):
        """The three bases are 11583, 46332 and 86873 cents of deposit.

        "Under `DEPOSIT_BASIS` the basis is the reservation's
        `deposit_due_cents`; under `FULL_TICKET_BASIS` it is the reservation's
        `grand_total_cents`. The raw forfeiture is the basis multiplied by the
        band in basis points, divided by 10000, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/rebook_fee_band_keyed_on_forfeiture_amount
        """
        world = _fee_band_world(api)
        guest_headers = [make_guest_headers(guest["id"]) for guest in world["guests"]]
        bookings = [
            FX.read_reservation(api, booking["id"], headers)
            for booking, headers in zip(world["bookings"], guest_headers)
        ]

        A.assert_money_breakdown(
            bookings[0],
            ticket_subtotal=36000,
            service_charge=2610,
            grand_total=38610,
            deposit_due=11583,
        )
        A.assert_money_breakdown(
            bookings[1],
            ticket_subtotal=144000,
            service_charge=10440,
            grand_total=154440,
            deposit_due=46332,
        )
        assert bookings[2]["price_locked_per_cover_cents"] == 90000
        A.assert_money_breakdown(
            bookings[2],
            ticket_subtotal=270000,
            service_charge=19575,
            grand_total=289575,
            deposit_due=86873,
        )
        # 289575 times 3000 divided by 10000 is exactly 86872.5 cents.
        assert C.apply_bp(289575, 3000) == 86873

        # The same 5000-basis-point band applies to all three at 48.0 hours out.
        assert C.forfeiture_band_bp("STANDARD", 48.0) == 5000
        for booking in bookings:
            assert (
                C.apply_bp(booking["deposit_due_cents"], 5000)
                != C.apply_bp(booking["grand_total_cents"], 5000)
            )
