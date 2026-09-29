"""
Edge arithmetic of the money and score derivations: the five-step per-cover
price against the declared day-of-week and demand-tier basis-point matrices,
half-up rounding at every named money step, the seat counters the scarcity step
is allowed to see, the kitchen prep-minute running total, the waitlist ranking
key, and the strict comparison that raises a guest's refund-scrutiny flag.

Every asserted money figure is the PRD's own literal; the arithmetic helpers of
``test_helpers.constants`` are used only to cross-check those literals, never to
stand in for them.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.test_users import make_guest_headers, make_restaurant_headers

# The instant every scenario below pins the logical clock to before anything
# else happens. It sits far inside every hold, cutoff and release window.
SETUP_CLOCK = "2026-09-01T00:00:00Z"

# 2026-09-10 is a Thursday, the neutral day at 10000 basis points.
THU_SEATING_START = "2026-09-10T22:00:00Z"
THU_SEATING_END = "2026-09-11T02:00:00Z"
# 2026-09-11 is a Friday, which carries 11500 basis points.
FRI_SEATING_START = "2026-09-11T22:00:00Z"
FRI_SEATING_END = "2026-09-12T02:00:00Z"
# 2026-09-07 is a Monday, which carries 9500 basis points.
MON_SEATING_START = "2026-09-07T22:00:00Z"
MON_SEATING_END = "2026-09-08T02:00:00Z"

# "hold_expires_at_utc is set to the logical clock plus the restaurant's
# hold_ttl_minutes": twenty minutes past SETUP_CLOCK, so one minute later the
# hold has lapsed and the sweep may reap it.
AFTER_HOLD_TTL = "2026-09-01T00:21:00Z"

SERVICE_CHARGE_BP = 725
BASE_PRICE_CENTS = 12000
DEPOSIT_BP = 3000
RELEASE_DISCOUNT_BP = 1500


def _quote(api, ticket_class_id, headers):
    """Re-derive one class's sell-through and both of its per-cover prices."""
    return get_success_data(api.price_quote(ticket_class_id, headers))


def _thursday_world(api, **overrides):
    """A published Thursday STANDARD service carrying one class of a 12000-cent
    package, plus the guests that will buy from it.
    """
    return FX.build_world(api, clock=SETUP_CLOCK, **overrides)


class TestThursdayStandardQuoteAndChargeBreakdown:
    """The whole reference chain from a neutral calendar factor to a balance."""

    def test_quote_prices_a_neutral_thursday_standard_cover_at_the_base(self, api):
        """THU 10000 bp times STANDARD 10000 bp leaves the base untouched.

        "The two are combined by multiplying the day-of-week factor by the
        demand-tier factor, dividing the product by 10000, and rounding that
        basis-point intermediate half up to a whole basis point."

        Design: Corner/calculations/correct_result_price_quote_and_charge_breakdown_thursday_standard
        """
        world = _thursday_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        service = FX.read_service(api, world["service_id"], guest_headers)
        assert service["day_of_week"] == "THU"
        assert service["demand_tier"] == "STANDARD"

        quote = _quote(api, world["ticket_class_id"], guest_headers)
        assert quote["sell_through_bp"] == 0
        assert quote["list_price_per_cover_cents"] == 12000
        assert quote["release_price_per_cover_cents"] == 10200

        # Cross-check the two literals against the declared matrices.
        assert C.DOW_BP["THU"] == 10000
        assert C.TIER_BP["STANDARD"] == 10000
        assert C.list_price_per_cover(BASE_PRICE_CENTS, "THU", "STANDARD", 0) == 12000
        assert C.release_price_per_cover(12000, RELEASE_DISCOUNT_BP) == 10200

        A.assert_seat_pool(
            quote, sold=0, held=0, released=0, available=20, status="OPEN"
        )

    def test_reservation_locks_the_quoted_cover_and_derives_the_breakdown(self, api):
        """A party of two turns 12000 into 24000, 1740 and 25740.

        "The ticket's own service charge is that subtotal multiplied by the
        restaurant's `service_charge_bp`, divided by 10000, rounded half up."

        Design: Corner/calculations/correct_result_price_quote_and_charge_breakdown_thursday_standard
        """
        world = _thursday_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Price Guest",
        )

        assert reservation["price_locked_per_cover_cents"] == 12000
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=24000,
            add_on_total=0,
            service_charge=1740,
            grand_total=25740,
            deposit_due=7722,
            amount_paid=0,
        )
        assert reservation["balance_due_cents"] == 25740
        assert reservation["is_release_priced"] is False
        A.assert_fulfillment_status(reservation, "PENDING")
        A.assert_payment_status(reservation, "UNPAID")

        # The same figures fall out of the declared per-line arithmetic.
        assert C.charge_breakdown(12000, 2, SERVICE_CHARGE_BP) == {
            "ticket_subtotal_cents": 24000,
            "add_on_total_cents": 0,
            "service_charge_cents": 1740,
            "grand_total_cents": 25740,
        }
        assert C.deposit_due(25740, "DEPOSIT", DEPOSIT_BP) == 7722

    def test_deposit_payment_leaves_the_balance_and_the_hold_below_the_step(self, api):
        """7722 paid against 25740 leaves 18018, and two of twenty seats held
        put sell-through at 1000 bp, below the first scarcity step.

        "Where it has not reached 8000 but has reached 5000, the step is 800
        basis points. Below 5000 there is no step at all."

        Design: Corner/calculations/correct_result_price_quote_and_charge_breakdown_thursday_standard
        """
        world = _thursday_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Price Guest",
        )
        FX.pay(api, reservation["id"], world["guest_id"], 7722)
        paid = FX.read_reservation(api, reservation["id"], guest_headers)

        A.assert_money_breakdown(paid, amount_paid=7722, grand_total=25740)
        assert paid["balance_due_cents"] == 18018
        A.assert_payment_status(paid, "DEPOSIT_PAID")

        after_hold = _quote(api, world["ticket_class_id"], guest_headers)
        assert after_hold["sell_through_bp"] == 1000
        assert after_hold["list_price_per_cover_cents"] == 12000
        assert C.scarcity_step_bp(1000) == 0
        A.assert_seat_pool(
            after_hold, sold=0, held=2, released=0, available=18, status="OPEN"
        )


