"""The quarantine cascade, the drop siblings and the settlement ledger (PRD §3.7, §3.10, §3.11)."""

from test_helpers import (
    FLOUR_HRW_LIST_ONLY,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    assert_lot_inventory_conservation,
    create_customer,
    create_product,
    create_route,
    create_zone,
    credit_limit_adjustment_payload,
    deallocate_order,
    deliver_stop,
    dispatch_route,
    open_order,
    quarantine_lot,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    read_zone,
    receive_lot,
    seal_route,
    set_clock,
    short_stop,
    submit_order,
    validate_success,
)
from test_helpers.fixtures import AM, PC

BREAD_FLOUR = dict(
    FLOUR_HRW_LIST_ONLY,
    sku="FLR-BREAD-50",
    list_price_cents_per_lb=30,
    min_rotation_days=0,
)


def _allocated_order(quantity_lb=1000, credit_limit_cents=5000000):
    """A submitted, allocated bagged order against a single 40000 lb GLUTEN lot."""
    set_clock("2026-08-01T00:00:00Z")
    customer = create_customer(
        credit_limit_cents=credit_limit_cents, min_drop_cents=25000
    )
    flour = create_product(BREAD_FLOUR)
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    lot = receive_lot(
        flour["id"],
        zone["id"],
        lot_code="LOT-A-0001",
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=40000,
    )
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on="2026-09-10T00:00:00Z",
    )
    line = add_order_line(customer, order["id"], flour["id"], quantity_lb)
    submitted = submit_order(customer, order["id"])
    allocate_order(order["id"])
    return {
        "customer": customer,
        "flour": flour,
        "zone": zone,
        "lot": lot,
        "order": submitted,
        "order_line": line,
    }


def _sealed_route_over(scenario, route_code="R-SEAL"):
    """One stop covering the scenario's order, then the trailer sealed."""
    route = create_route(
        route_code=route_code,
        service_on="2026-09-10T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    stop = append_stop(
        route["id"],
        scenario["order"]["id"],
        "2026-09-10T08:00:00Z",
        "2026-09-10T09:00:00Z",
    )
    seal_route(route["id"])
    return read_route(route["id"]), stop


class TestQuarantineCascadeInnerHops:
    """Hops one and two: the reservation unwinds even with no trailer in sight."""

    def test_a_quality_hold_releases_the_line_and_walks_the_order_back_to_new(self):
        """PRD §3.7: "**Hop one:** every order line whose `lot_id` is this lot and
        whose `allocation_status` is `RESERVED` flips back to `UNALLOCATED`; the
        lot's `quantity_reserved_lb` decreases by that line's `quantity_lb` and its
        `quantity_on_hand_lb` increases by the same amount, conserving the lot's
        totals. **Hop two:** because those lines became `UNALLOCATED`, each parent
        order whose `fulfillment_status` is `ALLOCATED` or `ROUTED` reverts to
        `NEW`."

        PRD §3.7: "The quarantine also recomputes the storage zone's `on_hand_lb`."

        Design: Corner/state_machines/corner_quarantine_cascades_release_of_reserved_order_line
        """
        scenario = _allocated_order()
        assert read_lot(scenario["lot"]["id"])["quantity_reserved_lb"] == 1000

        held = quarantine_lot(
            scenario["lot"]["id"],
            quarantine_reason="Supplier recall notice on the mill run",
        )

        assert held["status"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {held['status']}"
        )
        assert held["quarantine_reason"] == "Supplier recall notice on the mill run", (
            f"Expected the reason recorded, got {held['quarantine_reason']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {line['allocation_status']}"
        )
        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "NEW", (
            f"Expected the order back at NEW, got {order['fulfillment_status']}"
        )
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected the commercial dimension untouched, got {order['pricing_status']}"
        )
        assert order["total_cents"] == 30750, (
            f"The cascade touches inventory only, so expected 30750, got {order['total_cents']}"
        )
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_on_hand_lb"] == 40000, (
            f"Expected the pounds back on hand, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected nothing left reserved, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_consumed_lb"] == 0, (
            f"Expected nothing consumed, got {lot['quantity_consumed_lb']}"
        )
        assert lot["quantity_received_lb"] == 40000
        assert_lot_inventory_conservation(lot)
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 40000, (
            "A quarantined lot still counts towards its zone's on-hand pounds"
        )


