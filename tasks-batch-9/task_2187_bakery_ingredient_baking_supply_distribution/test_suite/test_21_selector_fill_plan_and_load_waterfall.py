"""The rotation selector, the pneumatic fill plan and the compartment waterfall (PRD §3.5, §3.6, §3.9)."""

from test_helpers import (
    add_order_line,
    allocate_order,
    append_stop,
    assert_lot_inventory_conservation,
    create_customer,
    create_product,
    create_route,
    create_zone,
    open_order,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    read_silo,
    read_zone,
    receive_lot,
    record_residual_reading,
    register_silo,
    set_clock,
    submit_order,
)

EPOCH = "2026-08-01T00:00:00Z"

FEFO_FLOUR = {
    "sku": "FLR-FEFO-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
ROTATION_YEAST = {
    "sku": "YST-ROT-30",
    "category": "LEAVENING",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 120,
}
BULK_FLOUR = {
    "sku": "FLR-BULK-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "bulk_capable": True,
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
WATERFALL_FLOUR = {
    "sku": "FLR-WF-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _bakery_with_gluten_zone(product_spec):
    set_clock(EPOCH)
    customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
    product = create_product(product_spec)
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    return customer, product, zone


def _submit_bagged_line(customer, product_id, quantity_lb,
                        requested_delivery_on="2026-09-05T00:00:00Z",
                        delivery_mode="BAGGED"):
    order = open_order(
        customer,
        delivery_mode=delivery_mode,
        requested_delivery_on=requested_delivery_on,
    )
    line = add_order_line(customer, order["id"], product_id, quantity_lb)
    submit_order(customer, order["id"])
    return order, line


class TestFefoTieBreak:
    """Equal expiry sends the selector to the larger on-hand bucket, not the older row."""

    def test_the_bigger_of_two_equally_dated_lots_wins_and_the_short_one_is_filtered_out(self):
        """PRD §3.5: "the lot's `quantity_on_hand_lb` is at least the line's
        `quantity_lb`" ... "Among the candidates, ranking is
        First-Expired-First-Out: the earliest `expires_on` wins. Only where two
        candidates share the same expiry does a tie-break apply, and then the larger
        `quantity_on_hand_lb` wins; if that is also equal, the earlier `created_at`
        wins. Lot identifiers are never used as a tie-break. Splitting a line across
        two lots is not permitted — one lot must cover the whole line by itself"

        PRD §3.5: "A successful receipt recomputes the zone's `on_hand_lb`, which is
        the total of `quantity_on_hand_lb` over the lots stored in that zone whose
        status is `AVAILABLE` or `QUARANTINED`."

        Design: Corner/calculations/corner_calc_fefo_tie_break_prefers_larger_on_hand_over_older_row
        """
        customer, flour, zone = _bakery_with_gluten_zone(FEFO_FLOUR)
        early = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-EARLY",
            manufactured_on="2026-06-01T00:00:00Z", quantity_received_lb=500,
        )
        small = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-SMALL",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=5000,
        )
        big = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-BIG",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=9000,
        )
        assert early["expires_on"] == "2026-11-28T00:00:00Z", (
            f"Expected 2026-06-01 advanced by 180 days, got {early['expires_on']}"
        )
        assert big["expires_on"] == "2026-12-28T00:00:00Z", (
            f"Expected 2026-07-01 advanced by 180 days, got {big['expires_on']}"
        )
        order, line = _submit_bagged_line(customer, flour["id"], 1000)

        allocated = allocate_order(order["id"])

        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
        picked = read_order_line(line["id"])
        assert picked["lot_id"] == big["id"], (
            "The 9000 lb lot must beat the equally-dated 5000 lb lot created before it"
        )
        assert picked["allocation_status"] == "RESERVED", (
            f"Expected RESERVED, got {picked['allocation_status']}"
        )
        chosen = read_lot(big["id"])
        assert chosen["quantity_reserved_lb"] == 1000, (
            f"Expected 1000 lb reserved on LOT-BIG, got {chosen['quantity_reserved_lb']}"
        )
        assert chosen["quantity_on_hand_lb"] == 8000, (
            f"Expected 8000 lb left on hand, got {chosen['quantity_on_hand_lb']}"
        )
        assert_lot_inventory_conservation(chosen)
        loser = read_lot(small["id"])
        assert loser["quantity_reserved_lb"] == 0, (
            f"Expected the tie-break loser untouched, got {loser['quantity_reserved_lb']}"
        )
        assert loser["quantity_on_hand_lb"] == 5000, (
            f"Expected 5000 lb still on hand, got {loser['quantity_on_hand_lb']}"
        )
        filtered = read_lot(early["id"])
        assert filtered["quantity_reserved_lb"] == 0, (
            "The earliest-expiring lot is too small to cover the line by itself"
        )
        assert filtered["quantity_on_hand_lb"] == 500, (
            f"Expected 500 lb still on hand, got {filtered['quantity_on_hand_lb']}"
        )
        assert read_zone(zone["id"])["on_hand_lb"] == 13500, (
            f"Expected 14500 lb less the 1000 reserved, got {read_zone(zone['id'])['on_hand_lb']}"
        )


