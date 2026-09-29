"""Forward action then compensating action on three separate ledgers (PRD §2.9, §3.5, §3.10)."""

from test_helpers import (
    FLOUR_HRW_LIST_ONLY,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    assert_lot_inventory_conservation,
    cancel_order,
    create_customer,
    create_product,
    create_route,
    create_zone,
    credit_limit_adjustment_payload,
    deallocate_order,
    dispatch_route,
    open_order,
    read_contract,
    read_contract_line,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_zone,
    receive_lot,
    seal_route,
    set_clock,
    setup_contracted_order,
    short_stop,
    submit_order,
    validate_success,
)
from test_helpers.fixtures import AM


def _submitted_order_ready_to_allocate():
    """15000 lb of bagged flour priced at 620267 cents against a 50000 lb lot."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=5000000, min_drop_cents=25000)
    flour = create_product(FLOUR_HRW_LIST_ONLY)
    zone = create_zone(allergen_class="GLUTEN")
    lot = receive_lot(flour["id"], zone["id"], quantity_received_lb=50000)
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], flour["id"], 15000)
    submitted = submit_order(customer, order["id"])
    return {
        "customer": customer,
        "flour": flour,
        "zone": zone,
        "lot": lot,
        "order": submitted,
        "order_line": line,
    }


class TestPoundsOfInventoryRoundTrip:
    """Conserved ledger one: the three pound buckets on a lot."""

    def test_deallocation_puts_each_pound_bucket_back_where_it_started(self):
        """PRD §2.9: "A forward action such as reserving pounds during allocation
        and its compensating action such as deallocation or cancellation must
        leave not only the sum but each of the three buckets individually at
        their pre-action values."

        PRD §3.5: "The point of stating this as a compensating action is that each
        of the three pound buckets, individually, must return to the value it held
        before the allocation."

        Design: Difficulty/compensating_invariant/conserved_pounds_of_inventory_allocate_then_deallocate_restores_every_bucket
        """
        scenario = _submitted_order_ready_to_allocate()
        assert scenario["order"]["total_cents"] == 620267, (
            f"Expected total 620267, got {scenario['order']['total_cents']}"
        )
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 50000

        allocated = allocate_order(scenario["order"]["id"])
        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
        mid = read_lot(scenario["lot"]["id"])
        assert mid["quantity_on_hand_lb"] == 35000, (
            f"Expected 35000 lb on hand mid-flight, got {mid['quantity_on_hand_lb']}"
        )
        assert mid["quantity_reserved_lb"] == 15000, (
            f"Expected 15000 lb reserved, got {mid['quantity_reserved_lb']}"
        )
        assert mid["quantity_consumed_lb"] == 0, (
            f"Expected nothing consumed, got {mid['quantity_consumed_lb']}"
        )
        assert_lot_inventory_conservation(mid)
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 35000, (
            "The zone total follows the on-hand pounds of its lots"
        )

        deallocated = deallocate_order(scenario["order"]["id"])

        assert deallocated["fulfillment_status"] == "NEW", (
            f"Expected the order back at NEW, got {deallocated['fulfillment_status']}"
        )
        after = read_lot(scenario["lot"]["id"])
        assert after["quantity_on_hand_lb"] == 50000, (
            f"Expected on hand back at 50000, got {after['quantity_on_hand_lb']}"
        )
        assert after["quantity_reserved_lb"] == 0, (
            f"Expected reserved back at 0, got {after['quantity_reserved_lb']}"
        )
        assert after["quantity_consumed_lb"] == 0, (
            f"Expected consumed still 0, got {after['quantity_consumed_lb']}"
        )
        assert after["quantity_received_lb"] == 50000, (
            f"Expected received untouched at 50000, got {after['quantity_received_lb']}"
        )
        assert_lot_inventory_conservation(after)
        assert read_zone(scenario["zone"]["id"])["on_hand_lb"] == 50000

    def test_the_released_line_stays_inside_the_exposure_and_risk_input_sets(self):
        """PRD §3.5: "Each line's `allocation_status` returns to `UNALLOCATED`
        with `lot_id` and `silo_id` cleared to null; on each released lot,
        `quantity_reserved_lb` decreases by the line's `quantity_lb` and
        `quantity_on_hand_lb` increases by the same amount, while
        `quantity_received_lb` is untouched."

        PRD §3.7: "The **in-flight** variant is used on allocation, on
        deallocation, and on substitution approval; its input set is the order
        lines whose owning order has `fulfillment_status` in `NEW`, `ALLOCATED`,
        `ROUTED` or `LOADED`."

        The line comes back as `UNALLOCATED` rather than `RELEASED` and the order
        returns to `NEW`, so both aggregations still see it: exposure holds at
        620267 and the gluten weight keeps the score at 55.00.

        Design: Difficulty/compensating_invariant/conserved_pounds_of_inventory_allocate_then_deallocate_restores_every_bucket
        """
        scenario = _submitted_order_ready_to_allocate()
        allocate_order(scenario["order"]["id"])

        deallocate_order(scenario["order"]["id"])

        line = read_order_line(scenario["order_line"]["id"])
        assert line["allocation_status"] == "UNALLOCATED", (
            f"Expected UNALLOCATED, got {line['allocation_status']}"
        )
        assert line["lot_id"] is None, f"Expected lot_id cleared, got {line['lot_id']}"
        assert line["silo_id"] is None, f"Expected silo_id cleared, got {line['silo_id']}"
        order = read_order(scenario["order"]["id"])
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected the commercial dimension untouched, got {order['pricing_status']}"
        )
        assert order["total_cents"] == 620267, (
            f"Expected total 620267, got {order['total_cents']}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 620267, (
            f"Expected exposure 620267, got {customer['open_exposure_cents']}"
        )
        assert float(customer["allergen_risk_score"]) == 55.00, (
            f"Expected the gluten score 55.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {customer['risk_tier']}"
        )


def _loaded_contract_order_awaiting_its_drop():
    """A 20000 lb draw against a 50000 lb commitment, dispatched and on the road."""
    set_clock("2026-08-05T00:00:00Z")
    scenario = setup_contracted_order(
        volume_committed_lb=50000,
        basis_cents_per_lb=6,
        pricing_mode="ORDER_DATE_INDEX",
        quantity_lb=20000,
        index_price_cents_per_lb=38,
        quote_effective_on="2026-08-01T00:00:00Z",
    )
    scenario["submitted"] = submit_order(scenario["customer"], scenario["order"]["id"])
    scenario["drawn_before"] = read_contract_line(scenario["contract_line"]["id"])[
        "volume_drawn_lb"
    ]
    allocate_order(scenario["order"]["id"])
    route = create_route(
        service_on="2026-09-15T00:00:00Z",
        vehicle_capacity_lb=24000,
        service_buffer_minutes=30,
    )
    stop = append_stop(
        route["id"],
        scenario["order"]["id"],
        "2026-09-15T08:00:00Z",
        "2026-09-15T10:00:00Z",
    )
    seal_route(route["id"])
    set_clock("2026-09-15T00:00:00Z")
    dispatch_route(route["id"])
    scenario["route"] = read_route(route["id"])
    scenario["route_stop"] = stop
    return scenario


class TestCommittedContractPoundsPartialReturn:
    """Conserved ledger two: committed pounds, compensated only in part."""

    def test_the_shorted_pounds_flow_back_to_the_commitment_line(self):
        """PRD §3.10: "Additionally — and this has no counterpart in the full drop
        — each affected contract line's `volume_drawn_lb` is reduced by the
        shorted pounds for that product, restoring the committed-pounds invariant
        of §2.9."

        PRD §2.9: "Stated in business terms: drawing pounds on submission and
        returning them through cancellation or a short drop must leave the
        remaining headroom — the commitment less the drawn volume — at its
        pre-action value."

        Design: Difficulty/compensating_invariant/conserved_committed_contract_pounds_short_shipment_returns_the_undelivered_volume
        """
        scenario = _loaded_contract_order_awaiting_its_drop()
        assert scenario["submitted"]["total_cents"] == 866404, (
            f"Expected total 866404, got {scenario['submitted']['total_cents']}"
        )
        assert scenario["drawn_before"] == 20000, (
            f"Expected the submission to draw 20000 lb, got {scenario['drawn_before']}"
        )

        shorted = short_stop(
            scenario["route_stop"]["id"],
            12000,
            short_reason="trailer compartment jammed; 8000 lb returned to the warehouse",
        )

        assert shorted["status"] == "SHORTED", (
            f"Expected SHORTED, got {shorted['status']}"
        )
        contract_line = read_contract_line(scenario["contract_line"]["id"])
        assert contract_line["volume_drawn_lb"] == 12000, (
            f"Expected volume_drawn_lb 12000, got {contract_line['volume_drawn_lb']}"
        )
        assert contract_line["volume_committed_lb"] == 50000, (
            f"Expected the commitment untouched, got {contract_line['volume_committed_lb']}"
        )
        contract = read_contract(scenario["contract"]["id"])
        assert contract["drawn_volume_lb"] == 12000, (
            f"Expected drawn_volume_lb 12000, got {contract['drawn_volume_lb']}"
        )
        assert contract["committed_volume_lb"] == 50000
        assert contract["status"] == "ACTIVE", (
            f"Expected the contract still ACTIVE, got {contract['status']}"
        )
        assert (
            contract["committed_volume_lb"] - contract["drawn_volume_lb"] == 38000
        ), "38000 lb of commitment must remain undrawn after the short drop"

    def test_the_same_call_splits_the_lot_twelve_thousand_to_eight(self):
        """PRD §3.10: "only the delivered pounds move from `quantity_reserved_lb`
        into `quantity_consumed_lb`, while the shorted pounds return to
        `quantity_on_hand_lb` and become pickable again."

        PRD §3.10: "The stop moves to `SHORTED` and the order `LOADED →
        SHORT_SHIPPED`, with `short_ship_lb` set to the order's total requested
        pounds less the delivered total."

        Design: Difficulty/compensating_invariant/conserved_committed_contract_pounds_short_shipment_returns_the_undelivered_volume
        """
        scenario = _loaded_contract_order_awaiting_its_drop()

        short_stop(
            scenario["route_stop"]["id"],
            12000,
            short_reason="trailer compartment jammed; 8000 lb returned to the warehouse",
        )

        lot = read_lot(scenario["lot"]["id"])
        assert lot["quantity_consumed_lb"] == 12000, (
            f"Expected 12000 lb consumed, got {lot['quantity_consumed_lb']}"
        )
        assert lot["quantity_on_hand_lb"] == 38000, (
            f"Expected 38000 lb pickable again, got {lot['quantity_on_hand_lb']}"
        )
        assert lot["quantity_reserved_lb"] == 0, (
            f"Expected nothing left reserved, got {lot['quantity_reserved_lb']}"
        )
        assert lot["quantity_received_lb"] == 50000
        assert_lot_inventory_conservation(lot)
        order = read_order(scenario["order"]["id"])
        assert order["fulfillment_status"] == "SHORT_SHIPPED", (
            f"Expected SHORT_SHIPPED, got {order['fulfillment_status']}"
        )
        assert order["short_ship_lb"] == 8000, (
            f"Expected short_ship_lb 8000, got {order['short_ship_lb']}"
        )
        assert order["delivered_on"] == "2026-09-15T00:00:00Z", (
            f"Expected delivered_on stamped from the clock, got {order['delivered_on']}"
        )
        assert order["pricing_status"] == "PROVISIONAL", (
            f"Expected the commercial dimension still open, got {order['pricing_status']}"
        )
        assert order["total_cents"] == 866404, (
            f"Expected total 866404, got {order['total_cents']}"
        )
        assert read_order_line(scenario["order_line"]["id"])["allocation_status"] == "SHIPPED"
        assert read_route(scenario["route"]["id"])["status"] == "COMPLETED", (
            "No stop remains in PLANNED, so the route completes"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert float(customer["allergen_risk_score"]) == 55.00, (
            f"Expected the closed-book gluten score 55.00, got {customer['allergen_risk_score']}"
        )
        assert customer["risk_tier"] == "AMBER"


def _bakery_holding_one_provisional_order_against_a_tight_limit():
    """827022 cents of exposure under a 1000000 cent limit, with no stock involved."""
    set_clock("2026-08-05T00:00:00Z")
    customer = create_customer(credit_limit_cents=1000000, min_drop_cents=25000)
    flour = create_product(FLOUR_HRW_LIST_ONLY)
    order = open_order(customer, requested_delivery_on="2026-09-15T00:00:00Z")
    line = add_order_line(customer, order["id"], flour["id"], 20000)
    submitted = submit_order(customer, order["id"])
    return {
        "customer": customer,
        "flour": flour,
        "order": submitted,
        "order_line": line,
    }


class TestOpenExposureCentsLedger:
    """Conserved ledger three: money, exercised in both directions of the guard."""

    def test_cutting_the_limit_moves_the_standing_but_never_the_exposure(self):
        """PRD §3.1: "Credit terms get renegotiated, and the account manager has a
        dedicated adjustment surface for that: supplying a
        `new_credit_limit_cents` together with a free-text `reason` overwrites
        `credit_limit_cents`, then immediately re-runs the exposure
        recomputation, which may move the account from `ACTIVE` to `CREDIT_HOLD`
        if outstanding exposure now sits above the lowered limit, or from
        `CREDIT_HOLD` back to `ACTIVE` if a raised limit now covers it."

        PRD §3.4: "A bakery's `open_exposure_cents` is the total of `total_cents`
        over every one of its orders whose `pricing_status` is either
        `PROVISIONAL` or `FINAL`; orders that are `UNPRICED`, `INVOICED` or `VOID`
        contribute nothing."

        The ledger tracks orders, not limits, so 827022 must survive the cut
        untouched even as the account standing flips.

        Design: Difficulty/compensating_invariant/conserved_open_credit_exposure_cents_survives_limit_cut_and_is_released_by_cancel
        """
        scenario = _bakery_holding_one_provisional_order_against_a_tight_limit()
        assert scenario["order"]["total_cents"] == 827022, (
            f"Expected total 827022, got {scenario['order']['total_cents']}"
        )
        before = read_customer(scenario["customer"]["id"])
        assert before["open_exposure_cents"] == 827022, (
            f"Expected exposure 827022, got {before['open_exposure_cents']}"
        )
        assert before["status"] == "ACTIVE", (
            f"Expected ACTIVE under the 1000000 limit, got {before['status']}"
        )

        adjusted = validate_success(
            api_client.adjust_credit_limit(
                scenario["customer"]["id"],
                credit_limit_adjustment_payload(500000),
                AM,
            )
        )

        assert adjusted["credit_limit_cents"] == 500000, (
            f"Expected the limit overwritten to 500000, got {adjusted['credit_limit_cents']}"
        )
        assert adjusted["open_exposure_cents"] == 827022, (
            f"Expected exposure unchanged at 827022, got {adjusted['open_exposure_cents']}"
        )
        assert adjusted["status"] == "CREDIT_HOLD", (
            f"Expected CREDIT_HOLD, got {adjusted['status']}"
        )
        assert read_order(scenario["order"]["id"])["total_cents"] == 827022, (
            "Cutting a limit never rewrites an order's settled figures"
        )

    def test_cancelling_the_order_releases_the_exposure_and_revives_the_account(self):
        """PRD §3.4: "Immediately afterwards the account standing is re-derived:
        an `ACTIVE` bakery whose recomputed exposure strictly exceeds its
        `credit_limit_cents` moves to `CREDIT_HOLD`, and a bakery on
        `CREDIT_HOLD` whose recomputed exposure is no greater than its limit
        returns to `ACTIVE`."

        PRD §3.3: "Cancellation drives both dimensions at once:
        `fulfillment_status` becomes `CANCELLED` and `pricing_status` becomes
        `VOID` — a transition available from either `UNPRICED` or `PROVISIONAL`."

        `CREDIT_HOLD` is therefore not terminal: voiding the only priced order
        drops the exposure to exactly 0 and the account walks back.

        Design: Difficulty/compensating_invariant/conserved_open_credit_exposure_cents_survives_limit_cut_and_is_released_by_cancel
        """
        scenario = _bakery_holding_one_provisional_order_against_a_tight_limit()
        validate_success(
            api_client.adjust_credit_limit(
                scenario["customer"]["id"],
                credit_limit_adjustment_payload(500000),
                AM,
            )
        )

        cancelled = cancel_order(
            scenario["customer"],
            scenario["order"]["id"],
            cancellation_reason="bakery released the order to free up credit",
        )

        assert cancelled["pricing_status"] == "VOID", (
            f"Expected VOID, got {cancelled['pricing_status']}"
        )
        assert cancelled["fulfillment_status"] == "CANCELLED", (
            f"Expected CANCELLED, got {cancelled['fulfillment_status']}"
        )
        assert cancelled["total_cents"] == 0, (
            f"Expected total reset to 0, got {cancelled['total_cents']}"
        )
        assert cancelled["subtotal_cents"] == 0
        assert cancelled["fuel_surcharge_cents"] == 0
        assert cancelled["volume_rebate_cents"] == 0
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 0, (
            f"Expected exposure back at exactly 0, got {customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE", (
            f"Expected the account revived to ACTIVE, got {customer['status']}"
        )
        assert customer["credit_limit_cents"] == 500000, (
            f"Expected the lowered limit to stand, got {customer['credit_limit_cents']}"
        )