class TestQuarantineCascadeOuterHops:
    """Hops three and four: the cancellation bubbles up through the trailer."""

    def test_the_hold_cancels_the_only_stop_and_unseals_the_trailer(self):
        """PRD §3.7: "**Hop three:** because those orders left `ROUTED`, each of
        their route stops still in `PLANNED` flips to `CANCELLED`, and the owning
        route recomputes `planned_load_lb`, `utilization_pct` and `stop_count`.
        **Hop four:** because `stop_count` has reached zero on a route whose
        `status` was `SEALED`, that route reverts to `PLANNING` and its
        `allergen_class_lock` resets to `NONE`."

        PRD §3.9: "When the route's `allergen_class_lock` is still `NONE`, appending
        the first stop sets it from that order's allergen class".

        Design: Corner/state_machines/corner_quarantine_cascade_reverts_sealed_route_to_planning
        """
        scenario = _allocated_order()
        route, stop = _sealed_route_over(scenario)
        assert route["status"] == "SEALED", (
            f"Expected SEALED before the hold, got {route['status']}"
        )
        assert route["allergen_class_lock"] == "GLUTEN", (
            f"Expected the trailer locked to GLUTEN, got {route['allergen_class_lock']}"
        )
        assert route["stop_count"] == 1, (
            f"Expected stop_count 1, got {route['stop_count']}"
        )
        assert float(route["utilization_pct"]) == 4.17, (
            f"Expected 1000 of 24000 lb to read 4.17, got {route['utilization_pct']}"
        )

        held = quarantine_lot(
            scenario["lot"]["id"],
            quarantine_reason="Allergen swab failed on the storage bay",
        )

        assert held["status"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {held['status']}"
        )
        assert read_route_stop(stop["id"])["status"] == "CANCELLED", (
            "A planned stop cannot survive its order leaving ROUTED"
        )
        after = read_route(route["id"])
        assert after["status"] == "PLANNING", (
            f"Expected the trailer unsealed back to PLANNING, got {after['status']}"
        )
        assert after["allergen_class_lock"] == "NONE", (
            f"Expected the allergen lock cleared, got {after['allergen_class_lock']}"
        )
        assert after["stop_count"] == 0, (
            f"Expected stop_count 0, got {after['stop_count']}"
        )
        assert after["planned_load_lb"] == 0, (
            f"Expected planned_load_lb 0, got {after['planned_load_lb']}"
        )
        assert float(after["utilization_pct"]) == 0, (
            f"Expected utilization_pct 0, got {after['utilization_pct']}"
        )
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "NEW", (
            "The order reverts on hop two, before the stop is cancelled on hop three"
        )
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_on_hand_lb"] == 40000, (
            f"Expected the pounds back on hand, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected nothing left reserved, got {lot['quantity_reserved_lb']}"
        )