class TestMinRotationDaysFiltersBeforeRanking:
    """The freshness floor removes the FEFO favourite from the candidate set entirely."""

    def test_the_lot_with_sixty_one_days_of_life_is_skipped_for_the_one_with_a_hundred_fifty_three(self):
        """PRD §3.5: "the number of whole UTC days from the logical clock date to the
        lot's `expires_on` is at least the product's `min_rotation_days`"

        PRD §3.5: "Lots that are `QUARANTINED`, `EXPIRED`, `DISPOSED` or `DEPLETED`
        are never candidates. Among the candidates, ranking is
        First-Expired-First-Out: the earliest `expires_on` wins."

        The near lot is still `AVAILABLE` and still the earliest expiring, so only the
        `min_rotation_days` predicate can explain the selector reaching past it.

        Design: Corner/calculations/corner_calc_min_rotation_days_excludes_earliest_expiring_lot
        """
        customer, yeast, zone = _bakery_with_gluten_zone(ROTATION_YEAST)
        near = receive_lot(
            yeast["id"], zone["id"], lot_code="LOT-NEAR",
            manufactured_on="2026-04-04T00:00:00Z", quantity_received_lb=20000,
        )
        far = receive_lot(
            yeast["id"], zone["id"], lot_code="LOT-FAR",
            manufactured_on="2026-07-05T00:00:00Z", quantity_received_lb=20000,
        )
        order, line = _submit_bagged_line(customer, yeast["id"], 1000)

        allocate_order(order["id"])

        assert read_order_line(line["id"])["lot_id"] == far["id"], (
            "Only 61 days of life remain on the near lot against a 120-day floor"
        )
        skipped = read_lot(near["id"])
        assert skipped["expires_on"] == "2026-10-01T00:00:00Z", (
            f"Expected 2026-04-04 advanced by 180 days, got {skipped['expires_on']}"
        )
        assert skipped["quantity_reserved_lb"] == 0, (
            f"Expected nothing reserved on the near lot, got {skipped['quantity_reserved_lb']}"
        )
        assert skipped["quantity_on_hand_lb"] == 20000, (
            f"Expected 20000 lb still on hand, got {skipped['quantity_on_hand_lb']}"
        )
        assert skipped["status"] == "AVAILABLE", (
            f"Rotation filtering must not change lot state, got {skipped['status']}"
        )
        used = read_lot(far["id"])
        assert used["expires_on"] == "2027-01-01T00:00:00Z", (
            f"Expected 2026-07-05 advanced by 180 days, got {used['expires_on']}"
        )
        assert used["quantity_reserved_lb"] == 1000, (
            f"Expected 1000 lb reserved on the far lot, got {used['quantity_reserved_lb']}"
        )
        assert used["quantity_on_hand_lb"] == 19000, (
            f"Expected 19000 lb left on hand, got {used['quantity_on_hand_lb']}"
        )
        assert_lot_inventory_conservation(used)


