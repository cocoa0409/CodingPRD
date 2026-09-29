"""Version tokens, cascades and the two pricing observation dates layered on one order (PRD §2.6, §3.4, §3.7, §3.8)."""

from test_helpers import (
    ApiErrorId,
    add_contract_line,
    activate_contract,
    add_order_line,
    allocate_order,
    api_client,
    append_stop,
    create_customer,
    create_product,
    create_substitution_request_payload,
    create_route,
    create_zone,
    deliver_stop,
    dispatch_route,
    draft_contract,
    make_technical_specialist_headers,
    offer_contract,
    open_order,
    publish_index_quote,
    quarantine_lot,
    raise_substitution_request,
    read_customer,
    read_lot,
    read_order,
    read_order_line,
    read_route,
    read_route_stop,
    read_substitution_request,
    receive_lot,
    seal_route,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import LP, PC, TS

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-LAY-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 365,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


INDEXED_FLOUR = dict(FLOUR_30, sku="FLR-DVA-30", index_code="HRW_WHEAT")


def _delivered_contract_order(pricing_mode, sku, route_code, lot_code):
    """One 1000 lb contracted order taken all the way to a delivered stop.

    The opening quote of 100 is published before the order is placed on
    2026-09-01, and a second quote of 130 is published on the delivery day.
    """
    set_clock("2026-09-01T00:00:00Z")
    customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
    flour = create_product(dict(INDEXED_FLOUR, sku=sku))
    publish_index_quote(
        index_code="HRW_WHEAT",
        effective_on="2026-08-01T00:00:00Z",
        price_cents_per_lb=100,
    )
    contract = draft_contract(
        customer,
        term_start_on="2026-09-01T00:00:00Z",
        term_end_on="2026-09-30T00:00:00Z",
        pricing_mode=pricing_mode,
    )
    contract_line = add_contract_line(
        contract["id"], flour["id"],
        volume_committed_lb=50000,
        basis_cents_per_lb=10,
        cap_cents_per_lb=200,
    )
    offer_contract(contract["id"])
    activate_contract(contract["id"])
    zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
    receive_lot(
        flour["id"], zone["id"], lot_code=lot_code,
        manufactured_on="2026-08-01T00:00:00Z", quantity_received_lb=20000,
    )
    order = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on=SERVICE_ON,
        contract_id=contract["id"],
    )
    line = add_order_line(customer, order["id"], flour["id"], 1000)
    provisional = submit_order(customer, order["id"])
    allocate_order(order["id"])
    route = create_route(
        route_code=route_code,
        service_on=SERVICE_ON,
        vehicle_capacity_lb=48000,
        service_buffer_minutes=30,
    )
    stop = append_stop(
        route["id"], order["id"],
        "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
    )
    seal_route(route["id"])
    set_clock("2026-09-10T06:00:00Z")
    late_quote = publish_index_quote(
        index_code="HRW_WHEAT",
        effective_on="2026-09-05T00:00:00Z",
        price_cents_per_lb=130,
    )
    dispatch_route(route["id"])
    deliver_stop(stop["id"])
    return {
        "customer": customer,
        "contract_line": contract_line,
        "order": order,
        "line": line,
        "provisional": provisional,
        "late_quote": late_quote,
    }


