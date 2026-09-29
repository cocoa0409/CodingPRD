"""Three contested resources whose adjacency semantics deliberately differ (PRD §2.5, §3.9)."""

from test_helpers import (
    ALMOND_FLOUR,
    FLOUR_HRW_LIST_ONLY,
    YEAST_INSTANT,
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    create_customer,
    create_lot_payload,
    create_product,
    create_route,
    create_route_stop_payload,
    create_zone,
    deliver_stop,
    dispatch_route,
    open_order,
    read_lot,
    read_order,
    read_route,
    read_route_stop,
    read_silo,
    read_zone,
    receive_lot,
    register_silo,
    schedule_zone_lockout,
    seal_route,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import LP, WO


def _route_with_one_stop_and_a_spare_allocated_order():
    """A 30-minute-buffer trailer carrying one 08:00-10:00 drop, plus a waiting order."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    yeast = create_product(YEAST_INSTANT)
    zone = create_zone(allergen_class="NONE")
    lot = receive_lot(
        yeast["id"],
        zone["id"],
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=20000,
    )
    orders = []
    for _ in range(2):
        order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
        add_order_line(customer, order["id"], yeast["id"], 5000)
        submitted = submit_order(customer, order["id"])
        allocate_order(order["id"])
        orders.append(submitted)
    route = create_route(
        service_on="2026-09-15T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    stop1 = append_stop(
        route["id"], orders[0]["id"], "2026-09-15T08:00:00Z", "2026-09-15T10:00:00Z"
    )
    return {
        "customer": customer,
        "yeast": yeast,
        "lot": lot,
        "order1": orders[0],
        "order2": orders[1],
        "route": read_route(route["id"]),
        "stop1": stop1,
    }


class TestRouteStopBufferSemantics:
    """Half-open windows, so a touching endpoint fails only the buffer test."""

    def test_a_window_starting_on_the_previous_end_instant_fails_the_buffer(self):
        """PRD §3.9: "First, stop windows on one route may not overlap, and they
        must additionally be separated by at least the route's
        `service_buffer_minutes`: because windows are half-open, a new window
        beginning exactly at an existing window's `window_end_at` does not
        technically overlap, yet it is still rejected unless the gap between that
        existing end instant and the new start instant is at least the buffer."

        Design: Difficulty/resource_temporal_overlap/overlap_route_stop_windows_half_open_plus_thirty_minute_buffer
        """
        scenario = _route_with_one_stop_and_a_spare_allocated_order()
        assert scenario["order1"]["total_cents"] == 1526750, (
            f"Expected total 1526750, got {scenario['order1']['total_cents']}"
        )
        assert float(scenario["route"]["utilization_pct"]) == 20.83, (
            f"Expected 5000 of 24000 lb to read 20.83, got {scenario['route']['utilization_pct']}"
        )

        response = api_client.create_route_stop(
            scenario["route"]["id"],
            create_route_stop_payload(
                scenario["order2"]["id"],
                scenario["route"]["version"],
                window_start_at="2026-09-15T10:00:00Z",
                window_end_at="2026-09-15T11:00:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        route = read_route(scenario["route"]["id"])
        assert route["version"] == scenario["route"]["version"], (
            f"A rejected append must not move the route version, got {route['version']}"
        )
        assert route["stop_count"] == 1, (
            f"Expected stop_count to stay at 1, got {route['stop_count']}"
        )
        assert read_order(scenario["order2"]["id"])["fulfillment_status"] == "ALLOCATED"

    def test_a_gap_of_exactly_the_buffer_is_accepted_on_the_same_route_version(self):
        """PRD §3.9: "Each accepted append re-runs the load waterfall below and
        increments the route's `version` by 1."

        PRD §3.9: "Finally `utilization_pct` is the planned load divided by the
        vehicle capacity, multiplied by one hundred, and rounded half-up to two
        decimal places."

        The refused 10:00 append left the version alone, so the very same
        `expected_route_version` still satisfies §2.6 on the 10:30 retry, whose
        gap is exactly the 30-minute buffer.

        Design: Difficulty/resource_temporal_overlap/overlap_route_stop_windows_half_open_plus_thirty_minute_buffer
        """
        scenario = _route_with_one_stop_and_a_spare_allocated_order()
        observed_version = scenario["route"]["version"]
        api_client.create_route_stop(
            scenario["route"]["id"],
            create_route_stop_payload(
                scenario["order2"]["id"],
                observed_version,
                window_start_at="2026-09-15T10:00:00Z",
                window_end_at="2026-09-15T11:00:00Z",
            ),
            LP,
        )

        stop2 = validate_success(
            api_client.create_route_stop(
                scenario["route"]["id"],
                create_route_stop_payload(
                    scenario["order2"]["id"],
                    observed_version,
                    window_start_at="2026-09-15T10:30:00Z",
                    window_end_at="2026-09-15T11:30:00Z",
                ),
                LP,
            ),
            201,
        )

        assert stop2["status"] == "PLANNED", (
            f"Expected PLANNED, got {stop2['status']}"
        )
        assert stop2["window_start_at"] == "2026-09-15T10:30:00Z", (
            f"Expected the 10:30 start echoed back, got {stop2['window_start_at']}"
        )
        route = read_route(scenario["route"]["id"])
        assert route["stop_count"] == 2, (
            f"Expected stop_count 2, got {route['stop_count']}"
        )
        assert route["planned_load_lb"] == 10000, (
            f"Expected planned_load_lb 10000, got {route['planned_load_lb']}"
        )
        assert float(route["utilization_pct"]) == 41.67, (
            f"Expected 10000 of 24000 lb to read 41.67, got {route['utilization_pct']}"
        )
        assert route["allergen_class_lock"] == "NONE", (
            f"Expected the trailer locked to NONE, got {route['allergen_class_lock']}"
        )
        assert read_route_stop(scenario["stop1"]["id"])["window_end_at"] == "2026-09-15T10:00:00Z"
        assert read_order(scenario["order2"]["id"])["fulfillment_status"] == "ROUTED", (
            "An accepted append carries the order ALLOCATED -> ROUTED"
        )
        assert read_lot(scenario["lot"]["id"])["quantity_reserved_lb"] == 10000


def _silo_with_a_recorded_fill_window_and_a_second_bulk_order():
    """One pneumatic drop already delivered into the silo, and another waiting."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    flour = create_product(FLOUR_HRW_LIST_ONLY)
    zone = create_zone(allergen_class="GLUTEN")
    lot = receive_lot(flour["id"], zone["id"], quantity_received_lb=50000)
    silo = register_silo(
        customer["id"], flour["id"], capacity_lb=60000, min_fill_lb=5000
    )
    order1 = open_order(
        customer, delivery_mode="BULK", requested_delivery_on="2026-09-15T00:00:00Z"
    )
    add_order_line(customer, order1["id"], flour["id"], 20000)
    submitted1 = submit_order(customer, order1["id"])
    allocate_order(order1["id"])
    route1 = create_route(
        service_on="2026-09-15T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    stop1 = append_stop(
        route1["id"], order1["id"], "2026-09-15T08:00:00Z", "2026-09-15T10:00:00Z"
    )
    seal_route(route1["id"])
    set_clock("2026-09-15T00:00:00Z")
    dispatch_route(route1["id"])
    delivered_stop = deliver_stop(stop1["id"])
    order2 = open_order(
        customer, delivery_mode="BULK", requested_delivery_on="2026-09-15T00:00:00Z"
    )
    add_order_line(customer, order2["id"], flour["id"], 20000)
    submitted2 = submit_order(customer, order2["id"])
    allocate_order(order2["id"])
    route2 = create_route(
        service_on="2026-09-15T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    return {
        "customer": customer,
        "flour": flour,
        "lot": lot,
        "silo": read_silo(silo["id"]),
        "order1": submitted1,
        "delivered_stop": delivered_stop,
        "order2": submitted2,
        "route2": read_route(route2["id"]),
    }


class TestSiloFillWindowSemantics:
    """Closed interval and no buffer, the exact opposite of the trailer rule."""

    def test_a_bulk_window_sharing_the_end_instant_collides_with_the_last_fill(self):
        """PRD §3.9: "Second, a silo's accepted fill window is a **closed**
        interval running from `last_fill_window_start_at` to
        `last_fill_window_end_at` with both endpoints included, and a bulk stop
        whose window shares even a single instant with it — endpoints included,
        with no buffer applied — is rejected with
        `ERR_SILO_FILL_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_silo_fill_windows_closed_interval_touching_endpoint_collides
        """
        scenario = _silo_with_a_recorded_fill_window_and_a_second_bulk_order()
        assert scenario["order1"]["total_cents"] == 827022, (
            f"Expected total 827022, got {scenario['order1']['total_cents']}"
        )
        assert scenario["delivered_stop"]["status"] == "DELIVERED", (
            f"Expected DELIVERED, got {scenario['delivered_stop']['status']}"
        )
        assert scenario["silo"]["residual_lb"] == 20000, (
            f"Expected residual_lb 20000, got {scenario['silo']['residual_lb']}"
        )
        assert scenario["silo"]["last_fill_window_start_at"] == "2026-09-15T08:00:00Z"
        assert scenario["silo"]["last_fill_window_end_at"] == "2026-09-15T10:00:00Z"

        response = api_client.create_route_stop(
            scenario["route2"]["id"],
            create_route_stop_payload(
                scenario["order2"]["id"],
                scenario["route2"]["version"],
                window_start_at="2026-09-15T10:00:00Z",
                window_end_at="2026-09-15T12:00:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_SILO_FILL_WINDOW_CONFLICT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        route2 = read_route(scenario["route2"]["id"])
        assert route2["stop_count"] == 0, (
            f"Expected the second route still empty, got {route2['stop_count']}"
        )
        assert read_order(scenario["order2"]["id"])["fulfillment_status"] == "ALLOCATED"

    def test_a_window_one_second_clear_of_the_endpoint_is_accepted(self):
        """PRD §3.9: "Touching endpoints collide here, where on the route they
        merely fail the buffer test."

        No buffer applies to the silo, so a start instant one second past
        10:00:00Z clears the closed interval and the drop is planned.

        Design: Difficulty/resource_temporal_overlap/overlap_silo_fill_windows_closed_interval_touching_endpoint_collides
        """
        scenario = _silo_with_a_recorded_fill_window_and_a_second_bulk_order()

        stop2 = validate_success(
            api_client.create_route_stop(
                scenario["route2"]["id"],
                create_route_stop_payload(
                    scenario["order2"]["id"],
                    scenario["route2"]["version"],
                    window_start_at="2026-09-15T10:00:01Z",
                    window_end_at="2026-09-15T12:00:00Z",
                ),
                LP,
            ),
            201,
        )

        assert stop2["status"] == "PLANNED", (
            f"Expected PLANNED, got {stop2['status']}"
        )
        route2 = read_route(scenario["route2"]["id"])
        assert route2["stop_count"] == 1, (
            f"Expected stop_count 1, got {route2['stop_count']}"
        )
        assert route2["planned_load_lb"] == 20000, (
            f"Expected planned_load_lb 20000, got {route2['planned_load_lb']}"
        )
        assert float(route2["utilization_pct"]) == 83.33, (
            f"Expected 20000 of 24000 lb to read 83.33, got {route2['utilization_pct']}"
        )
        silo = read_silo(scenario["silo"]["id"])
        assert silo["residual_lb"] == 20000, (
            f"Expected the residual unchanged by planning, got {silo['residual_lb']}"
        )
        assert silo["capacity_lb"] == 60000
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_consumed_lb"] == 20000, (
            f"Expected 20000 lb consumed by the first drop, got {lot['quantity_consumed_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 20000, (
            f"Expected 20000 lb reserved for the second, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_on_hand_lb"] == 10000, (
            f"Expected 10000 lb still on hand, got {lot['quantity_on_hand_lb']}"
        )


def _zone_whose_lockout_ends_on_the_clock_instant():
    """A nut zone with stock already in it, locked out up to and including now."""
    set_clock("2026-08-05T00:00:00Z")
    almond = create_product(ALMOND_FLOUR)
    zone = create_zone(allergen_class="TREE_NUT")
    control_lot = receive_lot(
        almond["id"],
        zone["id"],
        lot_code="LOT-CTRL-01",
        manufactured_on="2026-08-01T00:00:00Z",
        quantity_received_lb=1000,
    )
    before = schedule_zone_lockout(
        zone["id"], "2026-08-08T06:00:00Z", "2026-08-10T00:00:00Z"
    )
    set_clock("2026-08-10T00:00:00Z")
    locked = schedule_zone_lockout(
        zone["id"], "2026-08-08T06:00:00Z", "2026-08-10T00:00:00Z"
    )
    return {
        "almond": almond,
        "zone": zone,
        "control_lot": control_lot,
        "zone_before_lockout": before,
        "zone_locked": locked,
    }


class TestZoneLockoutEndpointSemantics:
    """The contested dimension is the clock instant against a closed interval."""

    def test_a_receipt_on_the_closing_instant_of_the_lockout_is_refused(self):
        """PRD §3.1: "The lockout is a **closed** interval — both endpoints
        belong to it."

        PRD §3.1: "While a zone is inside its lockout window, no lot may be
        received into it and no quarantined lot in it may be released, and both
        attempts are rejected with `ERR_ZONE_LOCKOUT_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_zone_sanitation_lockout_closed_interval_clock_on_end_endpoint
        """
        scenario = _zone_whose_lockout_ends_on_the_clock_instant()
        assert scenario["zone_before_lockout"]["status"] == "OPEN", (
            "Scheduling a future window leaves the zone open, got "
            f"{scenario['zone_before_lockout']['status']}"
        )
        assert scenario["zone_locked"]["status"] == "SANITATION_LOCKOUT", (
            f"Expected SANITATION_LOCKOUT on the closing instant, got {scenario['zone_locked']['status']}"
        )

        response = api_client.create_lot(
            create_lot_payload(
                scenario["almond"]["id"],
                scenario["zone"]["id"],
                lot_code="LOT-EDGE-01",
                manufactured_on="2026-08-01T00:00:00Z",
                quantity_received_lb=4000,
            ),
            WO,
        )

        validate_error(response, ApiErrorId.ERR_ZONE_LOCKOUT_CONFLICT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        lots, _meta = validate_paginated(api_client.list_lots(WO))
        assert "LOT-EDGE-01" not in [lot["lot_code"] for lot in lots], (
            "The refused receipt must not have persisted a lot row"
        )
        zone = read_zone(scenario["zone"]["id"])
        assert zone["on_hand_lb"] == 1000, (
            f"Expected the zone still holding only the control lot, got {zone['on_hand_lb']}"
        )
        assert zone["lockout_start_at"] == "2026-08-08T06:00:00Z"
        assert zone["lockout_end_at"] == "2026-08-10T00:00:00Z"

    def test_a_receipt_one_second_past_the_endpoint_reopens_the_zone(self):
        """PRD §3.1: "When the logical clock instant falls inside that closed
        interval the zone's `status` reads `SANITATION_LOCKOUT`, and otherwise
        `OPEN`; the zone's `version` increments by 1 on either scheduling or
        clearing."

        PRD §3.5: "Receipt computes `expires_on` as the manufacture date advanced
        by the product's `shelf_life_days`, landing at midnight UTC, and
        initialises the three pound buckets: `quantity_on_hand_lb` equals
        `quantity_received_lb`, while `quantity_reserved_lb` and
        `quantity_consumed_lb` are both 0."

        Design: Difficulty/resource_temporal_overlap/overlap_zone_sanitation_lockout_closed_interval_clock_on_end_endpoint
        """
        scenario = _zone_whose_lockout_ends_on_the_clock_instant()
        api_client.create_lot(
            create_lot_payload(
                scenario["almond"]["id"],
                scenario["zone"]["id"],
                lot_code="LOT-EDGE-01",
                manufactured_on="2026-08-01T00:00:00Z",
                quantity_received_lb=4000,
            ),
            WO,
        )
        set_clock("2026-08-10T00:00:01Z")

        reopened = schedule_zone_lockout(
            scenario["zone"]["id"], "2026-08-08T06:00:00Z", "2026-08-10T00:00:00Z"
        )

        assert reopened["status"] == "OPEN", (
            f"Expected the zone back to OPEN one second later, got {reopened['status']}"
        )
        accepted = validate_success(
            api_client.create_lot(
                create_lot_payload(
                    scenario["almond"]["id"],
                    scenario["zone"]["id"],
                    lot_code="LOT-EDGE-02",
                    manufactured_on="2026-08-01T00:00:00Z",
                    quantity_received_lb=4000,
                ),
                WO,
            ),
            201,
        )
        assert accepted["status"] == "AVAILABLE", (
            f"Expected AVAILABLE, got {accepted['status']}"
        )
        assert accepted["quantity_on_hand_lb"] == 4000, (
            f"Expected 4000 lb on hand, got {accepted['quantity_on_hand_lb']}"
        )
        assert accepted["expires_on"] == "2026-11-29T00:00:00Z", (
            f"120 shelf-life days from 2026-08-01 land on 2026-11-29, got {accepted['expires_on']}"
        )
        assert read_lot(scenario["control_lot"]["id"])["quantity_on_hand_lb"] == 1000
        zone = read_zone(scenario["zone"]["id"])
        assert zone["on_hand_lb"] == 5000, (
            f"Expected the zone total at 5000 lb, got {zone['on_hand_lb']}"
        )
        assert zone["status"] == "OPEN", f"Expected OPEN, got {zone['status']}"