class TestDeallocationKeepsTheAccountFigures:
    """The inventory inverse runs while both money and risk stay put."""

    def test_releasing_the_reservation_restores_the_buckets_but_not_the_score(self):
        """PRD §3.5: "Each line's `allocation_status` returns to `UNALLOCATED` with
        `lot_id` and `silo_id` cleared to null; on each released lot,
        `quantity_reserved_lb` decreases by the line's `quantity_lb` and
        `quantity_on_hand_lb` increases by the same amount, while
        `quantity_received_lb` is untouched."

        PRD §3.7: "The **in-flight** variant is used on allocation, on
        deallocation, and on substitution approval; its input set is the order lines
        whose owning order has `fulfillment_status` in `NEW`, `ALLOCATED`, `ROUTED`
        or `LOADED`."

        The line returns as `UNALLOCATED` on an order that returns to `NEW`, so it
        never leaves the in-flight input set and the gluten weight keeps the score at
        55.00.

        Design: Corner/state_machines/corner_deallocate_restores_lot_buckets_and_keeps_provisional_risk
        """
        scenario = _allocated_order()

        deallocated = deallocate_order(scenario["order"]["id"])

        assert deallocated["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {deallocated['fulfillment_status']}"
        )
        line = read_order_line(scenario["order_line"]["id"])
        assert line["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {line['allocation_status']}"
        )
        assert line["lot_id"] is None, f"Expected lot_id null, got {line['lot_id']}"
        assert line["silo_id"] is None, f"Expected silo_id null, got {line['silo_id']}"
        released = read_lot(scenario["lot"]["id"])
        assert released["quantity_on_hand_lb"] == 40000, (
            f"Expected on hand back at 40000, got {released['quantity_on_hand_lb']}"
        )
        assert released["quantity_reserved_lb"] == 0, (
            f"Expected reserved back at 0, got {released['quantity_reserved_lb']}"
        )
        assert released["quantity_consumed_lb"] == 0, (
            f"Expected consumed still 0, got {released['quantity_consumed_lb']}"
        )
        assert released["status"] == "AVAILABLE", (
            f"Expected the lot still AVAILABLE, got {released['status']}"
        )
        assert_lot_inventory_conservation(released)
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 40000
        customer = read_customer(scenario["customer"]["id"])
        assert float(customer["allergen_risk_score"]) == 55.00, (
            f"Expected the score held at 55.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {customer['risk_tier']}"
        )
        assert customer["open_exposure_cents"] == 30750, (
            f"Expected exposure 30750, got {customer['open_exposure_cents']}"
        )
        assert read_order(scenario["order"]["id"])["total_cents"] == 30750


def _dispatched_four_thousand_pound_order(route_code="R-DELV"):
    """4000 lb at 30 cents: 118200 after the 1.5% discount, 2955 surcharge, 121155 total."""
    scenario = _allocated_order(quantity_lb=4000)
    route, stop = _sealed_route_over(scenario, route_code=route_code)
    set_clock("2026-09-10T06:00:00Z")
    dispatch_route(route["id"])
    scenario["route"] = read_route(route["id"])
    scenario["route_stop"] = stop
    return scenario


class TestFullDropCompletesTheRoute:
    """The parent route's terminal state is derived from its stops, not requested."""

    def test_delivering_the_only_stop_completes_the_route_without_depleting_the_lot(self):
        """PRD §3.10: "When every non-cancelled stop on the route has reached
        `DELIVERED` or `SHORTED` — equivalently, when no stop remains in `PLANNED` —
        the route moves `DISPATCHED → COMPLETED`, recomputing `planned_load_lb` and
        `utilization_pct` from delivered pounds only and incrementing `version` by
        1."

        PRD §3.10: "Every line's `allocation_status` becomes `SHIPPED`, and each
        line's picked lot moves the line's pounds out of `quantity_reserved_lb` and
        into `quantity_consumed_lb`."

        PRD §3.7: "Separately, when a delivery consumes the last on-hand pound so
        that an `AVAILABLE` lot holds `quantity_on_hand_lb` of zero and
        `quantity_reserved_lb` of zero, the lot moves itself to `DEPLETED`".

        Design: Corner/state_machines/corner_last_stop_delivery_auto_completes_route_and_depletes_nothing
        """
        scenario = _dispatched_four_thousand_pound_order()
        assert scenario["order"]["total_cents"] == 121155, (
            f"Expected total 121155, got {scenario['order']['total_cents']}"
        )
        assert read_order(scenario["order"]["id"])["fulfillment_status"] == "LOADED"

        delivered = deliver_stop(scenario["route_stop"]["id"])

        assert delivered["status"] == "DELIVERED", (
            f"Expected DELIVERED, got {delivered['status']}"
        )
        assert read_route(scenario["route"]["id"])["status"] == "COMPLETED", (
            "No stop remains in PLANNED, so the route derives itself to COMPLETED"
        )
        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "DELIVERED", (
            f"Expected DELIVERED, got {order['fulfillment_status']}"
        )
        assert order["delivered_on"] == "2026-09-10T00:00:00Z", (
            f"Expected delivered_on stamped from the clock, got {order['delivered_on']}"
        )
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected the commercial dimension still open, got {order['pricing_status']}"
        )
        assert order["total_cents"] == 121155, (
            f"Expected total 121155, got {order['total_cents']}"
        )
        assert read_order_line(scenario["order_line"]["id"])["allocation_status"] == "SHIPPED"
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_consumed_lb"] == 4000, (
            f"Expected 4000 lb consumed, got {lot['quantity_consumed_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected nothing left reserved, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_on_hand_lb"] == 36000, (
            f"Expected 36000 lb still on hand, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["status"] == "AVAILABLE", (
            f"36000 lb remain on hand, so the lot cannot be DEPLETED, got {lot['status']}"
        )
        assert_lot_inventory_conservation(lot)
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 36000
        customer = read_customer(scenario["customer"]["id"])
        assert float(customer["allergen_risk_score"]) == 55.00, (
            f"Expected the closed-book gluten score 55.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {customer['risk_tier']}"
        )