class TestSupersedingAProposalMovesTheOrderVersionUnderTheSpecialist:
    """The token the first proposal was raised with cannot be replayed."""

    def test_the_replayed_token_is_refused_and_the_refreshed_one_is_accepted(self):
        """PRD §3.8: "Creating a request supersedes any earlier request on the same order
        line that is still open in `REQUESTED` or `REVISION_REQUESTED`, moving that
        earlier one to `WITHDRAWN`, and it increments the parent order's `version` by 1 —
        which in turn invalidates any other specialist's held order version."

        PRD §2.6: "A request to `POST /bakery-distribution/substitution-requests` must
        carry `expected_order_version` as a required input field, holding the `version` of
        the parent `Order` — reached from the supplied `order_line_id` — as the specialist
        last observed it. If that value does not equal the order's current `version` at
        the moment of the write, the create is rejected with `ERR_STALE_ORDER_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_order_version_stale_after_supersede_then_retry_succeeds
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        ordered = create_product(dict(FLOUR_30, sku="FLR-OCA-30"))
        first_alternative = create_product(
            dict(FLOUR_30, sku="FLR-OCB-32", list_price_cents_per_lb=32)
        )
        second_alternative = create_product(
            dict(FLOUR_30, sku="FLR-OCC-34", list_price_cents_per_lb=34)
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        receive_lot(
            ordered["id"], zone["id"], lot_code="LOT-OCA-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=20000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], ordered["id"], 1000)
        submit_order(customer, order["id"])
        allocated = allocate_order(order["id"])
        stale_version = allocated["version"]
        first_request = raise_substitution_request(
            line["id"], first_alternative["id"], stale_version,
            rationale="First proposal against the stale token",
        )
        second_request = raise_substitution_request(
            line["id"], second_alternative["id"], read_order(order["id"])["version"],
            rationale="Second proposal supersedes the first",
        )

        response = api_client.create_substitution_request(
            create_substitution_request_payload(
                line["id"], first_alternative["id"], stale_version,
                rationale="Third proposal replaying the original token",
            ),
            make_technical_specialist_headers("ts-1"),
        )

        validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION)
        assert response.status_code == 412, (
            f"Expected HTTP 412, got {response.status_code}"
        )
        assert read_substitution_request(first_request["id"])["status"] == "WITHDRAWN", (
            "The first proposal was superseded by the second"
        )
        surviving = read_substitution_request(second_request["id"])
        assert surviving["status"] == "REQUESTED", (
            f"Expected the second proposal still REQUESTED, got {surviving['status']}"
        )
        assert surviving["proposed_product_id"] == second_alternative["id"], (
            "The surviving proposal keeps its own SKU"
        )
        requests, _meta = validate_paginated(
            api_client.list_substitution_requests(
                TS, params={"order_line_id": line["id"]}
            )
        )
        assert len(requests) == 2, (
            f"The refused call created no third row, got {len(requests)}"
        )
        assert read_order_line(line["id"])["product_id"] == ordered["id"], (
            "A raised request never mutates the line"
        )

        replayed = validate_success(
            api_client.create_substitution_request(
                create_substitution_request_payload(
                    line["id"], first_alternative["id"],
                    read_order(order["id"])["version"],
                    rationale="Third proposal replaying the original token",
                ),
                make_technical_specialist_headers("ts-1"),
            ),
            201,
        )

        assert replayed["status"] == "REQUESTED", (
            f"A refreshed token is accepted, got {replayed['status']}"
        )


class TestOneQuarantineUnwindsTheWholeSealedLoad:
    """Four hops fire from a single quality action, and the pounds stay conserved."""

    def test_the_line_order_stop_and_route_all_step_back_together(self):
        """PRD §3.7: "**Hop one:** every order line whose `lot_id` is this lot and whose
        `allocation_status` is `RESERVED` flips back to `UNALLOCATED`; the lot's
        `quantity_reserved_lb` decreases by that line's `quantity_lb` and its
        `quantity_on_hand_lb` increases by the same amount, conserving the lot's totals.
        **Hop two:** because those lines became `UNALLOCATED`, each parent order whose
        `fulfillment_status` is `ALLOCATED` or `ROUTED` reverts to `NEW`. **Hop three:**
        because those orders left `ROUTED`, each of their route stops still in `PLANNED`
        flips to `CANCELLED`, and the owning route recomputes `planned_load_lb`,
        `utilization_pct` and `stop_count`. **Hop four:** because `stop_count` has reached
        zero on a route whose `status` was `SEALED`, that route reverts to `PLANNING` and
        its `allergen_class_lock` resets to `NONE`."

        PRD §2.9: "For every lot, the sum of `quantity_on_hand_lb`,
        `quantity_reserved_lb` and `quantity_consumed_lb` equals `quantity_received_lb`,
        exactly, at two decimal places. That equality is asserted after every mutation
        that touches a lot: allocation, deallocation, order cancellation, quarantine,
        release, disposal, full delivery, short delivery, and the lot re-pick that follows
        a substitution approval."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_quarantine_cascade_four_hops_unseals_route_and_clears_lock
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-QCA-30"))
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        lot = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-QCA-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=30000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], flour["id"], 4000)
        submit_order(customer, order["id"])
        allocate_order(order["id"])
        route = create_route(
            route_code="R-QCASC",
            service_on=SERVICE_ON,
            vehicle_capacity_lb=48000,
            service_buffer_minutes=30,
        )
        stop = append_stop(
            route["id"], order["id"],
            "2026-09-10T08:00:00Z", "2026-09-10T09:00:00Z",
        )
        sealed = seal_route(route["id"])
        assert sealed["allergen_class_lock"] == "GLUTEN", (
            f"The trailer locked onto the load's class, got "
            f"{sealed['allergen_class_lock']}"
        )

        held = quarantine_lot(
            lot["id"],
            quarantine_reason="Insect activity found during a bin inspection",
        )

        assert held["status"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {held['status']}"
        )
        released_line = read_order_line(line["id"])
        assert released_line["allocation_status"] == "UNALLOCATED", (
            f"Hop one: expected UNALLOCATED, got {released_line['allocation_status']}"
        )
        assert held["quantity_reserved_lb"] == 0, (
            f"Hop one: expected 0 reserved, got {held['quantity_reserved_lb']}"
        )
        assert held["quantity_on_hand_lb"] == 30000, (
            f"Hop one: expected the pounds back on hand, got "
            f"{held['quantity_on_hand_lb']}"
        )
        rewound = read_order(order["id"])
        assert rewound["fulfillment_status"] == "NEW", (
            f"Hop two: expected NEW, got {rewound['fulfillment_status']}"
        )
        assert rewound["pricing_status"] == "PROVISIONAL", (
            f"Hop two: the commercial dimension is untouched, got "
            f"{rewound['pricing_status']}"
        )
        assert rewound["total_cents"] == 121155, (
            f"Hop two: expected the settlement intact at 121155, got "
            f"{rewound['total_cents']}"
        )
        cancelled = read_route_stop(stop["id"])
        assert cancelled["status"] == "CANCELLED", (
            f"Hop three: expected CANCELLED, got {cancelled['status']}"
        )
        assert cancelled["sequence_no"] == 0, (
            f"Hop four: expected the sequence cleared, got {cancelled['sequence_no']}"
        )
        unsealed = read_route(route["id"])
        assert unsealed["stop_count"] == 0, (
            f"Hop three: expected stop_count 0, got {unsealed['stop_count']}"
        )
        assert unsealed["planned_load_lb"] == 0, (
            f"Hop three: expected planned_load_lb 0, got {unsealed['planned_load_lb']}"
        )
        assert float(unsealed["utilization_pct"]) == 0.00, (
            f"Hop three: expected utilization 0.00, got {unsealed['utilization_pct']}"
        )
        assert unsealed["status"] == "PLANNING", (
            f"Hop four: expected PLANNING, got {unsealed['status']}"
        )
        assert unsealed["allergen_class_lock"] == "NONE", (
            f"Hop four: expected the lock cleared, got {unsealed['allergen_class_lock']}"
        )
        final_lot = read_lot(lot["id"])
        assert (
            final_lot["quantity_on_hand_lb"]
            + final_lot["quantity_reserved_lb"]
            + final_lot["quantity_consumed_lb"]
            == final_lot["quantity_received_lb"]
        ), "The lot's three buckets must still sum to the received pounds"


