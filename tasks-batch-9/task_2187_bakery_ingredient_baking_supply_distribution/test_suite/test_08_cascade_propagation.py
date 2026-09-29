"""The three declared multi-hop cascades (PRD §2.10, §3.7, §3.8, §3.3)."""

from test_helpers import (
    ALMOND_FLOUR,
    FLOUR_HRW_LIST_ONLY,
    RICE_FLOUR,
    add_order_line,
    allocate_order,
    approve_substitution_request,
    cancel_order,
    claim_substitution_request,
    create_customer,
    create_product,
    create_zone,
    open_order,
    quarantine_lot,
    raise_substitution_request,
    read_contract,
    read_contract_line,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    receive_lot,
    seal_route,
    set_clock,
    setup_contracted_order,
    submit_order,
    append_stop,
    create_route,
    assert_lot_inventory_conservation,
)


def _sealed_route_over_one_flour_order():
    """15000 lb of bagged flour, allocated, routed and sealed on a 24000 lb trailer."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer()
    product = create_product(FLOUR_HRW_LIST_ONLY)
    zone = create_zone(allergen_class="GLUTEN")
    lot = receive_lot(product["id"], zone["id"], quantity_received_lb=50000)
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], product["id"], 15000)
    submitted = submit_order(customer, order["id"])
    allocate_order(order["id"])
    route = create_route(service_on="2026-09-15T00:00:00Z", vehicle_capacity_lb=24000)
    stop = append_stop(
        route["id"], order["id"], "2026-09-15T08:00:00Z", "2026-09-15T10:00:00Z"
    )
    sealed = seal_route(route["id"])
    return {
        "customer": customer,
        "product": product,
        "zone": zone,
        "lot": lot,
        "order": order,
        "order_line": line,
        "submitted": submitted,
        "route": sealed,
        "route_stop": stop,
    }


class TestLotQuarantineCascade:
    """One quarantine call unwinds lines, orders, stops and the sealed route."""

    def test_quarantine_returns_the_reserved_pounds_and_reverts_the_order(self):
        """PRD §3.7: "**Hop one:** every order line whose `lot_id` is this lot and
        whose `allocation_status` is `RESERVED` flips back to `UNALLOCATED`; the
        lot's `quantity_reserved_lb` decreases by that line's `quantity_lb` and
        its `quantity_on_hand_lb` increases by the same amount, conserving the
        lot's totals."

        PRD §3.7: "**Hop two:** because those lines became `UNALLOCATED`, each parent
        order whose `fulfillment_status` is `ALLOCATED` or `ROUTED` reverts to
        `NEW`."

        Design: Difficulty/transitive_cascade/lot_quarantine_four_hop_cascade_unseals_route_and_reverts_order
        """
        scenario = _sealed_route_over_one_flour_order()
        assert scenario["submitted"]["total_cents"] == 620267, (
            f"Expected total 620267, got {scenario['submitted']['total_cents']}"
        )
        assert scenario["route"]["status"] == "SEALED"

        quarantine_lot(scenario["lot"]["id"])

        lot = read_lot(scenario["lot"]["id"])
        assert lot["status"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {lot['status']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected reserved back at 0, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_on_hand_lb"] == 50000, (
            f"Expected on-hand back at 50000, got {lot['quantity_on_hand_lb']}"
        )
        assert_lot_inventory_conservation(lot)
        line = read_order_line(scenario["order_line"]["id"])
        assert line["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {line['allocation_status']}"
        )
        assert line["lot_id"] is None or line["lot_id"] == scenario["lot"]["id"]
        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "NEW", (
            f"Expected the order back at NEW, got {order['fulfillment_status']}"
        )
        assert order["pricing_status"] == "PROVISIONAL", (
            "The commercial dimension is untouched by the quarantine cascade"
        )
        assert order["total_cents"] == 620267

    def test_quarantine_cancels_the_planned_stop_and_unseals_the_empty_route(self):
        """PRD §3.7: "**Hop three:** because those orders left `ROUTED`, each of their
        route stops still in `PLANNED` flips to `CANCELLED`, and the owning route
        recomputes `planned_load_lb`, `utilization_pct` and `stop_count`."

        PRD §3.7: "**Hop four:** because `stop_count` has reached zero on a route
        whose `status` was `SEALED`, that route reverts to `PLANNING` and its
        `allergen_class_lock` resets to `NONE`."

        Design: Difficulty/transitive_cascade/lot_quarantine_four_hop_cascade_unseals_route_and_reverts_order
        """
        scenario = _sealed_route_over_one_flour_order()
        assert scenario["route"]["allergen_class_lock"] == "GLUTEN", (
            f"Expected the trailer locked to GLUTEN, got {scenario['route']['allergen_class_lock']}"
        )
        assert float(scenario["route"]["utilization_pct"]) == 62.50, (
            f"Expected 15000 of 24000 lb to read 62.50, got {scenario['route']['utilization_pct']}"
        )

        quarantine_lot(scenario["lot"]["id"])

        stop = read_route_stop(scenario["route_stop"]["id"])
        assert stop["status"] == "CANCELLED", (
            f"Expected the stop CANCELLED, got {stop['status']}"
        )
        route = read_route(scenario["route"]["id"])
        assert route["status"] == "PLANNING", (
            f"Expected the route back at PLANNING, got {route['status']}"
        )
        assert route["stop_count"] == 0, (
            f"Expected stop_count 0, got {route['stop_count']}"
        )
        assert route["planned_load_lb"] == 0, (
            f"Expected planned_load_lb 0, got {route['planned_load_lb']}"
        )
        assert float(route["utilization_pct"]) == 0.00, (
            f"Expected utilization_pct 0.00, got {route['utilization_pct']}"
        )
        assert route["allergen_class_lock"] == "NONE", (
            f"Expected the allergen lock cleared, got {route['allergen_class_lock']}"
        )


def _claimed_swap_from_rice_to_almond():
    """3000 lb of rice flour allocated, with a tree-nut swap under review.

    The bakery's credit limit is deliberately 1000000 cents so the repriced
    order overshoots it, and its only in-flight line is the one being swapped.
    """
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=1000000, min_drop_cents=25000)
    rice = create_product(RICE_FLOUR)
    almond = create_product(ALMOND_FLOUR)
    rice_zone = create_zone(allergen_class="NONE")
    nut_zone = create_zone(allergen_class="TREE_NUT")
    rice_lot = receive_lot(rice["id"], rice_zone["id"], quantity_received_lb=20000)
    almond_lot = receive_lot(
        almond["id"],
        nut_zone["id"],
        quantity_received_lb=10000,
        manufactured_on="2026-07-20T00:00:00Z",
    )
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], rice["id"], 3000)
    submitted = submit_order(customer, order["id"])
    allocate_order(order["id"])
    request = raise_substitution_request(
        line["id"], almond["id"], read_order(order["id"])["version"], specialist_user_id="ts-1"
    )
    claim_substitution_request(request["id"], manager_user_id="qm-1")
    return {
        "customer": customer,
        "rice": rice,
        "almond": almond,
        "rice_lot": rice_lot,
        "almond_lot": almond_lot,
        "order": order,
        "order_line": line,
        "submitted": submitted,
        "request": request,
    }


class TestSubstitutionApprovalCascade:
    """One approve call rewrites the line, re-picks stock, reprices and rescores."""

    def test_approval_swaps_the_line_and_moves_the_reservation_to_the_new_lot(self):
        """PRD §3.8: "**Hop one:** the order line's current `product_id` is copied
        into `substituted_from_product_id`, and `product_id` becomes the
        request's `proposed_product_id`."

        PRD §3.8: "the line's `allocation_status` becomes `RELEASED` and the old
        lot returns the line's pounds from `quantity_reserved_lb` to
        `quantity_on_hand_lb` — and the rotation selector of §3.5 re-picks a lot
        of the new product and re-reserves it".

        Design: Difficulty/transitive_cascade/substitution_approval_five_hop_cascade_reprices_flips_credit_hold_and_risk_tier
        """
        scenario = _claimed_swap_from_rice_to_almond()
        assert scenario["submitted"]["total_cents"] == 266541, (
            f"Expected the rice order at 266541, got {scenario['submitted']['total_cents']}"
        )

        approved = approve_substitution_request(scenario["request"]["id"], manager_user_id="qm-1")

        assert approved["status"] == "APPROVED", (
            f"Expected APPROVED, got {approved['status']}"
        )
        assert approved["decided_by_user_id"] == "qm-1"
        line = read_order_line(scenario["order_line"]["id"])
        assert line["product_id"] == scenario["almond"]["id"], (
            f"Expected the line to carry the almond SKU, got {line['product_id']}"
        )
        assert line["substituted_from_product_id"] == scenario["rice"]["id"], (
            f"Expected the rice SKU recorded as substituted-from, got {line['substituted_from_product_id']}"
        )
        assert line["lot_id"] == scenario["almond_lot"]["id"], (
            f"Expected the line re-picked onto the almond lot, got {line['lot_id']}"
        )
        rice_lot = read_lot(scenario["rice_lot"]["id"])
        assert rice_lot["quantity_reserved_lb"] == 0, (
            f"Expected the rice lot fully released, got {rice_lot['quantity_reserved_lb']}"
        )
        assert rice_lot["quantity_on_hand_lb"] == 20000, (
            f"Expected the rice lot back at 20000, got {rice_lot['quantity_on_hand_lb']}"
        )
        almond_lot = read_lot(scenario["almond_lot"]["id"])
        assert almond_lot["quantity_reserved_lb"] == 3000, (
            f"Expected 3000 lb reserved on the almond lot, got {almond_lot['quantity_reserved_lb']}"
        )
        assert almond_lot["quantity_on_hand_lb"] == 7000, (
            f"Expected the almond lot down to 7000, got {almond_lot['quantity_on_hand_lb']}"
        )
        assert_lot_inventory_conservation(rice_lot)
        assert_lot_inventory_conservation(almond_lot)

    def test_approval_reprices_the_order_then_flips_credit_and_risk_standing(self):
        """PRD §3.8: "**Hop three:** because the line's product and unit price
        changed, the order is repriced through the `PROVISIONAL` self-loop,
        changing `subtotal_cents`, `volume_rebate_cents` and `total_cents`."

        PRD §3.8: "**Hop four:** because `total_cents` changed, the bakery's
        `open_exposure_cents` is recomputed, and if it now exceeds
        `credit_limit_cents` the bakery moves `ACTIVE → CREDIT_HOLD`."

        3000 lb of almond flour at 890 cents less the one-and-a-half percent
        band gives a subtotal of 2629950, and at that size the 65749 cent
        surcharge and the 65749 cent rebate cancel exactly.

        Design: Difficulty/transitive_cascade/substitution_approval_five_hop_cascade_reprices_flips_credit_hold_and_risk_tier
        """
        scenario = _claimed_swap_from_rice_to_almond()
        before = read_customer(scenario["customer"]["id"])
        assert before["open_exposure_cents"] == 266541
        assert float(before["allergen_risk_score"]) == 0.00
        assert before["risk_tier"] == "GREEN"
        assert before["status"] == "ACTIVE"

        approve_substitution_request(scenario["request"]["id"], manager_user_id="qm-1")

        order = read_order(scenario["order"]["id"])
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected the reprice self-loop to stay PROVISIONAL, got {order['pricing_status']}"
        )
        assert order["subtotal_cents"] == 2629950, (
            f"Expected subtotal 2629950, got {order['subtotal_cents']}"
        )
        assert order["fuel_surcharge_cents"] == 65749, (
            f"Expected surcharge 65749, got {order['fuel_surcharge_cents']}"
        )
        assert order["volume_rebate_cents"] == 65749, (
            f"Expected rebate 65749, got {order['volume_rebate_cents']}"
        )
        assert order["total_cents"] == 2629950, (
            f"Expected total 2629950, got {order['total_cents']}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 2629950, (
            f"Expected exposure 2629950, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "CREDIT_HOLD", (
            f"Expected CREDIT_HOLD above the 1000000 limit, got {customer['status']}"
        )
        assert float(customer["allergen_risk_score"]) == 90.00, (
            f"Expected the tree-nut score 90.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "RED", (
            f"Expected RED, got {customer['risk_tier']}"
        )


def _allocated_order_that_exhausted_its_contract():
    """A 20000 lb draw against a 20000 lb commitment, so the contract exhausts."""
    set_clock("2026-08-05T00:00:00Z")
    scenario = setup_contracted_order(
        volume_committed_lb=20000,
        basis_cents_per_lb=6,
        pricing_mode="ORDER_DATE_INDEX",
        quantity_lb=20000,
        index_price_cents_per_lb=38,
        quote_effective_on="2026-08-01T00:00:00Z",
    )
    scenario["submitted"] = submit_order(scenario["customer"], scenario["order"]["id"])
    allocate_order(scenario["order"]["id"])
    return scenario


class TestOrderCancellationCascade:
    """Cancellation gives the pounds back in both directions."""

    def test_cancellation_voids_pricing_releases_stock_and_clears_exposure(self):
        """PRD §3.3: "Cancellation drives both dimensions at once:
        `fulfillment_status` becomes `CANCELLED` and `pricing_status` becomes
        `VOID` — a transition available from either `UNPRICED` or `PROVISIONAL`."

        PRD §3.3: "All reservations are released exactly as in a deallocation,
        every contract line's `volume_drawn_lb` is reduced by the pounds this
        order drew, and `subtotal_cents`, `fuel_surcharge_cents`,
        `volume_rebate_cents`, `tech_attach_fee_cents` and `total_cents` all
        reset to 0."

        Design: Difficulty/transitive_cascade/order_cancel_three_hop_cascade_returns_volume_and_revives_exhausted_contract
        """
        scenario = _allocated_order_that_exhausted_its_contract()
        assert scenario["submitted"]["total_cents"] == 866404, (
            f"Expected the indexed order at 866404, got {scenario['submitted']['total_cents']}"
        )
        assert read_order_line(scenario["order_line"]["id"])["unit_price_cents"] == 44, (
            "The 38 cent print plus a 6 cent basis settles at 44 cents per pound"
        )

        cancelled = cancel_order(scenario["customer"], scenario["order"]["id"])

        assert cancelled["fulfillment_status"] == "CANCELLED", (
            f"Expected CANCELLED, got {cancelled['fulfillment_status']}"
        )
        assert cancelled["pricing_status"] == "VOID", (
            f"Expected VOID, got {cancelled['pricing_status']}"
        )
        assert cancelled["total_cents"] == 0, (
            f"Expected total reset to 0, got {cancelled['total_cents']}"
        )
        assert cancelled["subtotal_cents"] == 0
        assert cancelled["fuel_surcharge_cents"] == 0
        assert cancelled["volume_rebate_cents"] == 0
        line = read_order_line(scenario["order_line"]["id"])
        assert line["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {line['allocation_status']}"
        )
        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_on_hand_lb"] == 50000, (
            f"Expected on-hand back at 50000, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0
        assert_lot_inventory_conservation(lot)
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 0, (
            f"Expected exposure back at 0, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE"

    def test_returned_volume_moves_the_contract_back_from_exhausted_to_active(self):
        """PRD §3.2: "when returned volume leaves at least one line with
        `volume_drawn_lb` strictly below its `volume_committed_lb`, an
        `EXHAUSTED` contract moves back to `ACTIVE`, provided its `term_end_on`
        is on or after the logical clock date, again recomputing
        `drawn_volume_lb` and incrementing `version`."

        Design: Difficulty/transitive_cascade/order_cancel_three_hop_cascade_returns_volume_and_revives_exhausted_contract
        """
        scenario = _allocated_order_that_exhausted_its_contract()
        before = read_contract(scenario["contract"]["id"])
        assert before["status"] == "EXHAUSTED", (
            f"Expected the full draw to exhaust the contract, got {before['status']}"
        )
        assert before["drawn_volume_lb"] == 20000, (
            f"Expected drawn_volume_lb 20000, got {before['drawn_volume_lb']}"
        )

        cancel_order(scenario["customer"], scenario["order"]["id"])

        contract_line = read_contract_line(scenario["contract_line"]["id"])
        assert contract_line["volume_drawn_lb"] == 0, (
            f"Expected the commitment line back at 0 drawn, got {contract_line['volume_drawn_lb']}"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["drawn_volume_lb"] == 0, (
            f"Expected drawn_volume_lb 0, got {contract['drawn_volume_lb']}"
        )
        assert contract["committed_volume_lb"] == 20000, (
            f"Expected the commitment untouched at 20000, got {contract['committed_volume_lb']}"
        )
        assert contract["status"] == "ACTIVE", (
            f"Expected the contract revived to ACTIVE, got {contract['status']}"
        )