class TestShortDropSplitsThePounds:
    """The sibling confirmation moves the same reservation two ways at once."""

    def test_a_partial_drop_consumes_what_landed_and_returns_the_rest(self):
        """PRD §3.10: "The stop moves to `SHORTED` and the order `LOADED →
        SHORT_SHIPPED`, with `short_ship_lb` set to the order's total requested
        pounds less the delivered total."

        PRD §3.10: "only the delivered pounds move from `quantity_reserved_lb` into
        `quantity_consumed_lb`, while the shorted pounds return to
        `quantity_on_hand_lb` and become pickable again."

        PRD §3.10: "the bakery's `allergen_risk_score` is recomputed on the
        closed-book basis, and the route moves `DISPATCHED → COMPLETED` under the
        same aggregate condition as above."

        Design: Corner/state_machines/corner_short_drop_returns_pounds_to_lot_and_sets_short_ship_lb
        """
        scenario = _dispatched_four_thousand_pound_order(route_code="R-SHORT")

        shorted = short_stop(
            scenario["route_stop"]["id"],
            1500,
            short_reason="Vehicle breakdown forced a partial drop",
        )

        assert shorted["status"] == "SHORTED", (
            f"Expected SHORTED, got {shorted['status']}"
        )
        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "SHORT_SHIPPED", (
            f"Expected SHORT_SHIPPED, got {order['fulfillment_status']}"
        )
        assert order["short_ship_lb"] == 2500, (
            f"Expected 4000 requested less 1500 delivered, got {order['short_ship_lb']}"
        )
        assert order["delivered_on"] == "2026-09-10T00:00:00Z", (
            f"Expected delivered_on stamped from the clock, got {order['delivered_on']}"
        )
        assert order["total_cents"] == 121155, (
            f"A short drop does not reprice the order, got {order['total_cents']}"
        )
        assert read_order_line(scenario["order_line"]["id"])["allocation_status"] == "SHIPPED"
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_consumed_lb"] == 1500, (
            f"Expected only the delivered pounds consumed, got {lot['quantity_consumed_lb']}"
        )
        assert lot["quantity_on_hand_lb"] == 38500, (
            f"Expected the shorted pounds pickable again, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected nothing left reserved, got {lot['quantity_reserved_lb']}"
        )
        assert (
            lot["quantity_on_hand_lb"]
            + lot["quantity_reserved_lb"]
            + lot["quantity_consumed_lb"]
            == 40000
        ), "The split must conserve the received pounds"
        assert_lot_inventory_conservation(lot)
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 38500
        assert read_route(scenario["route"]["id"])["status"] == "COMPLETED", (
            "A shorted stop closes the route under the same aggregate condition"
        )
        shorted_customer = read_customer(scenario["customer"]["id"])
        assert float(shorted_customer["allergen_risk_score"]) == 55.00, (
            f"Expected 55.00, got {shorted_customer['allergen_risk_score']}"
        )
        assert shorted_customer["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {shorted_customer['risk_tier']}"
        )


