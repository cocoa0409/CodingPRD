"""Route reversals and the derived read surfaces (PRD §3.4, §3.9, §4)."""

from test_helpers import (
    abort_route,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    assert_lot_inventory_conservation,
    create_customer,
    create_product,
    create_route,
    create_zone,
    dispatch_route,
    open_order,
    publish_index_quote,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    receive_lot,
    seal_route,
    set_clock,
    submit_order,
    unseal_route,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AM, LP, WO, buyer_headers

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-EP-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _stocked_bakery(sku, quantity_received_lb=20000, lot_code="LOT-EP-0001"):
    set_clock(EPOCH)
    customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
    flour = create_product(dict(FLOUR_30, sku=sku))
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    lot = receive_lot(
        flour["id"], zone["id"], lot_code=lot_code,
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=quantity_received_lb,
    )
    return customer, flour, lot


def _allocated_order(customer, product_id, quantity_lb,
                     requested_delivery_on=SERVICE_ON):
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on=requested_delivery_on,
    )
    line = add_order_line(customer, order["id"], product_id, quantity_lb)
    submit_order(customer, order["id"])
    allocate_order(order["id"])
    return order, line


class TestCancellingTheOnlyStopOfASealedRoute:
    """One call writes the stop, the order, the route status and the load figures."""

    def test_the_route_falls_back_to_planning_and_forgets_its_allergen_lock(self):
        """PRD §3.9: "Cancelling a planned stop is available on a route that is either
        `PLANNING` or `SEALED`. The stop's `status` becomes `CANCELLED` and its order
        steps back `ROUTED → ALLOCATED`, retaining its reservations. The waterfall
        re-runs, and if `stop_count` reaches zero on a route that was `SEALED`, that
        route reverts `SEALED → PLANNING` and its `allergen_class_lock` resets to
        `NONE`."

        PRD §3.9: "The route's `stop_count` is the number of participating stops. Its
        `planned_load_lb` is the total, across those stops, of the `quantity_lb` on
        every line of each stop's order."

        Design: Corner/endpoints/corner_ep_delete_last_stop_reverts_sealed_route_to_planning
        """
        customer, flour, lot = _stocked_bakery("FLR-DEL-30", lot_code="LOT-DEL-0001")
        order, line = _allocated_order(customer, flour["id"], 1000)
        route = create_route(
            route_code="R-DEL",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=24000,
            service_buffer_minutes=30,
        )
        stop = append_stop(
            route["id"], order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        sealed = seal_route(route["id"])
        assert sealed["status"] == "SEALED", (
            f"Expected the route SEALED before the cancellation, got {sealed['status']}"
        )

        cancelled = validate_success(
            api_client.delete_route_stop(stop["id"], LP), 200
        )

        assert cancelled["status"] == "CANCELLED", (
            f"Expected CANCELLED, got {cancelled['status']}"
        )
        assert read_order(order["id"])["fulfillment_status"] == "ALLOCATED", (
            "The order steps back to ALLOCATED rather than to NEW"
        )
        assert read_order_line(line["id"])["allocation_status"] == "RESERVED", (
            "The reservation is retained across the cancellation"
        )
        reopened = read_route(route["id"])
        assert reopened["status"] == "PLANNING", (
            f"Expected PLANNING, got {reopened['status']}"
        )
        assert reopened["allergen_class_lock"] == "NONE", (
            f"An emptied trailer forgets its class, got {reopened['allergen_class_lock']}"
        )
        assert reopened["stop_count"] == 0, (
            f"Expected stop_count 0, got {reopened['stop_count']}"
        )
        assert reopened["planned_load_lb"] == 0, (
            f"A cancelled stop contributes nothing, got {reopened['planned_load_lb']}"
        )
        assert float(reopened["utilization_pct"]) == 0.00, (
            f"Expected 0.00, got {reopened['utilization_pct']}"
        )
        assert read_lot(lot["id"])["quantity_reserved_lb"] == 1000, (
            "Reservations survive stop cancellation"
        )


class TestOrderLinesFilteredByThePickedLot:
    """The cross-order line collection resolves lines by the lot the selector chose."""

    def test_the_lot_filter_finds_the_reserved_line_and_the_substitution_filter_finds_nothing(self):
        """PRD §3.3: "Order lines are likewise readable per order and across orders,
        filterable by `order_id`, `product_id`, `substituted_from_product_id`,
        `lot_id`, `silo_id`, `contract_line_id` and `allocation_status`."

        PRD §3.5: "Each line's `lot_id` is set to the lot the selector chose and its
        `allocation_status` becomes `RESERVED`."

        PRD §3.3: "A new line begins with `allocation_status` at `UNALLOCATED`,
        `unit_price_cents` and `extended_cents` at 0, and `lot_id`, `silo_id`,
        `contract_line_id` and `substituted_from_product_id` all null."

        Design: Corner/endpoints/corner_ep_order_lines_cross_reference_filter_by_picked_lot
        """
        customer, flour, lot = _stocked_bakery("FLR-XREF-30", lot_code="LOT-XR-0001")
        _order, line = _allocated_order(customer, flour["id"], 1000)

        rows, _meta = validate_paginated(
            api_client.list_order_lines(
                WO, params={"lot_id": lot["id"], "allocation_status": "RESERVED"}
            )
        )

        assert len(rows) == 1, (
            f"Expected exactly the one reserved line, got {len(rows)}"
        )
        found = rows[0]
        assert found["id"] == line["id"], (
            f"Expected line {line['id']}, got {found['id']}"
        )
        assert found["lot_id"] == lot["id"], (
            f"Expected the picked lot, got {found['lot_id']}"
        )
        assert found["allocation_status"] == "RESERVED", (
            f"Expected RESERVED, got {found['allocation_status']}"
        )
        assert found["unit_price_cents"] == 30, (
            f"Expected the 30 c list price, got {found['unit_price_cents']}"
        )
        assert found["extended_cents"] == 30000, (
            f"Expected 1000 lb at 30 c with no discount tier, got {found['extended_cents']}"
        )
        assert found["substituted_from_product_id"] is None, (
            f"No substitution has occurred, got {found['substituted_from_product_id']}"
        )
        assert found["silo_id"] is None, (
            f"A bagged line has no destination silo, got {found['silo_id']}"
        )
        substituted, _meta = validate_paginated(
            api_client.list_order_lines(
                WO, params={"substituted_from_product_id": flour["id"]}
            )
        )
        assert substituted == [], (
            f"The same data must yield nothing on that filter, got {len(substituted)}"
        )


class TestPricingSummaryIsDerivedNotStored:
    """The buyer's own read reproduces the settlement the submission wrote."""

    def test_the_summary_reports_the_same_four_figures_the_submission_persisted(self):
        """PRD §3.3: "a dedicated computed read exposes the pricing summary: each line's
        unit and extended price alongside the order's surcharge, rebate and total, plus
        the index quote that priced each line."

        PRD §3.4: "A line of 10000 pounds or more — the boundary is inclusive — earns
        three percent." ... "two and a half percent outside one" ... "a base of 500000
        cents or more but below 1500000 cents earns one percent"

        PRD §3.4: "Finally, `total_cents` is the subtotal plus the fuel surcharge plus
        the formulation-support attach fee, less the volume rebate."

        17000 lb at 30 c is 510000 gross, 494700 net of the three percent, 12368 of
        fuel on top, and 4947 of rebate unlocked by the 507068 base.

        Design: Corner/endpoints/corner_ep_pricing_summary_computed_read_matches_persisted_settlement
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-SUM-30"))
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        line = add_order_line(customer, order["id"], flour["id"], 17000)
        submitted = submit_order(customer, order["id"])

        summary = validate_success(
            api_client.get_order_pricing_summary(order["id"], buyer_headers(customer)),
            200,
        )

        assert summary["subtotal_cents"] == 494700, (
            f"Expected 494700, got {summary['subtotal_cents']}"
        )
        assert summary["fuel_surcharge_cents"] == 12368, (
            f"Expected 12367.5 rounded half-up to 12368, got "
            f"{summary['fuel_surcharge_cents']}"
        )
        assert summary["volume_rebate_cents"] == 4947, (
            f"Expected one percent of the subtotal, got {summary['volume_rebate_cents']}"
        )
        assert summary["total_cents"] == 502121, (
            f"Expected 494700 + 12368 - 4947, got {summary['total_cents']}"
        )
        assert summary["tech_attach_fee_cents"] == 0, (
            f"No engagement is attached, got {summary['tech_attach_fee_cents']}"
        )
        assert summary["surge_window"] is False, (
            f"A 2026-09-05 delivery sits outside both windows, got {summary['surge_window']}"
        )
        assert summary["total_cents"] == submitted["total_cents"], (
            "The derived read must agree with what the submission persisted"
        )
        assert summary["subtotal_cents"] == read_order(order["id"])["subtotal_cents"], (
            "The derived read must agree with the stored order"
        )
        priced = read_order_line(line["id"])
        assert priced["unit_price_cents"] == 30, (
            f"Expected the 30 c list price, got {priced['unit_price_cents']}"
        )
        assert priced["extended_cents"] == 494700, (
            f"Expected the discounted extension, got {priced['extended_cents']}"
        )


class TestUnsealingATwoStopRoute:
    """Sequence numbers go, the class lock stays, and the orders are not touched."""

    def test_both_sequence_numbers_clear_to_zero_while_the_gluten_lock_survives(self):
        """PRD §3.9: "Sealing assigns each stop's `sequence_no` as a one-based position
        ordered by `window_start_at` ascending then `created_at` ascending, and
        increments the route's `version` by 1. Unsealing reverses it: a `SEALED` route
        returns to `PLANNING`, every stop's `sequence_no` is cleared back to 0, and
        `version` increments by 1. The same reversal is what fires automatically as the
        fourth hop of the quarantine cascade, and when it is triggered by `stop_count`
        reaching zero the `allergen_class_lock` resets to `NONE` as well."

        PRD §3.9: "When the route's `allergen_class_lock` is still `NONE`, appending the
        first stop sets it from that order's allergen class; once set it is immutable"

        The stops are inserted late-then-early, so a sequence read from insertion order
        would invert the one sealing actually assigns.

        Design: Corner/endpoints/corner_ep_unseal_clears_sequence_but_keeps_allergen_lock
        """
        customer, flour, _lot = _stocked_bakery(
            "FLR-UNS-30", quantity_received_lb=40000, lot_code="LOT-UNS-0001"
        )
        late_order, _ = _allocated_order(customer, flour["id"], 1000)
        early_order, _ = _allocated_order(customer, flour["id"], 2000)
        route = create_route(
            route_code="R-UNS",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        late_stop = append_stop(
            route["id"], late_order["id"],
            "2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z",
        )
        early_stop = append_stop(
            route["id"], early_order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        seal_route(route["id"])
        assert read_route_stop(early_stop["id"])["sequence_no"] == 1, (
            "Window order, not insertion order, decides the sequence"
        )
        assert read_route_stop(late_stop["id"])["sequence_no"] == 2, (
            "The 14:00 stop is second even though it was inserted first"
        )

        reopened = unseal_route(route["id"])

        assert reopened["status"] == "PLANNING", (
            f"Expected PLANNING, got {reopened['status']}"
        )
        assert read_route_stop(early_stop["id"])["sequence_no"] == 0, (
            "Unsealing clears the sequence"
        )
        assert read_route_stop(late_stop["id"])["sequence_no"] == 0, (
            "Unsealing clears the sequence"
        )
        assert reopened["allergen_class_lock"] == "GLUTEN", (
            f"Two stops remain, so the lock must stand, got "
            f"{reopened['allergen_class_lock']}"
        )
        assert reopened["stop_count"] == 2, (
            f"Expected stop_count 2, got {reopened['stop_count']}"
        )
        assert reopened["planned_load_lb"] == 3000, (
            f"Expected 1000 + 2000 pounds, got {reopened['planned_load_lb']}"
        )
        assert float(reopened["utilization_pct"]) == 6.25, (
            f"Expected 3000 of 48000 as 6.25, got {reopened['utilization_pct']}"
        )
        assert read_order(early_order["id"])["fulfillment_status"] == "ROUTED", (
            "Unsealing does not touch the orders"
        )
        assert read_order(late_order["id"])["fulfillment_status"] == "ROUTED", (
            "Unsealing does not touch the orders"
        )


class TestAbortingADispatchedTrailerBeforeAnyDrop:
    """The trailer comes home, the pounds unwind, the reservations stay."""

    def test_both_stops_cancel_and_both_orders_step_back_to_allocated(self):
        """PRD §3.10: "Aborting requires the route to be `DISPATCHED` and requires that
        no stop has yet reached `DELIVERED` or `SHORTED`; the planner supplies an
        `abort_reason`. The route moves to `ABORTED`, every stop still in `PLANNED`
        becomes `CANCELLED`, every affected order steps back `LOADED → ALLOCATED` with
        its reservations retained rather than released, and `stop_count`,
        `planned_load_lb` and `utilization_pct` are all recomputed to 0."

        PRD §3.10: "A `LogisticsPlanner` moves a route `SEALED → DISPATCHED` only when
        the logical clock date equals the route's `service_on`" ... "Dispatch advances
        each stop's order `ROUTED → LOADED` and increments the route's `version` by 1."

        PRD §3.5: "On each picked lot, `quantity_reserved_lb` increases by the line's
        `quantity_lb` and `quantity_on_hand_lb` decreases by the same amount"

        Design: Corner/endpoints/corner_ep_abort_before_any_drop_unwinds_route_and_orders
        """
        customer, flour, lot = _stocked_bakery(
            "FLR-ABT-30", quantity_received_lb=40000, lot_code="LOT-ABT-0001"
        )
        order_a, line_a = _allocated_order(customer, flour["id"], 1000)
        order_b, line_b = _allocated_order(customer, flour["id"], 2000)
        route = create_route(
            route_code="R-ABRT",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        stop_a = append_stop(
            route["id"], order_a["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        stop_b = append_stop(
            route["id"], order_b["id"],
            "2026-09-10T10:00:00Z", "2026-09-10T11:00:00Z",
        )
        seal_route(route["id"])
        set_clock("2026-09-10T07:00:00Z")
        dispatched = dispatch_route(route["id"])
        assert dispatched["status"] == "DISPATCHED", (
            f"Expected DISPATCHED, got {dispatched['status']}"
        )
        assert read_order(order_a["id"])["fulfillment_status"] == "LOADED", (
            "Dispatch loads every routed order"
        )

        aborted = abort_route(
            route["id"],
            abort_reason="Trailer refrigeration unit failed at the yard gate",
        )

        assert aborted["status"] == "ABORTED", (
            f"Expected ABORTED, got {aborted['status']}"
        )
        assert read_route_stop(stop_a["id"])["status"] == "CANCELLED", (
            "Every PLANNED stop cancels"
        )
        assert read_route_stop(stop_b["id"])["status"] == "CANCELLED", (
            "Every PLANNED stop cancels"
        )
        assert read_order(order_a["id"])["fulfillment_status"] == "ALLOCATED", (
            "The order steps back one state, not to NEW"
        )
        assert read_order(order_b["id"])["fulfillment_status"] == "ALLOCATED", (
            "The order steps back one state, not to NEW"
        )
        assert aborted["stop_count"] == 0, (
            f"Expected stop_count 0, got {aborted['stop_count']}"
        )
        assert aborted["planned_load_lb"] == 0, (
            f"Expected planned_load_lb 0, got {aborted['planned_load_lb']}"
        )
        assert float(aborted["utilization_pct"]) == 0.00, (
            f"Expected 0.00, got {aborted['utilization_pct']}"
        )
        assert read_order_line(line_a["id"])["allocation_status"] == "RESERVED", (
            "Reservations are retained rather than released"
        )
        assert read_order_line(line_b["id"])["allocation_status"] == "RESERVED", (
            "Reservations are retained rather than released"
        )
        held = read_lot(lot["id"])
        assert held["quantity_reserved_lb"] == 3000, (
            f"Expected 3000 lb still reserved, got {held['quantity_reserved_lb']}"
        )
        assert held["quantity_on_hand_lb"] == 37000, (
            f"Expected 40000 less the 3000 reserved, got {held['quantity_on_hand_lb']}"
        )
        assert_lot_inventory_conservation(held)


class TestIndexQuoteListingOrder:
    """Newest effective date first, whatever the publication order was."""

    def test_the_later_effective_quote_leads_and_the_other_index_is_excluded(self):
        """PRD §3.1: "Quotes are immutable and are listed newest effective date first,
        optionally narrowed to a single `index_code`, with the usual `limit` and `offset`
        window."

        PRD §2.4: "The single exception is the published commodity index quote: a
        `CommodityIndexQuote` is an immutable market observation and carries only `id`
        and `created_at` — it has neither `updated_at` nor `version`, and no endpoint
        mutates one once published."

        The 2026-09-01 HRW quote is published last, so publication order and effective
        order disagree, and a same-date SRW quote sits between the two HRW rows.

        Design: Corner/endpoints/corner_ep_index_quote_listing_orders_newest_effective_on_first
        """
        set_clock(EPOCH)
        older = publish_index_quote(
            index_code="HRW_WHEAT",
            effective_on="2026-08-01T00:00:00Z",
            price_cents_per_lb=120,
        )
        other_index = publish_index_quote(
            index_code="SRW_WHEAT",
            effective_on="2026-09-01T00:00:00Z",
            price_cents_per_lb=111,
        )
        newer = publish_index_quote(
            index_code="HRW_WHEAT",
            effective_on="2026-09-01T00:00:00Z",
            price_cents_per_lb=140,
        )

        rows, _meta = validate_paginated(
            api_client.list_index_quotes(
                AM, params={"index_code": "HRW_WHEAT", "limit": 10, "offset": 0}
            )
        )

        assert len(rows) == 2, (
            f"Expected only the two HRW quotes, got {len(rows)}"
        )
        assert rows[0]["id"] == newer["id"], (
            "The 2026-09-01 quote leads despite being published last"
        )
        assert rows[0]["price_cents_per_lb"] == 140, (
            f"Expected 140, got {rows[0]['price_cents_per_lb']}"
        )
        assert rows[1]["id"] == older["id"], (
            f"Expected the 2026-08-01 quote second, got {rows[1]['id']}"
        )
        assert rows[1]["price_cents_per_lb"] == 120, (
            f"Expected 120, got {rows[1]['price_cents_per_lb']}"
        )
        assert other_index["id"] not in [row["id"] for row in rows], (
            "The SRW quote must be filtered out"
        )
        for row in rows:
            assert "version" not in row, (
                "An immutable market observation carries no version"
            )
            assert "updated_at" not in row, (
                "An immutable market observation carries no updated_at"
            )
