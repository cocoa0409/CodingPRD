"""Inclusive boundaries on four different metrics (PRD §3.3, §3.5, §3.9, §3.11)."""

from test_helpers import (
    EMULSIFIER,
    FLOUR_HRW_LIST_ONLY,
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    create_customer,
    create_product,
    create_route,
    create_zone,
    log_hours,
    open_engagement,
    open_order,
    read_customer,
    read_engagement,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    receive_lot,
    seal_route,
    set_clock,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import WO, buyer_headers

YEAST_CREAM_SHORT_SHELF = {
    "sku": "YST-CRM-01",
    "category": "LEAVENING",
    "allergen_class": "NONE",
    "bulk_capable": False,
    "shelf_life_days": 90,
    "index_code": "NONE",
    "list_price_cents_per_lb": 310,
    "min_rotation_days": 30,
}


class TestMinimumDropBoundary:
    """A total exactly on the floor passes; 497 cents below it does not."""

    def _two_emulsifier_orders(self):
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer(credit_limit_cents=2000000, min_drop_cents=497350)
        emulsifier = create_product(EMULSIFIER)
        order1 = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        add_order_line(customer, order1["id"], emulsifier["id"], 1000)
        order2 = open_order(customer, requested_delivery_on="2026-09-16T00:00:00Z")
        line2 = add_order_line(customer, order2["id"], emulsifier["id"], 999)
        return {
            "customer": customer,
            "emulsifier": emulsifier,
            "order1": order1,
            "order2": order2,
            "order_line2": line2,
        }

    def test_a_total_exactly_equal_to_the_drop_floor_is_accepted(self):
        """PRD §3.3: "The order's computed `total_cents` must reach the bakery's
        `min_drop_cents`; a total exactly equal to the floor passes, and a total
        strictly below it is rejected with `ERR_MIN_DROP_NOT_MET` (HTTP 422)."

        1000 lb of emulsifier at 490 cents earns no quantity discount, so the
        subtotal is 490000, the surcharge 12250, and the 502250 cent rebate base
        earns one percent of the subtotal — 4900 — for a total of 497350.

        Design: Difficulty/boundary_precision_check/boundary_min_drop_total_exactly_equal_passes_one_cent_below_fails
        """
        scenario = self._two_emulsifier_orders()

        submitted = validate_success(
            api_client.submit_order(
                scenario["order1"]["id"], {}, buyer_headers(scenario["customer"])
            )
        )

        assert submitted["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {submitted['pricing_status']}"
        )
        assert submitted["subtotal_cents"] == 490000, (
            f"Expected subtotal 490000, got {submitted['subtotal_cents']}"
        )
        assert submitted["fuel_surcharge_cents"] == 12250, (
            f"Expected surcharge 12250, got {submitted['fuel_surcharge_cents']}"
        )
        assert submitted["volume_rebate_cents"] == 4900, (
            f"Expected rebate 4900, got {submitted['volume_rebate_cents']}"
        )
        assert submitted["total_cents"] == 497350, (
            f"Expected total 497350, got {submitted['total_cents']}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 497350

    def test_a_total_one_pound_short_of_the_floor_is_refused(self):
        """PRD §2.5: "Where a monetary quantity is derived from a percentage or a
        fractional multiplier, the result is rounded to a whole number of cents
        using round-half-up: a computed value whose fractional part is exactly one
        half rounds away from zero."

        999 lb gives 489510 plus 12238 less 4895, which is 496853 — 497 cents
        below the same floor — so the submission is refused.

        Design: Difficulty/boundary_precision_check/boundary_min_drop_total_exactly_equal_passes_one_cent_below_fails
        """
        scenario = self._two_emulsifier_orders()

        response = api_client.submit_order(
            scenario["order2"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_MIN_DROP_NOT_MET)
        order2 = read_order(scenario["order2"]["id"])
        assert order2["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {order2['pricing_status']}"
        )
        assert order2["total_cents"] == 0, (
            f"Expected total 0, got {order2['total_cents']}"
        )
        assert read_order_line(scenario["order_line2"]["id"])["extended_cents"] == 0


class TestRotationEligibilityBoundary:
    """Remaining shelf life exactly on `min_rotation_days` still qualifies."""

    def _two_yeast_lots_and_two_orders(self):
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
        yeast = create_product(YEAST_CREAM_SHORT_SHELF)
        zone = create_zone(allergen_class="NONE")
        lot_a = receive_lot(
            yeast["id"],
            zone["id"],
            manufactured_on="2026-06-06T00:00:00Z",
            quantity_received_lb=5000,
        )
        lot_b = receive_lot(
            yeast["id"],
            zone["id"],
            manufactured_on="2026-06-05T00:00:00Z",
            quantity_received_lb=9000,
        )
        order1 = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        line1 = add_order_line(customer, order1["id"], yeast["id"], 1500)
        submitted1 = submit_order(customer, order1["id"])
        order2 = open_order(customer, requested_delivery_on="2026-09-16T00:00:00Z")
        line2 = add_order_line(customer, order2["id"], yeast["id"], 6000)
        submitted2 = submit_order(customer, order2["id"])
        return {
            "customer": customer,
            "yeast": yeast,
            "lot_a": lot_a,
            "lot_b": lot_b,
            "order1": submitted1,
            "order_line1": line1,
            "order2": submitted2,
            "order_line2": line2,
        }

    def test_the_selector_skips_the_earlier_expiring_but_ineligible_lot(self):
        """PRD §3.5: "the number of whole UTC days from the logical clock date to
        the lot's `expires_on` is at least the product's `min_rotation_days`".

        The lot expiring 2026-09-04 sits exactly 30 days out and qualifies; the
        lot expiring 2026-09-03 is 29 days out and does not, so plain
        First-Expired-First-Out would have picked the wrong lot.

        Design: Difficulty/boundary_precision_check/boundary_rotation_eligibility_exactly_min_rotation_days_then_empty_candidate_set
        """
        scenario = self._two_yeast_lots_and_two_orders()
        assert scenario["order1"]["total_cents"] == 476625, (
            f"Expected total 476625, got {scenario['order1']['total_cents']}"
        )

        allocated = allocate_order(scenario["order1"]["id"])

        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
        line = read_order_line(scenario["order_line1"]["id"])
        assert line["lot_id"] == scenario["lot_a"]["id"], (
            f"Expected the 2026-09-04 lot, got {line['lot_id']}"
        )
        assert line["allocation_status"] == "RESERVED"
        lot_a = read_lot(scenario["lot_a"]["id"])
        assert lot_a["quantity_on_hand_lb"] == 3500, (
            f"Expected 3500 lb left on hand, got {lot_a['quantity_on_hand_lb']}"
        )
        assert lot_a["quantity_reserved_lb"] == 1500
        lot_b = read_lot(scenario["lot_b"]["id"])
        assert lot_b["quantity_on_hand_lb"] == 9000, (
            f"Expected the ineligible lot untouched, got {lot_b['quantity_on_hand_lb']}"
        )
        assert lot_b["quantity_reserved_lb"] == 0

    def test_an_empty_candidate_set_refuses_the_second_allocation(self):
        """PRD §3.5: "If the candidate set is empty for any line, the operation is
        rejected with `ERR_NO_ELIGIBLE_LOT` (HTTP 409)."

        After the first pick the eligible lot holds 3500 lb against a 6000 lb
        line, and the 9000 lb lot is still outside its rotation floor, so nothing
        can cover the line on its own.

        Design: Difficulty/boundary_precision_check/boundary_rotation_eligibility_exactly_min_rotation_days_then_empty_candidate_set
        """
        scenario = self._two_yeast_lots_and_two_orders()
        assert scenario["order2"]["total_cents"] == 1832100, (
            f"Expected total 1832100, got {scenario['order2']['total_cents']}"
        )
        allocate_order(scenario["order1"]["id"])

        response = api_client.allocate_order(scenario["order2"]["id"], {}, WO)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOT)
        order2 = read_order(scenario["order2"]["id"])
        assert order2["fulfillment_status"] == "NEW", (
            f"Expected the order to stay NEW, got {order2['fulfillment_status']}"
        )
        line2 = read_order_line(scenario["order_line2"]["id"])
        assert line2["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {line2['allocation_status']}"
        )
        assert line2["lot_id"] is None, f"Expected no lot bound, got {line2['lot_id']}"


class TestFullTrailerUtilizationBoundary:
    """A trailer filled to exactly 100.00 percent is still sealable."""

    def _route_loaded_to_capacity(self):
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
        flour = create_product(FLOUR_HRW_LIST_ONLY)
        zone = create_zone(allergen_class="GLUTEN")
        lot = receive_lot(flour["id"], zone["id"], quantity_received_lb=50000)
        order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        line = add_order_line(customer, order["id"], flour["id"], 20000)
        submitted = submit_order(customer, order["id"])
        allocate_order(order["id"])
        route = create_route(
            service_on="2026-09-15T00:00:00Z",
            vehicle_capacity_lb=20000,
            service_buffer_minutes=30,
        )
        stop = append_stop(
            route["id"], order["id"], "2026-09-15T08:00:00Z", "2026-09-15T10:00:00Z"
        )
        return {
            "customer": customer,
            "flour": flour,
            "lot": lot,
            "order": submitted,
            "order_line": line,
            "route": read_route(route["id"]),
            "route_stop": stop,
        }

    def test_a_trailer_at_exactly_one_hundred_percent_seals(self):
        """PRD §3.9: "`utilization_pct` is no greater than 100, with exactly
        100.00 permitted to seal".

        PRD §3.9: "Finally `utilization_pct` is the planned load divided by the
        vehicle capacity, multiplied by one hundred, and rounded half-up to two
        decimal places."

        Design: Difficulty/boundary_precision_check/boundary_route_utilization_exactly_one_hundred_percent_still_seals
        """
        scenario = self._route_loaded_to_capacity()
        assert scenario["order"]["total_cents"] == 827022, (
            f"Expected total 827022, got {scenario['order']['total_cents']}"
        )
        assert scenario["route"]["planned_load_lb"] == 20000, (
            f"Expected planned_load_lb 20000, got {scenario['route']['planned_load_lb']}"
        )
        assert float(scenario["route"]["utilization_pct"]) == 100.00, (
            f"Expected utilization_pct 100.00, got {scenario['route']['utilization_pct']}"
        )

        sealed = seal_route(scenario["route"]["id"])

        assert sealed["status"] == "SEALED", f"Expected SEALED, got {sealed['status']}"
        assert float(sealed["utilization_pct"]) == 100.00, (
            f"Expected utilization_pct still 100.00, got {sealed['utilization_pct']}"
        )
        assert sealed["stop_count"] == 1, (
            f"Expected stop_count 1, got {sealed['stop_count']}"
        )
        assert sealed["allergen_class_lock"] == "GLUTEN", (
            f"Expected the trailer locked to GLUTEN, got {sealed['allergen_class_lock']}"
        )

    def test_sealing_the_full_trailer_assigns_the_one_based_sequence_number(self):
        """PRD §3.9: "Sealing assigns each stop's `sequence_no` as a one-based
        position ordered by `window_start_at` ascending then `created_at`
        ascending, and increments the route's `version` by 1."

        Design: Difficulty/boundary_precision_check/boundary_route_utilization_exactly_one_hundred_percent_still_seals
        """
        scenario = self._route_loaded_to_capacity()
        assert scenario["route_stop"]["sequence_no"] == 0, (
            f"A new stop begins at sequence_no 0, got {scenario['route_stop']['sequence_no']}"
        )

        seal_route(scenario["route"]["id"])

        stop = read_route_stop(scenario["route_stop"]["id"])
        assert stop["sequence_no"] == 1, (
            f"Expected sequence_no 1, got {stop['sequence_no']}"
        )
        assert stop["status"] == "PLANNED", (
            f"Expected the stop still PLANNED, got {stop['status']}"
        )
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "ROUTED", (
            "Sealing does not itself advance the order past ROUTED"
        )


class TestBillableHoursBoundary:
    """Bench hours reach the qualifying threshold by accumulation."""

    def _open_engagement_for_a_green_bakery(self):
        set_clock("2026-08-05T00:00:00Z")
        customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
        emulsifier = create_product(EMULSIFIER)
        engagement = open_engagement(customer, emulsifier["id"], specialist_user_id="ts-1")
        return {"customer": customer, "product": emulsifier, "engagement": engagement}

    def test_three_point_nine_hours_leaves_the_engagement_open_and_unbilled(self):
        """PRD §3.11: "The first four hours are the qualifying threshold — the
        moment `hours_logged` reaches 4.0, the boundary being inclusive, an `OPEN`
        engagement moves itself to `BILLABLE` and the attach fee is computed."

        Design: Difficulty/boundary_precision_check/boundary_tech_hours_exactly_four_point_zero_flips_open_to_billable
        """
        scenario = self._open_engagement_for_a_green_bakery()
        assert scenario["engagement"]["status"] == "OPEN"
        assert float(scenario["engagement"]["hours_logged"]) == 0.0
        assert scenario["engagement"]["attach_fee_cents"] == 0

        first = log_hours(scenario["engagement"]["id"], 2.0, specialist_user_id="ts-1")
        assert float(first["hours_logged"]) == 2.0, (
            f"Expected hours_logged 2.0, got {first['hours_logged']}"
        )
        assert first["status"] == "OPEN", f"Expected OPEN, got {first['status']}"
        assert first["attach_fee_cents"] == 0

        second = log_hours(scenario["engagement"]["id"], 1.9, specialist_user_id="ts-1")

        assert float(second["hours_logged"]) == 3.9, (
            f"Expected hours_logged 3.9, got {second['hours_logged']}"
        )
        assert second["status"] == "OPEN", (
            f"Expected the engagement still OPEN one tenth short, got {second['status']}"
        )
        assert second["attach_fee_cents"] == 0, (
            f"Expected attach_fee_cents 0, got {second['attach_fee_cents']}"
        )

    def test_the_posting_that_lands_on_four_point_zero_flips_and_prices_the_fee(self):
        """PRD §3.11: "The first two logged hours are included at no charge, so
        billable hours are `hours_logged` less two, floored at zero."

        Two billable hours at 18500 cents give 37000 cents, and a `GREEN` account
        carries a multiplier of one.

        Design: Difficulty/boundary_precision_check/boundary_tech_hours_exactly_four_point_zero_flips_open_to_billable
        """
        scenario = self._open_engagement_for_a_green_bakery()
        assert read_customer(scenario["customer"]["id"])["risk_tier"] == "GREEN"
        log_hours(scenario["engagement"]["id"], 2.0, specialist_user_id="ts-1")
        log_hours(scenario["engagement"]["id"], 1.9, specialist_user_id="ts-1")

        third = log_hours(scenario["engagement"]["id"], 0.1, specialist_user_id="ts-1")

        assert float(third["hours_logged"]) == 4.0, (
            f"Expected hours_logged exactly 4.0, got {third['hours_logged']}"
        )
        assert third["status"] == "BILLABLE", (
            f"Expected BILLABLE, got {third['status']}"
        )
        assert third["attach_fee_cents"] == 37000, (
            f"Expected attach_fee_cents 37000, got {third['attach_fee_cents']}"
        )
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["assigned_specialist_user_id"] == "ts-1"
        assert engagement["order_id"] is None, (
            f"Expected order_id null before attachment, got {engagement['order_id']}"
        )