# One row per calendar day of a single week: (service_date, day_of_week,
# demand_tier, list_price_per_cover_cents, release_price_per_cover_cents).
# Every price is the PRD's own arithmetic on a 12000-cent base with the default
# 1500-basis-point release discount.
DOW_TIER_MATRIX = (
    ("2026-09-07", "MON", "LOW", 10260, 8721),
    ("2026-09-08", "TUE", "HIGH", 13680, 11628),
    ("2026-09-09", "WED", "PEAK", 16530, 14051),
    ("2026-09-10", "THU", "STANDARD", 12000, 10200),
    ("2026-09-11", "FRI", "STANDARD", 13800, 11730),
    ("2026-09-12", "SAT", "HIGH", 18000, 15300),
    ("2026-09-13", "SUN", "PEAK", 19140, 16269),
)


def _matrix_world(api):
    """One restaurant and one 12000-cent package, carrying a published service
    per calendar day of the same week, each at its own demand tier.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(api, service_charge_bp=SERVICE_CHARGE_BP)
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Matrix Tasting Menu",
        base_price_cents=BASE_PRICE_CENTS,
        release_discount_bp=RELEASE_DISCOUNT_BP,
    )
    rows = {}
    for service_date, day_of_week, demand_tier, _list_price, _release in (
        DOW_TIER_MATRIX
    ):
        service = FX.create_service(
            api,
            restaurant["id"],
            service_date=service_date,
            meal_period="DINNER",
            seating_start_utc=service_date + "T22:00:00Z",
            seating_end_utc=F.shift(service_date + "T22:00:00Z", hours=4),
            demand_tier=demand_tier,
        )
        ticket_class = FX.create_ticket_class(
            api, restaurant["id"], service["id"], package["id"], seats_allocated=20
        )
        FX.publish_service(api, restaurant["id"], service["id"])
        rows[day_of_week] = {
            "service_id": service["id"],
            "ticket_class_id": ticket_class["id"],
        }
    guest = FX.create_guest(api, display_name="Matrix Guest")
    return {
        "restaurant_id": restaurant["id"],
        "package_id": package["id"],
        "rows": rows,
        "guest_id": guest["id"],
        "manager_headers": make_restaurant_headers(restaurant["id"]),
    }


class TestDayOfWeekAndTierBasisPointMatrix:
    """Every declared calendar factor crossed with a declared demand factor."""

    def test_every_day_and_tier_pair_prices_its_own_list_cover(self, api):
        """All seven calendar factors combine with their tier as declared.

        "The day-of-week factor is read off the service's derived `day_of_week`:
        Monday, Tuesday and Wednesday each carry 9500 basis points — a five
        percent discount on list; Thursday is neutral at 10000; Friday carries
        11500; Saturday is the strongest day at 12500; and Sunday sits at
        11000." "The demand-tier factor is read off the service's `demand_tier`:
        `LOW` is 9000, `STANDARD` is 10000, `HIGH` is 12000, and `PEAK` is
        14500."

        Design: Corner/calculations/constants_applied_dow_and_tier_basis_point_matrix
        """
        world = _matrix_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        for service_date, day_of_week, demand_tier, list_price, _release in (
            DOW_TIER_MATRIX
        ):
            row = world["rows"][day_of_week]
            service = FX.read_service(api, row["service_id"], guest_headers)
            # The calendar factor is keyed on a derived field, never a client one.
            assert service["service_date"] == service_date
            assert service["day_of_week"] == day_of_week
            assert service["demand_tier"] == demand_tier

            quote = _quote(api, row["ticket_class_id"], guest_headers)
            assert quote["sell_through_bp"] == 0
            assert quote["list_price_per_cover_cents"] == list_price
            # Cross-check the literal against the declared basis-point tables.
            assert (
                C.list_price_per_cover(BASE_PRICE_CENTS, day_of_week, demand_tier, 0)
                == list_price
            )

        # No two consecutive days of this week price alike.
        distinct = {row[3] for row in DOW_TIER_MATRIX}
        assert len(distinct) == 7

    def test_every_pair_carries_its_release_price_off_the_list_figure(self, api):
        """The 1500-basis-point release discount rides on each list figure.

        "The discount therefore comes off the scarcity-adjusted figure, never off
        the pre-scarcity list price."

        Design: Corner/calculations/constants_applied_dow_and_tier_basis_point_matrix
        """
        world = _matrix_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        for _service_date, day_of_week, _tier, list_price, release_price in (
            DOW_TIER_MATRIX
        ):
            row = world["rows"][day_of_week]
            quote = _quote(api, row["ticket_class_id"], guest_headers)
            assert quote["list_price_per_cover_cents"] == list_price
            assert quote["release_price_per_cover_cents"] == release_price
            assert (
                C.release_price_per_cover(list_price, RELEASE_DISCOUNT_BP)
                == release_price
            )
            # The release figure is strictly the cheaper of the two.
            assert release_price < list_price


def _odd_cent_world(api):
    """A Monday LOW service on a 10001-cent base — deliberately chosen so that
    every named money step lands on a half-cent remainder — plus a 100-cent
    add-on whose two units also charge to an exact half cent.
    """
    world = FX.build_world(
        api,
        clock=SETUP_CLOCK,
        restaurant={"service_charge_bp": SERVICE_CHARGE_BP},
        package={
            "name": "Odd Cent Menu",
            "base_price_cents": 10001,
            "deposit_bp": DEPOSIT_BP,
            "kitchen_prep_minutes_per_cover": 12,
            "min_party_size": 1,
        },
        service={
            "service_date": "2026-09-07",
            "seating_start_utc": MON_SEATING_START,
            "seating_end_utc": MON_SEATING_END,
            "demand_tier": "LOW",
        },
    )
    world["add_on"] = FX.create_add_on(
        api,
        world["restaurant_id"],
        name="Half Cent Pairing",
        price_cents=100,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
    )
    return world


class TestRoundHalfUpAtEveryNamedMoneyStep:
    """Every step of the chain sits on an exact half-cent remainder."""

    def test_cover_price_charge_and_deposit_each_round_half_up_once(self, api):
        """8550.855 cents becomes 8551, 619.9475 becomes 620, 2751.3 becomes 2751.

        "Every named step in every calculation in this document rounds half up at
        that step; intermediate basis-point figures are themselves rounded half
        up before they are used further, and no calculation defers rounding to a
        later step unless this document explicitly says so."

        Design: Corner/calculations/precision_round_half_up_at_every_named_money_step
        """
        world = _odd_cent_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        quote = _quote(api, world["ticket_class_id"], guest_headers)
        # MON 9500 bp times LOW 9000 bp is 8550 bp, above the 8500 floor.
        assert quote["list_price_per_cover_cents"] == 8551
        assert C.combined_factor_bp("MON", "LOW") == 8550
        assert C.clamp_factor_bp(8550) == 8550
        # Truncation would have produced 8550; half up produces 8551.
        assert 10001 * 8550 // 10000 == 8550

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=1,
            primary_guest_name="Half Cent Guest",
        )
        assert reservation["price_locked_per_cover_cents"] == 8551
        A.assert_money_breakdown(
            reservation,
            ticket_subtotal=8551,
            add_on_total=0,
            service_charge=620,
            grand_total=9171,
            deposit_due=2751,
        )
        assert C.apply_bp(8551, SERVICE_CHARGE_BP) == 620
        assert C.deposit_due(9171, "DEPOSIT", DEPOSIT_BP) == 2751

    def test_add_on_line_charge_rounds_on_that_line_alone(self, api):
        """A line charge of exactly 14.5 cents rounds up to 15, and the
        reservation's service charge is the sum of the two rounded lines.

        "Summing the raw subtotals first and rounding the service charge once at
        the end is the wrong variant and diverges by cents; the per-line rounding
        is normative."

        Design: Corner/calculations/precision_round_half_up_at_every_named_money_step
        """
        world = _odd_cent_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=1,
            primary_guest_name="Half Cent Guest",
        )
        line = FX.append_add_on_line(
            api,
            reservation["id"],
            world["guest_id"],
            world["add_on"]["id"],
            qty=2,
        )
        assert line["unit_price_cents_locked"] == 100
        assert line["line_subtotal_cents"] == 200
        # 200 * 725 / 10000 is exactly 14.5 cents; half up on this line alone.
        assert line["line_service_charge_cents"] == 15
        assert line["line_prep_minutes"] == 8

        after = FX.read_reservation(api, reservation["id"], guest_headers)
        A.assert_money_breakdown(
            after,
            ticket_subtotal=8551,
            add_on_total=200,
            service_charge=635,
            grand_total=9386,
        )
        # The forbidden variant rounds 8751 * 725 / 10000 once, to 634, and so
        # reaches a grand total of 9385 rather than 9386.
        assert C.apply_bp(8751, SERVICE_CHARGE_BP) == 634
        assert after["service_charge_cents"] != 634
        assert after["grand_total_cents"] != 9385
        assert C.charge_breakdown(
            8551, 1, SERVICE_CHARGE_BP, add_on_lines=((100, 2),)
        ) == {
            "ticket_subtotal_cents": 8551,
            "add_on_total_cents": 200,
            "service_charge_cents": 635,
            "grand_total_cents": 9386,
        }

    def test_unfrozen_deposit_and_prep_minutes_follow_the_new_grand_total(
        self, api
    ):
        """With nothing yet paid the deposit re-rounds 2815.8 up to 2816, and the
        prep total takes whole minutes with no rounding at all.

        "Once the deposit is frozen it retains its frozen value and stops
        tracking the grand total altogether."

        Design: Corner/calculations/precision_round_half_up_at_every_named_money_step
        """
        world = _odd_cent_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=1,
            primary_guest_name="Half Cent Guest",
        )
        assert reservation["deposit_frozen"] is False
        FX.append_add_on_line(
            api,
            reservation["id"],
            world["guest_id"],
            world["add_on"]["id"],
            qty=2,
        )

        after = FX.read_reservation(api, reservation["id"], guest_headers)
        assert after["deposit_frozen"] is False
        assert after["grand_total_cents"] == 9386
        assert after["deposit_due_cents"] == 2816
        assert C.deposit_due(9386, "DEPOSIT", DEPOSIT_BP) == 2816
        assert after["balance_due_cents"] == 9386
        # One cover at 12 minutes plus two add-on units at 4 minutes each.
        assert after["prep_minutes_total"] == 20
        assert C.prep_minutes_total(1, 12, add_on_lines=((4, 2),)) == 20


def _tiny_allocation_world(api):
    """A four-seat Thursday STANDARD class, so that a single party of two puts
    the class at exactly 5000 basis points of sell-through.
    """
    return FX.build_world(
        api,
        clock=SETUP_CLOCK,
        restaurant={"service_charge_bp": SERVICE_CHARGE_BP},
        package={
            "name": "Four Seat Counter",
            "base_price_cents": BASE_PRICE_CENTS,
            "release_discount_bp": RELEASE_DISCOUNT_BP,
        },
        service={
            "service_date": "2026-09-10",
            "seating_start_utc": THU_SEATING_START,
            "seating_end_utc": THU_SEATING_END,
            "demand_tier": "STANDARD",
        },
        ticket_class={"seats_allocated": 4},
    )


class TestScarcityStepInputSet:
    """Which seats the scarcity step is allowed to count, and which it is not."""

    def test_a_hold_lifts_the_step_but_never_prices_its_own_seats(self, api):
        """The booking locks 12000, and only afterwards does the class read 5000
        basis points and price the next cover at 12960.

        "First, the only inputs are the class's own `seats_sold` and
        `seats_held`, read **before** the current write credits its own seats — a
        reservation never prices itself into a higher scarcity step."

        Design: Corner/calculations/input_set_filtering_scarcity_step_ignores_cancelled_holds
        """
        world = _tiny_allocation_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        before = _quote(api, world["ticket_class_id"], guest_headers)
        assert before["sell_through_bp"] == 0
        assert before["list_price_per_cover_cents"] == 12000

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Counter Guest",
        )
        # The two seats it is buying are not counted against itself.
        assert reservation["price_locked_per_cover_cents"] == 12000
        A.assert_money_breakdown(
            reservation, ticket_subtotal=24000, service_charge=1740, grand_total=25740
        )

        after = _quote(api, world["ticket_class_id"], guest_headers)
        # Two of four seats held is exactly 5000 basis points, the mid step.
        assert after["sell_through_bp"] == 5000
        assert C.sell_through_bp(0, 2, 4) == 5000
        assert C.scarcity_step_bp(5000) == 800
        assert after["list_price_per_cover_cents"] == 12960
        assert after["release_price_per_cover_cents"] == 11016
        assert C.list_price_per_cover(BASE_PRICE_CENTS, "THU", "STANDARD", 5000) == 12960
        assert C.release_price_per_cover(12960, RELEASE_DISCOUNT_BP) == 11016
        A.assert_seat_pool(
            after, sold=0, held=2, released=0, available=2, status="OPEN"
        )

    def test_cancelling_the_hold_drops_it_out_of_the_scarcity_inputs(self, api):
        """Once the hold is cancelled the class prices at 12000 again.

        "Second, reservations in `CANCELLED`, `NO_SHOW`, `EXPIRED` or
        `TRANSFERRED_OUT` have already been removed from those counters by the
        seat-pool accounting of §2.6 and are therefore excluded automatically."

        Design: Corner/calculations/input_set_filtering_scarcity_step_ignores_cancelled_holds
        """
        world = _tiny_allocation_world(api)
        guest_headers = make_guest_headers(world["guest_id"])

        reservation = FX.hold_seats(
            api,
            world["ticket_class_id"],
            world["guest_id"],
            party_size=2,
            primary_guest_name="Counter Guest",
        )
        assert (
            _quote(api, world["ticket_class_id"], guest_headers)["sell_through_bp"]
            == 5000
        )

        FX.cancel(api, reservation["id"], world["guest_id"])
        cancelled = FX.read_reservation(api, reservation["id"], guest_headers)
        A.assert_fulfillment_status(cancelled, "CANCELLED")
        assert cancelled["forfeited_cents"] == 0

        after = _quote(api, world["ticket_class_id"], guest_headers)
        assert after["sell_through_bp"] == 0
        assert after["list_price_per_cover_cents"] == 12000
        assert after["release_price_per_cover_cents"] == 10200
        A.assert_seat_pool(
            after, sold=0, held=0, released=0, available=4, status="OPEN"
        )


def _prep_minutes_world(api):
    """A party-of-two Thursday booking on a 12-minute-per-cover package, with a
    4-minute-per-unit add-on available to it.
    """
    world = FX.build_world(
        api,
        clock=SETUP_CLOCK,
        restaurant={"service_charge_bp": SERVICE_CHARGE_BP},
        package={
            "name": "Prep Minute Menu",
            "base_price_cents": BASE_PRICE_CENTS,
            "kitchen_prep_minutes_per_cover": 12,
        },
        service={
            "service_date": "2026-09-10",
            "seating_start_utc": THU_SEATING_START,
            "seating_end_utc": THU_SEATING_END,
            "demand_tier": "STANDARD",
        },
    )
    world["add_on"] = FX.create_add_on(
        api,
        world["restaurant_id"],
        name="Caviar Supplement",
        price_cents=4500,
        prep_minutes_per_unit=4,
        max_qty_per_cover=2,
        order_cutoff_minutes=1440,
    )
    world["reservation"] = FX.hold_seats(
        api,
        world["ticket_class_id"],
        world["guest_id"],
        party_size=2,
        primary_guest_name="Prep Guest",
    )
    return world


class TestPrepMinutesRunningTotal:
    """The three prep terms accumulate and then shrink as the note is revised."""

    def test_note_and_add_on_line_each_push_the_running_total_up(self, api):
        """24 baseline minutes become 39 with an anaphylaxis note and 47 with two
        add-on units, and a prep rejection changes nothing.

        "It is the sum of three terms: a baseline of the reservation's
        `party_size` multiplied by the package's `kitchen_prep_minutes_per_cover`;
        plus the severity minutes of every one of the reservation's dietary notes,
        counted **regardless of `ack_status`**, because a still-pending allergy
        consumes kitchen time exactly as an acknowledged one does; plus, over
        every add-on line on the reservation, the add-on's `prep_minutes_per_unit`
        multiplied by that line's `qty`."

        Design: Corner/calculations/aggregation_prep_minutes_running_total_after_add_and_downgrade
        """
        world = _prep_minutes_world(api)
        guest_headers = make_guest_headers(world["guest_id"])
        reservation_id = world["reservation"]["id"]

        # Two covers at 12 minutes each and nothing else yet.
        assert world["reservation"]["prep_minutes_total"] == 24

        note = FX.add_dietary_note(
            api,
            reservation_id,
            world["guest_id"],
            guest_index=1,
            severity="ANAPHYLAXIS",
            restriction_code="SHELLFISH",
            note_text="Anaphylactic to shellfish.",
        )
        assert note["severity"] == "ANAPHYLAXIS"
        assert note["prep_minutes"] == 15
        assert note["ack_status"] == "PENDING"
        with_note = FX.read_reservation(api, reservation_id, guest_headers)
        assert with_note["prep_minutes_total"] == 39

        line = FX.append_add_on_line(
            api, reservation_id, world["guest_id"], world["add_on"]["id"], qty=2
        )
        assert line["line_prep_minutes"] == 8
        with_line = FX.read_reservation(api, reservation_id, guest_headers)
        assert with_line["prep_minutes_total"] == 47
        assert C.prep_minutes_total(
            2, 12, severities=("ANAPHYLAXIS",), add_on_lines=((4, 2),)
        ) == 47

        # A prep rejection is not a deletion: the minutes stay on the books.
        rejected = FX.reject_note(api, world["restaurant_id"], note["id"])
        assert rejected["ack_status"] == "PREP_REJECTED"
        assert rejected["prep_minutes"] == 15
        after_reject = FX.read_reservation(api, reservation_id, guest_headers)
        assert after_reject["prep_minutes_total"] == 47

    def test_amending_the_severity_downward_shrinks_the_running_total(self, api):
        """An amendment to INFO re-derives the note at 0 minutes and drops the
        reservation from 47 to 32, leaving the add-on's 8 minutes untouched.

        "A successful amendment credits `amend_count` by 1, clears both
        `reject_reason_code` and `acked_by_user_id` back to null, and re-derives
        `prep_minutes` from the amended severity."

        Design: Corner/calculations/aggregation_prep_minutes_running_total_after_add_and_downgrade
        """
        world = _prep_minutes_world(api)
        guest_headers = make_guest_headers(world["guest_id"])
        reservation_id = world["reservation"]["id"]

        note = FX.add_dietary_note(
            api,
            reservation_id,
            world["guest_id"],
            guest_index=1,
            severity="ANAPHYLAXIS",
            restriction_code="SHELLFISH",
            note_text="Anaphylactic to shellfish.",
        )
        FX.append_add_on_line(
            api, reservation_id, world["guest_id"], world["add_on"]["id"], qty=2
        )
        FX.reject_note(api, world["restaurant_id"], note["id"])
        assert (
            FX.read_reservation(api, reservation_id, guest_headers)[
                "prep_minutes_total"
            ]
            == 47
        )

        amended = FX.amend_note(
            api,
            note["id"],
            world["guest_id"],
            severity="INFO",
            restriction_code="GLUTEN",
            note_text="Prefers gluten free bread.",
        )
        assert amended["ack_status"] == "PENDING"
        assert amended["severity"] == "INFO"
        assert amended["prep_minutes"] == 0
        assert amended["amend_count"] == 1
        assert amended["reject_reason_code"] is None

        after = FX.read_reservation(api, reservation_id, guest_headers)
        # 24 baseline plus 0 for the downgraded note plus 8 for the add-on line.
        assert after["prep_minutes_total"] == 32
        assert C.prep_minutes_total(
            2, 12, severities=("INFO",), add_on_lines=((4, 2),)
        ) == 32

    def test_the_add_on_line_that_added_minutes_also_added_money(self, api):
        """The same two units carry 9000 cents of subtotal and a 653-cent line
        charge into the reservation's totals.

        "`add_on_total_cents` accumulates the line subtotals; `service_charge_cents`
        accumulates the ticket's charge plus every rounded per-line charge."

        Design: Corner/calculations/aggregation_prep_minutes_running_total_after_add_and_downgrade
        """
        world = _prep_minutes_world(api)
        guest_headers = make_guest_headers(world["guest_id"])
        reservation_id = world["reservation"]["id"]

        line = FX.append_add_on_line(
            api, reservation_id, world["guest_id"], world["add_on"]["id"], qty=2
        )
        assert line["unit_price_cents_locked"] == 4500
        assert line["line_subtotal_cents"] == 9000
        # 9000 * 725 / 10000 is exactly 652.5 cents, which rounds up to 653.
        assert line["line_service_charge_cents"] == 653

        after = FX.read_reservation(api, reservation_id, guest_headers)
        A.assert_money_breakdown(
            after,
            ticket_subtotal=24000,
            add_on_total=9000,
            service_charge=2393,
            grand_total=35393,
        )
        assert C.charge_breakdown(
            12000, 2, SERVICE_CHARGE_BP, add_on_lines=((4500, 2),)
        ) == {
            "ticket_subtotal_cents": 24000,
            "add_on_total_cents": 9000,
            "service_charge_cents": 2393,
            "grand_total_cents": 35393,
        }
        assert after["prep_minutes_total"] == 32


def _waitlist_scoring_world(api):
    """One published Thursday service with three waiting entries of different
    party sizes, every guest carrying a clean record.
    """
    world = FX.build_world(
        api,
        clock=SETUP_CLOCK,
        restaurant={"service_charge_bp": SERVICE_CHARGE_BP},
        package={"name": "Ranking Menu", "base_price_cents": BASE_PRICE_CENTS},
        service={
            "service_date": "2026-09-10",
            "seating_start_utc": THU_SEATING_START,
            "seating_end_utc": THU_SEATING_END,
            "waitlist_policy": "YIELD_WEIGHTED",
        },
        guests=3,
    )
    guests = world["guests"]
    world["entries"] = [
        FX.join_waitlist(api, world["service_id"], guests[0]["id"], party_size=2),
        FX.join_waitlist(api, world["service_id"], guests[1]["id"], party_size=3),
        FX.join_waitlist(
            api,
            world["service_id"],
            guests[2]["id"],
            party_size=8,
            requested_package_id=world["package_id"],
        ),
    ]
    return world


class TestPriorityScoreFromDeclaredWeights:
    """Party size is the only term in play, so each entry scores differently."""

    def test_each_party_size_scores_its_declared_weight(self, api):
        """Parties of 2, 3 and 8 with clean records score 1100, 1150 and 1400.

        "It starts from a base of 1000, adds 50 per cover of the entry's
        `party_size`, adds 25 for each of the guest's `completed_reservations_count`
        **capped at 8** so that a hundred past dinners count no more than eight,
        subtracts 300 for each of the guest's `no_show_strikes`, subtracts 200 if
        the entry's `priority_penalty_applied` is true, and subtracts 100 for each
        `offer_round` the entry has already burned through." "For a party of 2
        with a clean record the score is 1100; one no-show strike takes it to 800;
        one burned offer round takes it to 1000; a scrutiny penalty takes it to
        900."

        Design: Corner/calculations/weighted_scoring_priority_score_from_declared_weights
        """
        world = _waitlist_scoring_world(api)

        for entry, guest, party_size, score in zip(
            world["entries"], world["guests"], (2, 3, 8), (1100, 1150, 1400)
        ):
            guest_headers = make_guest_headers(guest["id"])
            # Every subtracting term is provably absent.
            record = FX.read_guest(api, guest["id"], guest_headers)
            assert record["completed_reservations_count"] == 0
            assert record["no_show_strikes"] == 0
            assert record["refund_scrutiny_flag"] is False

            stored = FX.read_waitlist_entry(api, entry["id"], guest_headers)
            assert stored["party_size"] == party_size
            assert stored["status"] == "WAITING"
            assert stored["offer_round"] == 0
            assert stored["priority_penalty_applied"] is False
            assert stored["priority_score"] == score
            assert C.priority_score(party_size) == score

    def test_narrowing_to_a_package_leaves_the_ranking_key_untouched(self, api):
        """A package-narrowed entry scores on the same weights as an open one.

        "A `Guest` joins a waitlist by naming a `service_id`, a `guest_id` and a
        `party_size` between 1 and 20, and may optionally narrow the request to a
        single `requested_package_id`, in which case the entry is only ever
        eligible for ticket classes of that package; left null, the entry is
        eligible for any class of the service."

        Design: Corner/calculations/weighted_scoring_priority_score_from_declared_weights
        """
        world = _waitlist_scoring_world(api)
        open_entry, _mid_entry, narrowed_entry = world["entries"]

        assert open_entry["requested_package_id"] is None
        assert narrowed_entry["requested_package_id"] == world["package_id"]
        assert narrowed_entry["priority_score"] == 1400

        rows, meta = validate_paginated(
            api.list_waitlist_entries(
                world["manager_headers"],
                {"service_id": world["service_id"], "limit": 50, "offset": 0},
            )
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        by_id = {row["id"]: row for row in rows}
        assert len(by_id) == 3
        assert sorted(row["priority_score"] for row in rows) == [1100, 1150, 1400]
        assert by_id[narrowed_entry["id"]]["priority_score"] == 1400
        assert by_id[narrowed_entry["id"]]["priority_penalty_applied"] is False


def _scrutiny_world(api, threshold_cents):
    """One guest with a paid, unconfirmed 7722-cent hold on a Thursday service
    and a waiting entry on the following Friday service, under a restaurant whose
    scrutiny threshold is set to the given figure.
    """
    FX.set_clock(api, SETUP_CLOCK)
    restaurant = FX.create_restaurant(
        api,
        service_charge_bp=SERVICE_CHARGE_BP,
        hold_ttl_minutes=20,
        refund_scrutiny_threshold_cents=threshold_cents,
    )
    package = FX.create_package(
        api,
        restaurant["id"],
        name="Scrutiny Menu",
        base_price_cents=BASE_PRICE_CENTS,
        prepayment_mode="DEPOSIT",
        deposit_bp=DEPOSIT_BP,
    )
    service_paid = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-10",
        meal_period="DINNER",
        seating_start_utc=THU_SEATING_START,
        seating_end_utc=THU_SEATING_END,
        waitlist_policy="FAIR_QUEUE",
    )
    service_waiting = FX.create_service(
        api,
        restaurant["id"],
        service_date="2026-09-11",
        meal_period="DINNER",
        seating_start_utc=FRI_SEATING_START,
        seating_end_utc=FRI_SEATING_END,
        waitlist_policy="YIELD_WEIGHTED",
    )
    ticket_class = FX.create_ticket_class(
        api, restaurant["id"], service_paid["id"], package["id"], seats_allocated=20
    )
    FX.create_ticket_class(
        api, restaurant["id"], service_waiting["id"], package["id"], seats_allocated=20
    )
    FX.publish_service(api, restaurant["id"], service_paid["id"])
    FX.publish_service(api, restaurant["id"], service_waiting["id"])

    guest = FX.create_guest(api, display_name="Scrutiny Guest")
    reservation = FX.hold_seats(
        api,
        ticket_class["id"],
        guest["id"],
        party_size=2,
        primary_guest_name="Scrutiny Guest",
    )
    FX.pay(api, reservation["id"], guest["id"], 7722)
    entry = FX.join_waitlist(
        api, service_waiting["id"], guest["id"], party_size=3
    )
    return {
        "restaurant_id": restaurant["id"],
        "manager_headers": make_restaurant_headers(restaurant["id"]),
        "service_paid_id": service_paid["id"],
        "service_waiting_id": service_waiting["id"],
        "ticket_class_id": ticket_class["id"],
        "guest_id": guest["id"],
        "guest_headers": make_guest_headers(guest["id"]),
        "reservation_id": reservation["id"],
        "entry_id": entry["id"],
    }


class TestRefundScrutinyStrictlyGreaterThanAtTheThreshold:
    """A lifetime total that lands exactly on the threshold must not flag."""

    def test_a_lifetime_total_equal_to_the_threshold_raises_no_flag(self, api):
        """A 7722-cent hold-lapse refund against a 7722-cent threshold leaves the
        flag down.

        "The comparison is strict: a lifetime total exactly equal to the threshold
        does not raise the flag."

        Design: Corner/calculations/constants_applied_refund_scrutiny_strict_greater_than_at_threshold
        """
        world = _scrutiny_world(api, 7722)

        FX.set_clock(api, AFTER_HOLD_TTL)
        FX.sweep_holds(api, world["service_paid_id"])

        swept = FX.read_reservation(
            api, world["reservation_id"], world["guest_headers"]
        )
        A.assert_fulfillment_status(swept, "EXPIRED")
        assert swept["refunded_cents"] == 7722
        assert swept["forfeited_cents"] == 0

        rows = FX.ledger_rows(api, world["reservation_id"], world["guest_headers"])
        refunds = [row for row in rows if row["kind"] == "REFUND"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 7722
        assert refunds[0]["memo_code"] == "HOLD_LAPSE"

        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["lifetime_refunded_cents"] == 7722
        # 7722 is not strictly greater than 7722.
        assert guest["refund_scrutiny_flag"] is False

    def test_the_waiting_entry_keeps_its_unpenalised_ranking_key(self, api):
        """With the flag still down the waiting entry keeps 1150.

        "Anything the guest had paid is refunded in full with `memo_code`
        `HOLD_LAPSE`."

        Design: Corner/calculations/constants_applied_refund_scrutiny_strict_greater_than_at_threshold
        """
        world = _scrutiny_world(api, 7722)

        before = FX.read_waitlist_entry(
            api, world["entry_id"], world["guest_headers"]
        )
        assert before["priority_penalty_applied"] is False
        assert before["priority_score"] == 1150

        FX.set_clock(api, AFTER_HOLD_TTL)
        FX.sweep_holds(api, world["service_paid_id"])

        after = FX.read_waitlist_entry(api, world["entry_id"], world["guest_headers"])
        assert after["status"] == "WAITING"
        assert after["priority_penalty_applied"] is False
        assert after["priority_score"] == 1150
        assert C.priority_score(3) == 1150


class TestRefundScrutinyCrossingTheThreshold:
    """One cent lower, and the same refund rescores the waiting entry."""

    def test_crossing_the_threshold_raises_the_one_way_flag(self, api):
        """7722 refunded against a 7721-cent threshold raises the flag.

        "If the running lifetime total then stands **strictly greater than** the
        restaurant's `refund_scrutiny_threshold_cents`, the guest's
        `refund_scrutiny_flag` is raised to true, and every one of that guest's
        waitlist entries **whose status is `WAITING` at that moment** has its
        `priority_penalty_applied` set to true and its `priority_score`
        re-derived."

        Design: Corner/calculations/correct_result_refund_scrutiny_crossing_threshold_rescores_waiting_entries
        """
        world = _scrutiny_world(api, 7721)

        before_guest = FX.read_guest(
            api, world["guest_id"], world["guest_headers"]
        )
        assert before_guest["lifetime_refunded_cents"] == 0
        assert before_guest["refund_scrutiny_flag"] is False

        FX.set_clock(api, AFTER_HOLD_TTL)
        FX.sweep_holds(api, world["service_paid_id"])

        guest = FX.read_guest(api, world["guest_id"], world["guest_headers"])
        assert guest["lifetime_refunded_cents"] == 7722
        assert guest["refund_scrutiny_flag"] is True

        rows = FX.ledger_rows(api, world["reservation_id"], world["guest_headers"])
        refunds = [row for row in rows if row["kind"] == "REFUND"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 7722
        assert refunds[0]["memo_code"] == "HOLD_LAPSE"

    def test_the_penalty_rescores_the_waiting_entry_on_another_service(self, api):
        """The entry drops from 1150 to 950 and stays waiting.

        "The `priority_score` is a pure ranking key that never enters a money
        figure."

        Design: Corner/calculations/correct_result_refund_scrutiny_crossing_threshold_rescores_waiting_entries
        """
        world = _scrutiny_world(api, 7721)

        before = FX.read_waitlist_entry(api, world["entry_id"], world["guest_headers"])
        assert before["priority_score"] == 1150
        assert before["priority_penalty_applied"] is False

        FX.set_clock(api, AFTER_HOLD_TTL)
        FX.sweep_holds(api, world["service_paid_id"])

        after = FX.read_waitlist_entry(api, world["entry_id"], world["guest_headers"])
        # The refund landed on the Thursday service; the entry sits on Friday's.
        assert after["service_id"] == world["service_waiting_id"]
        assert after["status"] == "WAITING"
        assert after["offer_round"] == 0
        assert after["priority_penalty_applied"] is True
        # 1000 base plus 150 for three covers, less the 200-point penalty.
        assert after["priority_score"] == 950
        assert C.priority_score(3, priority_penalty_applied=True) == 950