class TestTheSameOrderPricedByBothObservationDates:
    """A quote published after placement is invisible until final settlement."""

    def test_the_delivery_date_quote_lifts_the_final_total_by_exactly_thirty_thousand_cents(self):
        """PRD §3.4: "During submission and during every provisional reprice, the
        observation date is the order's `order_placed_on`, regardless of what the
        contract's `pricing_mode` says. During final settlement, the observation date
        depends on the mode: under `DELIVERY_DATE_INDEX` it is the order's `delivered_on`,
        and under `ORDER_DATE_INDEX` it remains `order_placed_on`."

        PRD §3.11: "Finalization re-runs the settlement price for every line under the
        delivery-date observation described in §3.4 — producing per-pound prices that may
        legitimately differ from the provisional ones — then re-extends the lines, re-runs
        the order-level waterfall, recomputes the bakery's `open_exposure_cents`, and
        increments the order's `version` by 1."

        Provisional 110 c/lb gives 110000 plus 2750 fuel; final 140 c/lb gives 140000 plus
        3500 fuel, a swing of exactly 30750 cents.

        Design: Corner/cross_cutting_complexity_layers/corner_layer_dual_variant_delta_between_provisional_and_final_pricing
        """
        scenario = _delivered_contract_order(
            "DELIVERY_DATE_INDEX", "FLR-DVA-30", "R-DVA", "LOT-DVA-0001"
        )
        provisional_total = scenario["provisional"]["total_cents"]
        assert provisional_total == 112750, (
            f"The order-date observation prices at 110 c/lb, so expected 112750, got "
            f"{provisional_total}"
        )
        assert read_order_line(scenario["line"]["id"])["unit_price_cents"] == 110, (
            "Quote 100 effective 2026-08-01 plus basis 10"
        )

        final = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC), 200
        )

        assert final["pricing_status"] == "FINAL", (
            f"Expected FINAL, got {final['pricing_status']}"
        )
        repriced = read_order_line(scenario["line"]["id"])
        assert repriced["unit_price_cents"] == 140, (
            f"Quote 130 effective 2026-09-05 plus basis 10, under the 200 cap, so "
            f"expected 140, got {repriced['unit_price_cents']}"
        )
        assert repriced["contract_line_id"] == scenario["contract_line"]["id"], (
            "The line stays bound to the commitment it drew against"
        )
        assert final["subtotal_cents"] == 140000, (
            f"Expected subtotal 140000, got {final['subtotal_cents']}"
        )
        assert final["fuel_surcharge_cents"] == 3500, (
            f"Expected 2.5% of 140000, got {final['fuel_surcharge_cents']}"
        )
        assert final["volume_rebate_cents"] == 0, (
            f"143500 is below the 500000 rebate floor, got "
            f"{final['volume_rebate_cents']}"
        )
        assert final["total_cents"] == 143500, (
            f"Expected total 143500, got {final['total_cents']}"
        )
        assert final["total_cents"] - provisional_total == 30750, (
            f"Expected a delta of exactly 30750, got "
            f"{final['total_cents'] - provisional_total}"
        )
        assert read_customer(scenario["customer"]["id"])["open_exposure_cents"] == 143500, (
            "A FINAL order still counts against the credit line until invoiced"
        )

    def test_an_order_date_contract_finalises_at_the_price_it_was_submitted_with(self):
        """PRD §3.4: "During final settlement, the observation date depends on the mode:
        under `DELIVERY_DATE_INDEX` it is the order's `delivered_on`, and under
        `ORDER_DATE_INDEX` it remains `order_placed_on`. Consequently, when a contract
        prices on the delivery date and a new quote is published between the order's
        placement and its delivery, that later quote becomes prevailing at final
        settlement and the final per-pound price legitimately differs from the provisional
        one for identical order inputs."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_dual_variant_delta_between_provisional_and_final_pricing
        """
        scenario = _delivered_contract_order(
            "ORDER_DATE_INDEX", "FLR-DVB-30", "R-DVB", "LOT-DVB-0001"
        )

        final = validate_success(
            api_client.finalize_order_pricing(scenario["order"]["id"], {}, PC), 200
        )

        assert final["pricing_status"] == "FINAL", (
            f"Expected FINAL, got {final['pricing_status']}"
        )
        assert read_order_line(scenario["line"]["id"])["unit_price_cents"] == 110, (
            "The later quote is ignored under the order-date mode"
        )
        assert final["subtotal_cents"] == 110000, (
            f"Expected subtotal 110000, got {final['subtotal_cents']}"
        )
        assert final["fuel_surcharge_cents"] == 2750, (
            f"Expected 2.5% of 110000, got {final['fuel_surcharge_cents']}"
        )
        assert final["total_cents"] == 112750, (
            f"Expected the provisional total to survive finalization, got "
            f"{final['total_cents']}"
        )
        assert final["total_cents"] == scenario["provisional"]["total_cents"], (
            "Identical inputs and observation date give an identical settlement"
        )