class TestFillPlanAtBothBoundariesAtOnce:
    """Fillable equals headroom equals the line equals `min_fill_lb`, and both tests pass."""

    def test_a_fill_that_exactly_uses_the_headroom_and_exactly_meets_the_minimum_is_accepted(self):
        """PRD §3.6: "Headroom is the silo's `capacity_lb` less its current
        `residual_lb`." ... "The third quantity is the line's own `quantity_lb`, and
        the fourth is the trailer compartment ceiling of 48000 pounds" ... "The
        fillable amount is the smallest of those four. If the fillable amount is less
        than the line's `quantity_lb`, the allocation is rejected with
        `ERR_SILO_HEADROOM_INSUFFICIENT` (HTTP 422). If the fillable amount is less
        than the silo's `min_fill_lb`, it cannot be blown pneumatically at all and the
        allocation is rejected with `ERR_BULK_FILL_BELOW_MIN` (HTTP 422). Only when
        both tests pass is the line's `silo_id` set to that silo."

        PRD §3.6: "a `measured_residual_lb` that overwrites `residual_lb` outright
        rather than adjusting it"

        Design: Corner/calculations/corner_calc_bulk_fill_nested_min_binds_on_headroom_at_exact_min_fill
        """
        customer, flour, zone = _bakery_with_gluten_zone(BULK_FLOUR)
        lot = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-B-0001",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=40000,
        )
        silo = register_silo(
            customer["id"], flour["id"], silo_code="SILO-01",
            capacity_lb=20000, min_fill_lb=5000,
        )
        record_residual_reading(silo["id"], 15000)
        order, line = _submit_bagged_line(
            customer, flour["id"], 5000, delivery_mode="BULK"
        )

        allocated = allocate_order(order["id"])

        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
        planned = read_order_line(line["id"])
        assert planned["silo_id"] == silo["id"], (
            f"Expected the only matching silo bound to the line, got {planned['silo_id']}"
        )
        assert planned["lot_id"] == lot["id"], (
            f"Expected the only eligible lot, got {planned['lot_id']}"
        )
        assert planned["allocation_status"] == "RESERVED", (
            f"Expected RESERVED, got {planned['allocation_status']}"
        )
        assert read_silo(silo["id"])["residual_lb"] == 15000, (
            "Allocation plans the fill but adds no pounds to the silo"
        )
        filled_from = read_lot(lot["id"])
        assert filled_from["quantity_reserved_lb"] == 5000, (
            f"Expected 5000 lb reserved, got {filled_from['quantity_reserved_lb']}"
        )
        assert filled_from["quantity_on_hand_lb"] == 35000, (
            f"Expected 35000 lb on hand, got {filled_from['quantity_on_hand_lb']}"
        )
        assert_lot_inventory_conservation(filled_from)


class TestOneStopStraddlesTwoCompartments:
    """25000 lb cannot sit in one 24000 lb compartment, yet the trailer still takes it."""

    def test_the_second_stop_spills_into_the_second_compartment_instead_of_being_refused(self):
        """PRD §3.9: "The trailer is then modelled as two compartments of 24000 pounds
        each, and each stop's pounds are poured in sequence: as much as fits goes into
        the first compartment, the remainder spills into the second, and a single
        stop's pounds may straddle the two. If any pounds remain unplaced after both
        compartments are full, the operation is rejected with
        `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 409)" ... "Finally `utilization_pct` is
        the planned load divided by the vehicle capacity, multiplied by one hundred,
        and rounded half-up to two decimal places."

        PRD §3.9: "The order must be sitting at `ALLOCATED`, and appending the stop
        advances it `ALLOCATED → ROUTED`" ... "When the route's `allergen_class_lock`
        is still `NONE`, appending the first stop sets it from that order's allergen
        class"

        Design: Corner/calculations/corner_calc_route_waterfall_second_stop_straddles_compartments
        """
        customer, flour, zone = _bakery_with_gluten_zone(WATERFALL_FLOUR)
        receive_lot(
            flour["id"], zone["id"], lot_code="LOT-W-0001",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=60000,
        )
        first_order, _ = _submit_bagged_line(
            customer, flour["id"], 20000, requested_delivery_on="2026-09-10T00:00:00Z"
        )
        allocate_order(first_order["id"])
        second_order, _ = _submit_bagged_line(
            customer, flour["id"], 25000, requested_delivery_on="2026-09-10T00:00:00Z"
        )
        allocate_order(second_order["id"])
        route = create_route(
            route_code="R-WF",
            service_on="2026-09-10T00:00:00Z",
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        append_stop(
            route["id"], first_order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )

        straddling = append_stop(
            route["id"], second_order["id"],
            "2026-09-10T10:00:00Z", "2026-09-10T11:00:00Z",
        )

        assert read_route_stop(straddling["id"])["status"] == "PLANNED", (
            f"Expected PLANNED, got {read_route_stop(straddling['id'])['status']}"
        )
        loaded = read_route(route["id"])
        assert loaded["stop_count"] == 2, (
            f"Expected stop_count 2, got {loaded['stop_count']}"
        )
        assert loaded["planned_load_lb"] == 45000, (
            f"Expected 20000 + 25000 pounds planned, got {loaded['planned_load_lb']}"
        )
        assert float(loaded["utilization_pct"]) == 93.75, (
            f"Expected 45000 of 48000 as 93.75, got {loaded['utilization_pct']}"
        )
        assert loaded["status"] == "PLANNING", (
            f"Expected the route still PLANNING, got {loaded['status']}"
        )
        assert loaded["allergen_class_lock"] == "GLUTEN", (
            f"Expected the lock set by the first stop, got {loaded['allergen_class_lock']}"
        )
        assert read_order(first_order["id"])["fulfillment_status"] == "ROUTED", (
            "The first stop's order was carried to ROUTED on append"
        )
        assert read_order(second_order["id"])["fulfillment_status"] == "ROUTED", (
            "The straddling stop's order must be carried to ROUTED too"
        )
