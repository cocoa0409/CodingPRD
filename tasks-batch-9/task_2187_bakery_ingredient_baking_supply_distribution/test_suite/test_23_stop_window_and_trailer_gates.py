"""What a trailer refuses: touching windows, a second allergen class, a full compartment (PRD §2.8, §3.9)."""

from test_helpers import (
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
    read_order,
    read_route,
    read_route_stop,
    receive_lot,
    set_clock,
    submit_order,
    validate_error,
)
from test_helpers.fixtures import LP

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

BUFFER_FLOUR = {
    "sku": "FLR-BUF-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
LOCK_DAIRY = {
    "sku": "DRY-LK-30",
    "category": "INCLUSION",
    "allergen_class": "DAIRY",
    "shelf_life_days": 150,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _allocated(customer, product_id, quantity_lb):
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on=SERVICE_ON,
    )
    add_order_line(customer, order["id"], product_id, quantity_lb)
    submit_order(customer, order["id"])
    allocate_order(order["id"])
    return order


def _two_thousand_pound_pair(route_code, vehicle_capacity_lb=24000):
    """A PLANNING route already carrying an 08:00–09:00 stop, plus a spare order."""
    set_clock(EPOCH)
    customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
    flour = create_product(BUFFER_FLOUR)
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    receive_lot(
        flour["id"], zone["id"], lot_code="LOT-G-0001",
        manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=20000,
    )
    first = _allocated(customer, flour["id"], 1000)
    second = _allocated(customer, flour["id"], 1000)
    route = create_route(
        route_code=route_code,
        service_on=SERVICE_ON,
        vehicle_capacity_lb=vehicle_capacity_lb,
        service_buffer_minutes=30,
    )
    append_stop(route["id"], first["id"], "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z")
    return {"customer": customer, "route": route, "second_order": second}


class TestServiceBufferOnTouchingWindows:
    """Half-open windows do not overlap at the seam, and the buffer still refuses them."""

    def test_a_stop_starting_exactly_when_the_previous_one_ends_is_refused(self):
        """PRD §3.9: "First, stop windows on one route may not overlap, and they must
        additionally be separated by at least the route's `service_buffer_minutes`:
        because windows are half-open, a new window beginning exactly at an existing
        window's `window_end_at` does not technically overlap, yet it is still rejected
        unless the gap between that existing end instant and the new start instant is
        at least the buffer. Either failure is reported as `ERR_STOP_WINDOW_CONFLICT`
        (HTTP 409)."

        Design: Corner/validations/corner_val_touching_stop_window_rejected_by_service_buffer
        """
        scenario = _two_thousand_pound_pair("R-BUF")
        pinned = read_route(scenario["route"]["id"])["version"]

        response = api_client.create_route_stop(
            scenario["route"]["id"],
            create_route_stop_payload(
                scenario["second_order"]["id"],
                pinned,
                window_start_at="2026-09-10T09:00:00Z",
                window_end_at="2026-09-10T10:00:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_STOP_WINDOW_CONFLICT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        route = read_route(scenario["route"]["id"])
        assert route["stop_count"] == 1, (
            f"Expected the rejected stop absent, got stop_count {route['stop_count']}"
        )
        assert route["planned_load_lb"] == 1000, (
            f"Expected only the first stop's pounds, got {route['planned_load_lb']}"
        )
        assert route["version"] == pinned, (
            f"A rejected write leaves the route version at {pinned}, got {route['version']}"
        )
        assert read_order(scenario["second_order"]["id"])["fulfillment_status"] == "ALLOCATED", (
            "The refused order must not be advanced to ROUTED"
        )

    def test_a_gap_of_exactly_the_buffer_is_accepted(self):
        """PRD §3.9: "they must additionally be separated by at least the route's
        `service_buffer_minutes`"

        PRD §3.9: "Finally `utilization_pct` is the planned load divided by the
        vehicle capacity, multiplied by one hundred, and rounded half-up to two decimal
        places."

        Thirty minutes of separation is exactly the buffer, so the same append that
        failed at the seam succeeds here — the buffer, not the ordering, was the cause.

        Design: Corner/validations/corner_val_stop_window_exactly_one_buffer_after_previous_passes
        """
        scenario = _two_thousand_pound_pair("R-BUFOK")

        appended = append_stop(
            scenario["route"]["id"],
            scenario["second_order"]["id"],
            "2026-09-10T09:30:00Z",
            "2026-09-10T10:30:00Z",
        )

        assert read_route_stop(appended["id"])["status"] == "PLANNED", (
            f"Expected PLANNED, got {read_route_stop(appended['id'])['status']}"
        )
        route = read_route(scenario["route"]["id"])
        assert route["stop_count"] == 2, (
            f"Expected stop_count 2, got {route['stop_count']}"
        )
        assert route["planned_load_lb"] == 2000, (
            f"Expected 2000 lb planned, got {route['planned_load_lb']}"
        )
        assert float(route["utilization_pct"]) == 8.33, (
            f"Expected 2000 of 24000 rounded to 8.33, got {route['utilization_pct']}"
        )
        assert read_order(scenario["second_order"]["id"])["fulfillment_status"] == "ROUTED", (
            "The accepted stop carries its order to ROUTED"
        )


class TestTrailerAllergenLock:
    """One non-`NONE` class per trailer, whatever the timing and whatever the capacity."""

    def test_a_dairy_stop_cannot_join_a_trailer_already_locked_to_gluten(self):
        """PRD §2.8: "On the trailer, once a route's `allergen_class_lock` holds any
        value other than `NONE`, every subsequently added stop's order lines must all
        carry that same `allergen_class`; a trailer may never hold two different
        non-`NONE` classes at once. That check guards both appending a stop and sealing
        the load plan, and in either case the rejection is
        `ERR_ROUTE_ALLERGEN_LOCK_CONFLICT` (HTTP 409)."

        The window respects the 30-minute buffer and 2000 lb is far under the trailer's
        24000, so only the lock can explain the refusal.

        Design: Corner/validations/corner_val_second_allergen_class_on_locked_route_rejected
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(BUFFER_FLOUR, sku="FLR-LK-30"))
        dairy = create_product(LOCK_DAIRY)
        gluten_zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        dairy_zone = create_zone(zone_code="Z-DRY", allergen_class="DAIRY")
        receive_lot(
            flour["id"], gluten_zone["id"], lot_code="LOT-LKG-0001",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=20000,
        )
        receive_lot(
            dairy["id"], dairy_zone["id"], lot_code="LOT-LKD-0001",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=20000,
        )
        gluten_order = _allocated(customer, flour["id"], 1000)
        dairy_order = _allocated(customer, dairy["id"], 1000)
        route = create_route(
            route_code="R-LOCK",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=24000,
            service_buffer_minutes=30,
        )
        append_stop(
            route["id"], gluten_order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        pinned = read_route(route["id"])["version"]

        response = api_client.create_route_stop(
            route["id"],
            create_route_stop_payload(
                dairy_order["id"],
                pinned,
                window_start_at="2026-09-10T09:30:00Z",
                window_end_at="2026-09-10T10:30:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_ROUTE_ALLERGEN_LOCK_CONFLICT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        locked = read_route(route["id"])
        assert locked["allergen_class_lock"] == "GLUTEN", (
            f"Expected the lock immutable at GLUTEN, got {locked['allergen_class_lock']}"
        )
        assert locked["stop_count"] == 1, (
            f"Expected stop_count 1, got {locked['stop_count']}"
        )
        assert locked["planned_load_lb"] == 1000, (
            f"Expected 1000 lb planned, got {locked['planned_load_lb']}"
        )
        assert locked["version"] == pinned, (
            f"A rejected append leaves the version at {pinned}, got {locked['version']}"
        )
        assert read_order(dairy_order["id"])["fulfillment_status"] == "ALLOCATED", (
            "The refused dairy order keeps its reservations and its ALLOCATED state"
        )


class TestCompartmentsBindBeforeVehicleCapacity:
    """Two 24000 lb boxes can refuse a load the 60000 lb payload figure would allow."""

    def test_a_four_thousand_pound_third_stop_overflows_the_second_compartment(self):
        """PRD §3.9: "The trailer is then modelled as two compartments of 24000 pounds
        each, and each stop's pounds are poured in sequence: as much as fits goes into
        the first compartment, the remainder spills into the second, and a single
        stop's pounds may straddle the two. If any pounds remain unplaced after both
        compartments are full, the operation is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 409); the same error is raised when
        `planned_load_lb` would exceed the route's `vehicle_capacity_lb`."

        49000 lb sits comfortably below the 60000 lb payload, but only 3000 lb of
        compartment two survive the 20000 and 25000 lb pours.

        Design: Corner/validations/corner_val_third_stop_rejected_by_compartment_waterfall_under_capacity
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(BUFFER_FLOUR, sku="FLR-OVF-30"))
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        receive_lot(
            flour["id"], zone["id"], lot_code="LOT-O-0001",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=60000,
        )
        first = _allocated(customer, flour["id"], 20000)
        second = _allocated(customer, flour["id"], 25000)
        third = _allocated(customer, flour["id"], 4000)
        route = create_route(
            route_code="R-OVF",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=60000,
            service_buffer_minutes=30,
        )
        append_stop(route["id"], first["id"], "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z")
        append_stop(route["id"], second["id"], "2026-09-10T09:30:00Z", "2026-09-10T10:30:00Z")
        pinned = read_route(route["id"])["version"]

        response = api_client.create_route_stop(
            route["id"],
            create_route_stop_payload(
                third["id"],
                pinned,
                window_start_at="2026-09-10T11:00:00Z",
                window_end_at="2026-09-10T12:00:00Z",
            ),
            LP,
        )

        validate_error(response, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        full = read_route(route["id"])
        assert full["stop_count"] == 2, (
            f"Expected stop_count 2, got {full['stop_count']}"
        )
        assert full["planned_load_lb"] == 45000, (
            f"Expected the first two stops only, got {full['planned_load_lb']}"
        )
        assert float(full["utilization_pct"]) == 75.00, (
            f"Expected 45000 of 60000 as 75.00, got {full['utilization_pct']}"
        )
        assert full["version"] == pinned, (
            f"A rejected append leaves the version at {pinned}, got {full['version']}"
        )
        assert read_order(third["id"])["fulfillment_status"] == "ALLOCATED", (
            "The overflowing order stays ALLOCATED"
        )