class TestInvoicingDrainsTheExposureLedger:
    """The only event that removes a priced order from the exposure aggregation."""

    def test_closing_the_book_empties_the_exposure_and_releases_the_credit_hold(self):
        """PRD §3.11: "Invoicing freezes `total_cents` — any subsequent repricing
        attempt is rejected — and recomputes `open_exposure_cents`, from which the
        now-invoiced order drops out entirely. That recomputation is often what
        rescues an account: a bakery sitting on `CREDIT_HOLD` whose recomputed
        exposure has fallen to or below its `credit_limit_cents` returns to `ACTIVE`,
        and its buyer can submit again."

        PRD §3.4: "A bakery's `open_exposure_cents` is the total of `total_cents`
        over every one of its orders whose `pricing_status` is either `PROVISIONAL`
        or `FINAL`; orders that are `UNPRICED`, `INVOICED` or `VOID` contribute
        nothing."

        Design: Corner/state_machines/corner_invoice_drains_open_exposure_and_lifts_credit_hold
        """
        scenario = _allocated_order(quantity_lb=4000)
        held = validate_success(
            api_client.adjust_credit_limit(
                scenario["customer"]["id"],
                credit_limit_adjustment_payload(
                    100000, reason="Trade insurer reduced the covered line"
                ),
                AM,
            )
        )
        assert held["status"] == "CREDIT_HOLD", (
            f"121155 of exposure exceeds the lowered 100000 limit, got {held['status']}"
        )
        assert held["open_exposure_cents"] == 121155, (
            f"Expected exposure 121155, got {held['open_exposure_cents']}"
        )
        route, stop = _sealed_route_over(scenario, route_code="R-INV")
        set_clock("2026-09-10T06:00:00Z")
        dispatch_route(route["id"])
        deliver_stop(stop["id"])
        final = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC)
        )
        assert final["pricing_status"] == "FINAL", (
            f"Expected FINAL before the invoice, got {final['pricing_status']}"
        )
        assert read_customer(scenario["customer"]["id"])["status"] == "CREDIT_HOLD", (
            "A FINAL order still sits inside the exposure aggregation"
        )

        invoiced = validate_success(
            api_client.invoice_order(scenario["order"]["id"], {}, PC)
        )

        assert invoiced["pricing_status"] == "INVOICED", (
            f"Expected INVOICED, got {invoiced['pricing_status']}"
        )
        assert invoiced["fulfillment_status"] == "DELIVERED", (
            f"Expected the physical dimension untouched, got {invoiced['fulfillment_status']}"
        )
        assert invoiced["subtotal_cents"] == 118200, (
            f"Expected subtotal 118200, got {invoiced['subtotal_cents']}"
        )
        assert invoiced["fuel_surcharge_cents"] == 2955, (
            f"Expected surcharge 2955, got {invoiced['fuel_surcharge_cents']}"
        )
        assert invoiced["volume_rebate_cents"] == 0, (
            f"A 121155 rebate base earns nothing, got {invoiced['volume_rebate_cents']}"
        )
        assert invoiced["total_cents"] == 121155, (
            f"Expected the frozen total 121155, got {invoiced['total_cents']}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 0, (
            f"Expected the ledger drained to 0, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE", (
            f"Expected the account rescued to ACTIVE, got {customer['status']}"
        )
        assert customer["credit_limit_cents"] == 100000, (
            f"Expected the lowered limit to stand, got {customer['credit_limit_cents']}"
        )
