"""The three collisions PRD §2.7 states explicitly, each on its own endpoint."""

from test_helpers import (
    ALMOND_FLOUR,
    FLOUR_HRW_LIST_ONLY,
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    create_customer,
    create_product,
    create_route,
    create_route_stop_payload,
    create_zone,
    open_order,
    read_customer,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    receive_lot,
    set_clock,
    submit_order,
    validate_error,
)
from test_helpers.fixtures import LP, buyer_headers


def _nut_bakery_with_stock(credit_limit_cents=5000000):
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(
        credit_limit_cents=credit_limit_cents, min_drop_cents=25000
    )
    almond = create_product(ALMOND_FLOUR)
    nut_zone = create_zone(allergen_class="TREE_NUT")
    lot = receive_lot(
        almond["id"],
        nut_zone["id"],
        quantity_received_lb=10000,
        manufactured_on="2026-07-20T00:00:00Z",
    )
    return customer, almond, lot


def _almond_order(customer, almond, quantity_lb=1000, requested_delivery_on="2026-09-15T00:00:00Z"):
    order = open_order(customer, requested_delivery_on=requested_delivery_on)
    line = add_order_line(customer, order["id"], almond["id"], quantity_lb)
    return order, line


class TestStateOutranksAllergenSafety:
    """Priority pair A: an already-priced order that also breaches the program."""

    def _red_tier_provisional_order(self):
        customer, almond, lot = _nut_bakery_with_stock()
        order, line = _almond_order(customer, almond)
        submitted = submit_order(customer, order["id"])
        allocate_order(order["id"])
        return {
            "customer": customer,
            "almond": almond,
            "lot": lot,
            "order": order,
            "order_line": line,
            "submitted": submitted,
        }

    def test_resubmitting_a_priced_red_tier_nut_order_reports_the_state_breach(self):
        """PRD §2.7: "A submit request against an order that is already
        `PROVISIONAL` *and* whose lines breach the customer's allergen program
        returns `ERR_INVALID_STATE_TRANSITION`, not
        `ERR_ALLERGEN_PROGRAM_CONFLICT`, because state legality outranks allergen
        compatibility."

        Design: Difficulty/priority_pair_validation_conflict/pair_a_state_10_beats_business_safety_14_on_resubmit_of_red_tier_tree_nut_order
        """
        scenario = self._red_tier_provisional_order()
        assert scenario["submitted"]["total_cents"] == 903350, (
            f"Expected total 903350, got {scenario['submitted']['total_cents']}"
        )
        assert scenario["submitted"]["pricing_status"] == "PROVISIONAL"
        customer = read_customer(scenario["customer"]["id"])
        assert float(customer["allergen_risk_score"]) == 90.00, (
            f"Expected the score at 90.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "RED", (
            f"Expected RED, got {customer['risk_tier']}"
        )

        response = api_client.submit_order(
            scenario["order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert response.json()["data"]["error_id"] != "ERR_ALLERGEN_PROGRAM_CONFLICT"

    def test_the_refused_resubmission_leaves_both_dimensions_and_the_totals_alone(self):
        """PRD §2.8: "Independently of the declared program, a customer whose
        `risk_tier` has been derived as `RED` may not receive a product whose
        `allergen_class` is `TREE_NUT` or `PEANUT`."

        The losing check is real — the account is `RED` and the line is
        tree-nut — so the refusal must still be a no-op on the order.

        Design: Difficulty/priority_pair_validation_conflict/pair_a_state_10_beats_business_safety_14_on_resubmit_of_red_tier_tree_nut_order
        """
        scenario = self._red_tier_provisional_order()

        api_client.submit_order(scenario["order"]["id"], {}, buyer_headers(scenario["customer"]))

        order = read_order(scenario["order"]["id"])
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {order['pricing_status']}"
        )
        assert order["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {order['fulfillment_status']}"
        )
        assert order["total_cents"] == 903350, (
            f"Expected total 903350, got {order['total_cents']}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 903350


class TestAllergenSafetyOutranksCredit:
    """Priority pair B: a nut line for a RED account that is also over its limit."""

    def _second_nut_order_pending(self):
        customer, almond, lot = _nut_bakery_with_stock(credit_limit_cents=1000000)
        order1, line1 = _almond_order(customer, almond)
        order2, line2 = _almond_order(
            customer, almond, requested_delivery_on="2026-09-16T00:00:00Z"
        )
        submitted = submit_order(customer, order1["id"])
        allocate_order(order1["id"])
        return {
            "customer": customer,
            "almond": almond,
            "order1": order1,
            "order2": order2,
            "order_line2": line2,
            "submitted": submitted,
        }

    def test_submitting_the_second_nut_order_reports_the_allergen_breach(self):
        """PRD §2.7: "An order that both breaches the allergen program *and*
        would exceed the customer's credit limit returns
        `ERR_ALLERGEN_PROGRAM_CONFLICT`, because allergen compatibility outranks
        the fiscal checks."

        Design: Difficulty/priority_pair_validation_conflict/pair_b_business_safety_14_beats_business_fiscal_33_on_red_tier_over_credit_order
        """
        scenario = self._second_nut_order_pending()
        assert scenario["submitted"]["total_cents"] == 903350
        before = read_customer(scenario["customer"]["id"])
        assert before["open_exposure_cents"] == 903350, (
            f"Expected exposure 903350, got {before['open_exposure_cents']}"
        )
        assert before["risk_tier"] == "RED", f"Expected RED, got {before['risk_tier']}"

        response = api_client.submit_order(
            scenario["order2"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_ALLERGEN_PROGRAM_CONFLICT)
        assert response.json()["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"
        assert response.status_code != 402, (
            f"402 is the fiscal status and must not surface here, got {response.status_code}"
        )

    def test_the_losing_credit_check_would_also_have_fired(self):
        """PRD §3.3: "Then the bakery's existing `open_exposure_cents` plus this
        order's computed `total_cents` must be no greater than its
        `credit_limit_cents`; a sum that strictly exceeds the limit is rejected
        with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        903350 already booked plus another 903350 is 1806700 against a limit of
        1000000, so the fiscal gate is genuinely breached and the refusal still
        leaves the second order untouched.

        Design: Difficulty/priority_pair_validation_conflict/pair_b_business_safety_14_beats_business_fiscal_33_on_red_tier_over_credit_order
        """
        scenario = self._second_nut_order_pending()

        api_client.submit_order(
            scenario["order2"]["id"], {}, buyer_headers(scenario["customer"])
        )

        order2 = read_order(scenario["order2"]["id"])
        assert order2["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {order2['pricing_status']}"
        )
        assert order2["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {order2['fulfillment_status']}"
        )
        assert order2["total_cents"] == 0, (
            f"Expected total 0, got {order2['total_cents']}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 903350, (
            f"Expected exposure to stay at 903350, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE", (
            f"Expected the account still ACTIVE, got {customer['status']}"
        )


class TestStopWindowOutranksTrailerCapacity:
    """Priority pair C: an overlapping window on an already-overloaded trailer."""

    def _route_with_one_stop_and_a_second_allocated_order(self):
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
        flour = create_product(FLOUR_HRW_LIST_ONLY)
        zone = create_zone(allergen_class="GLUTEN")
        lot = receive_lot(flour["id"], zone["id"], quantity_received_lb=50000)
        orders = []
        for _ in range(2):
            order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
            add_order_line(customer, order["id"], flour["id"], 15000)
            submitted = submit_order(customer, order["id"])
            allocate_order(order["id"])
            orders.append(submitted)
        route = create_route(
            service_on="2026-09-15T00:00:00Z",
            vehicle_capacity_lb=20000,
            service_buffer_minutes=30,
        )
        stop1 = append_stop(
            route["id"], orders[0]["id"], "2026-09-15T08:00:00Z", "2026-09-15T09:00:00Z"
        )
        return {
            "customer": customer,
            "flour": flour,
            "lot": lot,
            "order1": orders[0],
            "order2": orders[1],
            "route": read_route(route["id"]),
            "stop1": stop1,
        }

    def test_an_overlapping_overweight_stop_reports_the_window_conflict(self):
        """PRD §2.7: "And a route stop that both collides in time with an
        existing stop *and* overflows the trailer returns
        `ERR_STOP_WINDOW_CONFLICT`, because the temporal check outranks the
        capacity check."

        Design: Difficulty/priority_pair_validation_conflict/pair_c_business_temporal_19_beats_business_constraint_26_on_overlapping_overweight_stop
        """
        scenario = self._route_with_one_stop_and_a_second_allocated_order()
        assert scenario["order1"]["total_cents"] == 620267, (
            f"Expected total 620267, got {scenario['order1']['total_cents']}"
        )
        assert scenario["route"]["planned_load_lb"] == 15000, (
            f"Expected planned_load_lb 15000, got {scenario['route']['planned_load_lb']}"
        )
        assert float(scenario["route"]["utilization_pct"]) == 75.00, (
            f"Expected utilization_pct 75.00, got {scenario['route']['utilization_pct']}"
        )

        response = api_client.create_route_stop(
            scenario["route"]["id"],
            create_route_stop_payload(
                scenario["order2"]["id"],
                scenario["route"]["version"],
                window_start_at="2026-09-15T08:30:00Z",
                window_end_at="2026-09-15T09:30:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)
        assert response.json()["data"]["error_id"] != "ERR_ROUTE_CAPACITY_EXCEEDED"

    def test_the_refused_append_leaves_the_load_waterfall_untouched(self):
        """PRD §3.9: "If any pounds remain unplaced after both compartments are
        full, the operation is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP
        409); the same error is raised when `planned_load_lb` would exceed the
        route's `vehicle_capacity_lb`."

        Two 15000 lb drops on a 20000 lb trailer would breach that ceiling as
        well, so the losing check is real; the refusal must nonetheless leave the
        route at one stop and 75.00 percent.

        Design: Difficulty/priority_pair_validation_conflict/pair_c_business_temporal_19_beats_business_constraint_26_on_overlapping_overweight_stop
        """
        scenario = self._route_with_one_stop_and_a_second_allocated_order()

        api_client.create_route_stop(
            scenario["route"]["id"],
            create_route_stop_payload(
                scenario["order2"]["id"],
                scenario["route"]["version"],
                window_start_at="2026-09-15T08:30:00Z",
                window_end_at="2026-09-15T09:30:00Z",
            ),
            LP,
        )

        route = read_route(scenario["route"]["id"])
        assert route["stop_count"] == 1, (
            f"Expected stop_count to stay at 1, got {route['stop_count']}"
        )
        assert route["planned_load_lb"] == 15000, (
            f"Expected planned_load_lb 15000, got {route['planned_load_lb']}"
        )
        assert float(route["utilization_pct"]) == 75.00, (
            f"Expected utilization_pct 75.00, got {route['utilization_pct']}"
        )
        assert route["version"] == scenario["route"]["version"], (
            f"Expected the route version unchanged, got {route['version']}"
        )
        assert read_order(scenario["order2"]["id"])["fulfillment_status"] == "ALLOCATED", (
            "The refused order must stay ALLOCATED rather than advancing to ROUTED"
        )
        assert read_route_stop(scenario["stop1"]["id"])["status"] == "PLANNED"
