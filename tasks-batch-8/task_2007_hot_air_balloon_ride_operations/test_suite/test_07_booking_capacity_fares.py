"""Booking rules: fare quotes (shared combinatorial, charter, weight
surcharge), capacity guards, payment exactness at CONFIRM, and seat-inventory
conservation (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_seat_inventory,
    book_reservation,
    confirm_reservation,
    create_customer,
    create_confirmed_booking,
    customer_cancel,
    get_flight,
    get_reservation,
    make_customer_headers,
    set_clock,
    setup_scheduled_flight,
    validate_error,
    validate_success,
)


class TestFareQuoteShared:
    def test_fare_quote_shared_peak_combinatorial(self, api):
        """PRD §3.4: "The per-person base fare is 39900 cents during `PEAK`
        season and 29900 cents during `REGULAR` season. When the party's average
        weight per person is strictly greater than 200 pounds, a weight
        surcharge of 2500 cents per person applies; at exactly 200 pounds or
        below there is no surcharge. The fare is `party_size` times the sum of
        the base and any surcharge, plus the photo add-on."
        PRD §3.4: "Zero cents for `NONE`, 4900 cents for `STANDARD`, and 9900
        cents for `DELUXE`, identical for both kinds."

        Design: Difficulty/combinatorial_formula/fare_quote_shared_combinatorial
        """
        ctx = setup_scheduled_flight(
            flight_kw={
                "scheduled_date": "2026-10-05",
                "dawn_window_start": "2026-10-05T05:30:00Z",
                "dawn_window_end": "2026-10-05T07:00:00Z",
            }
        )
        assert ctx["flight"]["season_tier"] == "PEAK", (
            "2026-10-05 falls within the October 1-14 Balloon Fiesta window"
        )
        _, reservation = book_reservation(
            ctx["flight"], party_size=2, declared_weight_lbs=500,
            photo_package_tier="DELUXE",
        )
        # avg 250 > 200 -> 2 * (39900 + 2500) + 9900 = 94700
        assert reservation["quoted_fare_cents"] == 94700, (
            f"PEAK party of 2 over the weight threshold with DELUXE photos must "
            f"quote 94700, got {reservation['quoted_fare_cents']}"
        )

    def test_fare_quote_shared_factor_isolation(self, api):
        """PRD §3.4: "When the party's average weight per person is strictly
        greater than 200 pounds, a weight surcharge of 2500 cents per person
        applies; at exactly 200 pounds or below there is no surcharge. The fare
        is `party_size` times the sum of the base and any surcharge, plus the
        photo add-on."

        Design: Difficulty/combinatorial_formula/fare_quote_shared_combinatorial
        """
        ctx = setup_scheduled_flight(
            flight_kw={
                "scheduled_date": "2026-10-05",
                "dawn_window_start": "2026-10-05T05:30:00Z",
                "dawn_window_end": "2026-10-05T07:00:00Z",
            }
        )
        flight = ctx["flight"]
        # Same season/party/weight as the DELUXE booking, but no photo add-on.
        _, r_no_photo = book_reservation(
            flight, party_size=2, declared_weight_lbs=500, photo_package_tier="NONE"
        )
        # Same season/party with DELUXE but avg exactly 200 -> no surcharge.
        _, r_no_surcharge = book_reservation(
            flight, party_size=2, declared_weight_lbs=400, photo_package_tier="DELUXE"
        )
        assert r_no_photo["quoted_fare_cents"] == 84800, "2 * (39900 + 2500) + 0"
        assert r_no_surcharge["quoted_fare_cents"] == 89700, "2 * 39900 + 9900"


class TestFareQuoteCharter:
    def test_fare_quote_charter_peak_multiplier(self, api):
        """PRD §3.4: "The flat charter fare is keyed on the balloon's
        `basket_capacity_passengers`: 120000 cents when the capacity is 4 or
        fewer, 180000 cents when it is 5 through 8, and 250000 cents when it is
        9 or more. During `PEAK` season the flat fare is multiplied by 1.25 with
        the result rounded half-up to the nearest cent; during `REGULAR` season
        the flat fare stands as-is. The photo add-on is then added."

        Design: Corner/calculations/fare_quote_charter_peak_multiplier
        """
        ctx = setup_scheduled_flight(
            flight_kw={
                "kind": "CHARTER",
                "scheduled_date": "2026-10-03",
                "dawn_window_start": "2026-10-03T05:30:00Z",
                "dawn_window_end": "2026-10-03T07:00:00Z",
            }
        )
        _, reservation = book_reservation(
            ctx["flight"], party_size=4, declared_weight_lbs=560,
            photo_package_tier="STANDARD",
        )
        # capacity 6 -> 180000 flat; PEAK x1.25 -> 225000; + STANDARD 4900.
        assert reservation["quoted_fare_cents"] == 229900, (
            f"CHARTER PEAK capacity-6 flat with STANDARD photos must quote "
            f"229900, got {reservation['quoted_fare_cents']}"
        )


class TestWeightSurchargeBoundary:
    def test_weight_surcharge_boundary_avg_exactly_200(self, api):
        """PRD §3.4: "When the party's average weight per person is strictly
        greater than 200 pounds, a weight surcharge of 2500 cents per person
        applies; at exactly 200 pounds or below there is no surcharge."

        Design: Corner/calculations/weight_surcharge_boundary_avg_exactly_200
        """
        ctx = setup_scheduled_flight()
        flight = ctx["flight"]
        _, r_low = book_reservation(flight, party_size=2, declared_weight_lbs=400)
        _, r_high = book_reservation(flight, party_size=2, declared_weight_lbs=402)
        assert r_low["quoted_fare_cents"] == 59800, (
            "avg exactly 200 lbs -> no surcharge -> 2 * 29900"
        )
        assert r_high["quoted_fare_cents"] == 64800, (
            "avg 201 lbs -> surcharge applies -> 2 * (29900 + 2500)"
        )


class TestBookingCapacityRules:
    def test_basket_capacity_exceeded_on_shared_booking(self, api):
        """PRD §3.4: "Second, seats: on a `SHARED` flight, the flight's
        `seats_sold` plus the new `party_size` must not exceed the balloon's
        `basket_capacity_passengers`, else `ERR_BASKET_CAPACITY_EXCEEDED`
        (HTTP 422); on a `CHARTER` flight the whole basket is exclusive — at
        most one non-cancelled reservation may exist, and its `party_size` must
        still fit within `basket_capacity_passengers` — so a second booking, or
        an oversized charter party, is rejected with `ERR_CHARTER_EXCLUSIVE`
        (HTTP 409)."

        Design: Corner/validations/basket_capacity_exceeded_on_shared_booking
        """
        ctx = setup_scheduled_flight(
            balloon_kw={
                "basket_capacity_passengers": 4,
                "max_gross_weight_lbs": 2000,
                "empty_weight_lbs": 500,
            }
        )
        customer = create_customer()
        book_reservation(ctx["flight"], customer, party_size=2, declared_weight_lbs=360)
        resp = api.create_reservation(
            ctx["flight"]["id"],
            {
                "customer_id": customer["id"],
                "party_size": 3,
                "declared_weight_lbs": 540,
                "photo_package_tier": "NONE",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BASKET_CAPACITY_EXCEEDED)

    def test_charter_flight_rejects_second_reservation(self, api):
        """PRD §3.4: "Second, seats: on a `SHARED` flight, the flight's
        `seats_sold` plus the new `party_size` must not exceed the balloon's
        `basket_capacity_passengers`, else `ERR_BASKET_CAPACITY_EXCEEDED`
        (HTTP 422); on a `CHARTER` flight the whole basket is exclusive — at
        most one non-cancelled reservation may exist, and its `party_size` must
        still fit within `basket_capacity_passengers` — so a second booking, or
        an oversized charter party, is rejected with `ERR_CHARTER_EXCLUSIVE`
        (HTTP 409)."

        Design: Corner/validations/charter_flight_rejects_second_reservation
        """
        ctx = setup_scheduled_flight(flight_kw={"kind": "CHARTER"})
        customer = create_customer()
        book_reservation(ctx["flight"], customer, party_size=2, declared_weight_lbs=360)
        resp = api.create_reservation(
            ctx["flight"]["id"],
            {
                "customer_id": customer["id"],
                "party_size": 1,
                "declared_weight_lbs": 180,
                "photo_package_tier": "NONE",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CHARTER_EXCLUSIVE)

    def test_payload_exceeded_at_booking_declared_weight(self, api):
        """PRD §3.4: "First, weight-and-balance: the declared party weight plus
        the balloon's `empty_weight_lbs` plus the flight's `fuel_lbs` must not
        exceed the balloon's `max_gross_weight_lbs`; a violation is rejected
        with `ERR_PAYLOAD_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/payload_exceeded_at_booking_declared_weight
        """
        # empty 500 + fuel 200 -> declared budget exactly 300 lbs.
        ctx = setup_scheduled_flight(
            balloon_kw={
                "basket_capacity_passengers": 4,
                "max_gross_weight_lbs": 1000,
                "empty_weight_lbs": 500,
            }
        )
        customer = create_customer()
        ok = api.create_reservation(
            ctx["flight"]["id"],
            {
                "customer_id": customer["id"],
                "party_size": 2,
                "declared_weight_lbs": 300,
                "photo_package_tier": "NONE",
            },
            make_customer_headers(customer["id"]),
        )
        validate_success(ok, expected_status=201)  # 500 + 200 + 300 == 1000, at max

        resp = api.create_reservation(
            ctx["flight"]["id"],
            {
                "customer_id": customer["id"],
                "party_size": 2,
                "declared_weight_lbs": 301,
                "photo_package_tier": "NONE",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYLOAD_EXCEEDED)


class TestConfirmPaymentExactness:
    def test_confirm_with_wrong_payment_amount(self, api):
        """PRD §3.4: "Payment is exact. The customer confirms a `PENDING`
        reservation by paying exactly the quoted fare: the confirming event's
        `paid_cents` must equal `quoted_fare_cents` to the cent, and any
        mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402)."

        Design: Corner/validations/confirm_with_wrong_payment_amount
        """
        ctx = setup_scheduled_flight()
        customer, reservation = book_reservation(
            ctx["flight"], party_size=1, declared_weight_lbs=180
        )
        assert reservation["quoted_fare_cents"] == 29900
        resp = api.reservation_event(
            reservation["id"],
            {"event_type": "CONFIRM", "paid_cents": 29901},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        after = get_reservation(reservation["id"])
        assert after["booking_status"] == "PENDING"
        assert after["payment_status"] == "UNPAID"
        assert after["paid_cents"] == 0


class TestSeatInventoryConservation:
    def test_seats_returned_after_cancellation(self, api, ops_headers):
        """PRD §3.4: "The flight's `seats_sold` is the sum of `party_size` over
        its reservations whose `booking_status` is `PENDING`, `CONFIRMED`,
        `CHECKED_IN`, `FLOWN`, or `COMPLETED`, and `seats_available` is the
        balloon's `basket_capacity_passengers` minus `seats_sold`."
        PRD §3.5/§3.7: a cancelled reservation leaves that set, so "Either way
        the flight's payload and seat figures are recomputed."

        Design: Difficulty/compensating_invariant/seat_inventory_conserved_across_book_and_cancel
        """
        ctx = setup_scheduled_flight()
        balloon = ctx["balloon"]
        flight = ctx["flight"]
        customer, reservation = create_confirmed_booking(
            flight, party_size=2, declared_weight_lbs=360
        )
        mid = get_flight(flight["id"])
        assert mid["seats_sold"] == 2 and mid["seats_available"] == 4
        assert_seat_inventory(mid, balloon)

        set_clock("2026-08-08T00:00:00Z")  # >24h before the dawn window
        customer_cancel(reservation, customer)

        after = get_flight(flight["id"])
        assert after["seats_sold"] == 0, "cancelled seats return to inventory"
        assert after["seats_available"] == 6
        assert_seat_inventory(after, balloon)

    def test_seat_invariant_holds_across_booking_steps(self, api, ops_headers):
        """PRD §3.4: "The flight's `seats_sold` is the sum of `party_size` over
        its reservations whose `booking_status` is `PENDING`, `CONFIRMED`,
        `CHECKED_IN`, `FLOWN`, or `COMPLETED`, and `seats_available` is the
        balloon's `basket_capacity_passengers` minus `seats_sold`."

        Design: Difficulty/compensating_invariant/seat_inventory_conserved_across_book_and_cancel
        """
        ctx = setup_scheduled_flight()
        balloon = ctx["balloon"]
        flight = ctx["flight"]

        start = get_flight(flight["id"])
        assert start["seats_sold"] == 0 and start["seats_available"] == 6

        # A PENDING booking already counts against the inventory.
        customer, r1 = book_reservation(flight, party_size=2, declared_weight_lbs=360)
        after_book = get_flight(flight["id"])
        assert after_book["seats_sold"] == 2, "PENDING reservations consume seats"
        assert after_book["seats_available"] == 4
        assert_seat_inventory(after_book, balloon)

        # Confirming does not change the count.
        confirm_reservation(r1, customer)
        after_confirm = get_flight(flight["id"])
        assert after_confirm["seats_sold"] == 2
        assert after_confirm["seats_available"] == 4
        assert_seat_inventory(after_confirm, balloon)

        # A second booking accumulates.
        book_reservation(flight, customer, party_size=1, declared_weight_lbs=180)
        after_second = get_flight(flight["id"])
        assert after_second["seats_sold"] == 3
        assert after_second["seats_available"] == 3
        assert_seat_inventory(after_second, balloon)
