"""Boundaries resolved to the exact unit the PRD names.

One rule pins a temporal boundary to the second on the same order; the other
pins a capacity boundary to a single logistics unit on the same route.
"""

from test_helpers import (
    ApiErrorId,
    LOGISTICS,
    api_client,
    assert_instant,
    assert_route_capacity_identity,
    book_appointment,
    create_customer_row,
    create_model,
    get_success_data,
    open_return_case,
    pickup_appointment_payload,
    read_order,
    read_return_case,
    read_route,
    return_case_payload,
    set_clock,
    setup_delivered_order,
    setup_published_route,
    validate_error,
)


class TestBreakInWindowIsInclusiveToTheSecond:
    """The same order refused at 23:59:59 and accepted one second later."""

    def _delivered_order(self):
        return setup_delivered_order(
            model_overrides={
                "sku": "MDL-Q-MED-B",
                "list_price_cents": 120000,
                "break_in_nights": 21,
                "trial_nights": 100,
            },
            customer_overrides={
                "email": "bp1@example.com",
                "full_name": "Bea Boundary",
                "household_hash": "HH-BP1",
            },
        )

    def test_delivery_pins_both_trial_window_boundaries(self):
        """PRD §3.3: "It computes `break_in_ends_at` as `delivered_at` plus the model's `break_in_nights` in days, and `trial_ends_at` as `delivered_at` plus the model's `trial_nights` in days."

        Delivery on 2026-08-01 with a 21-night break-in and a 100-night trial
        puts the two boundaries at 2026-08-22T00:00:00Z and
        2026-11-09T00:00:00Z.

        Design: Difficulty/boundary_precision_check/break_in_window_inclusive_to_the_second_on_return_case_creation
        """
        scenario = self._delivered_order()
        order = scenario["order"]

        assert_instant(order["delivered_at"], "2026-08-01T00:00:00Z", "delivered_at")
        assert_instant(order["break_in_ends_at"], "2026-08-22T00:00:00Z", "break_in_ends_at")
        assert_instant(order["trial_ends_at"], "2026-11-09T00:00:00Z", "trial_ends_at")

    def test_one_second_before_the_boundary_the_return_is_refused(self):
        """PRD §3.6: "The break-in window is the heart of the trial promise, and it is enforced here: the logical clock must have reached `break_in_ends_at`, with the boundary inclusive so a return opened at exactly that instant is accepted."

        At 2026-08-21T23:59:59Z the clock has not reached
        `break_in_ends_at`, so the request is refused and nothing on the order
        moves — its version is unchanged and the trial axis is still BREAK_IN.

        Design: Difficulty/boundary_precision_check/break_in_window_inclusive_to_the_second_on_return_case_creation
        """
        scenario = self._delivered_order()
        order = scenario["order"]

        set_clock("2026-08-21T23:59:59Z")
        response = api_client.create_return_case(
            return_case_payload(order["id"], "COMFORT"), scenario["customer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_BREAK_IN_NOT_ELAPSED)

        reloaded = read_order(order["id"])
        assert reloaded["version"] == order["version"], (
            "a refused return request may not bump the order's version"
        )
        assert reloaded["trial_status"] == "BREAK_IN"

    def test_exactly_at_the_boundary_the_return_is_accepted(self):
        """PRD §3.6: "The server stamps `requested_at` from the logical clock and opens the case with `logistics_status` `REQUESTED`, `financial_status` `PENDING`, `disposition` `PENDING`, and `nights_used` null — nothing is priced until the mattress has actually been collected and graded."

        One second later the clock is exactly at 2026-08-22T00:00:00Z and the
        inclusive boundary admits the return, moving the order's trial axis to
        RETURN_REQUESTED.

        Design: Difficulty/boundary_precision_check/break_in_window_inclusive_to_the_second_on_return_case_creation
        """
        scenario = self._delivered_order()
        order = scenario["order"]

        set_clock("2026-08-21T23:59:59Z")
        api_client.create_return_case(
            return_case_payload(order["id"], "COMFORT"), scenario["customer_headers"]
        )
        set_clock("2026-08-22T00:00:00Z")
        case = get_success_data(
            api_client.create_return_case(
                return_case_payload(order["id"], "COMFORT"), scenario["customer_headers"]
            ),
            expected_status=201,
        )

        assert case["logistics_status"] == "REQUESTED"
        assert case["financial_status"] == "PENDING"
        assert case["nights_used"] is None
        assert_instant(case["requested_at"], "2026-08-22T00:00:00Z", "requested_at")
        assert read_order(order["id"])["trial_status"] == "RETURN_REQUESTED"


class TestRouteCapacityAllowsExactEqualityAndRejectsOneUnitOver:
    """A five-unit truck already carrying four units of QUEEN bookings."""

    def _route_with_four_units_booked(self):
        queen = create_model(
            sku="MDL-Q-CAP", firmness="MEDIUM", size="QUEEN", list_price_cents=120000
        )
        twin = create_model(
            sku="MDL-T-CAP", firmness="MEDIUM", size="TWIN", list_price_cents=70000
        )
        cases = []
        for index, model in enumerate((queen, queen, queen, twin), start=1):
            customer = create_customer_row(
                email=f"cap{index}@example.com", household_hash=f"HH-CAP{index}"
            )
            scenario = setup_delivered_order(model=model, customer=customer)
            cases.append(scenario)

        set_clock("2026-09-10T00:00:00Z")
        for scenario in cases:
            scenario["return_case"] = open_return_case(
                scenario["order"]["id"], scenario["customer_headers"]
            )

        route = setup_published_route(capacity_units=5)
        appointment_one = book_appointment(
            route["id"],
            cases[0]["return_case"]["id"],
            slot_start_at="2026-09-15T09:00:00Z",
            slot_end_at="2026-09-15T10:00:00Z",
        )
        appointment_two = book_appointment(
            route["id"],
            cases[1]["return_case"]["id"],
            slot_start_at="2026-09-15T11:00:00Z",
            slot_end_at="2026-09-15T12:00:00Z",
        )
        return {
            "route": read_route(route["id"]),
            "cases": cases,
            "appointment_one": appointment_one,
            "appointment_two": appointment_two,
        }

    def test_a_booking_that_would_exceed_the_capacity_by_one_unit_is_refused(self):
        """PRD §3.7: "Third, the route's capacity must accommodate the booking: the route's current `booked_units` plus the new slot's `units` may not exceed `capacity_units`."

        Two QUEEN collections consume two units each, so a third QUEEN slot would
        take the truck to six units against a capacity of five; the refusal
        leaves the route ledger and its version exactly where they were and the
        third return case still in REQUESTED.

        Design: Difficulty/boundary_precision_check/route_capacity_allows_exact_equality_and_rejects_one_unit_over
        """
        fixture = self._route_with_four_units_booked()
        route = fixture["route"]

        assert fixture["appointment_one"]["units"] == 2
        assert fixture["appointment_two"]["units"] == 2

        response = api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                fixture["cases"][2]["return_case"]["id"],
                route["version"],
                slot_start_at="2026-09-15T13:00:00Z",
                slot_end_at="2026-09-15T14:00:00Z",
            ),
            LOGISTICS,
        )
        validate_error(response, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)

        assert (
            read_return_case(fixture["cases"][2]["return_case"]["id"])["logistics_status"]
            == "REQUESTED"
        )
        reloaded = read_route(route["id"])
        assert reloaded["booked_units"] == 4
        assert reloaded["available_units"] == 1
        assert reloaded["version"] == route["version"]

    def test_filling_the_truck_to_exactly_its_capacity_is_allowed(self):
        """PRD §3.7: "Exact equality is allowed — a truck may be filled precisely to the brim — and only strictly exceeding it is refused, with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        A TWIN collection is a single unit, so booking it against the same
        unchanged route version takes the truck from four units to exactly its
        five-unit capacity and leaves no headroom.

        Design: Difficulty/boundary_precision_check/route_capacity_allows_exact_equality_and_rejects_one_unit_over
        """
        fixture = self._route_with_four_units_booked()
        route = fixture["route"]

        api_client.create_pickup_appointment(
            pickup_appointment_payload(
                route["id"],
                fixture["cases"][2]["return_case"]["id"],
                route["version"],
                slot_start_at="2026-09-15T13:00:00Z",
                slot_end_at="2026-09-15T14:00:00Z",
            ),
            LOGISTICS,
        )
        appointment = get_success_data(
            api_client.create_pickup_appointment(
                pickup_appointment_payload(
                    route["id"],
                    fixture["cases"][3]["return_case"]["id"],
                    route["version"],
                    slot_start_at="2026-09-15T15:00:00Z",
                    slot_end_at="2026-09-15T16:00:00Z",
                ),
                LOGISTICS,
            ),
            expected_status=201,
        )

        assert appointment["units"] == 1, (
            f"a TWIN collection is one logistics unit, got {appointment['units']}"
        )
        assert appointment["status"] == "BOOKED"

        reloaded = read_route(route["id"])
        assert reloaded["booked_units"] == 5
        assert reloaded["available_units"] == 0
        assert_route_capacity_identity(reloaded)
        assert (
            read_return_case(fixture["cases"][3]["return_case"]["id"])["logistics_status"]
            == "PICKUP_SCHEDULED"
        )
