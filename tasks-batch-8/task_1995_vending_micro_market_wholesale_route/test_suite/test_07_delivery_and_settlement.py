"""Delivery, cash-vs-cashless settlement, and margin reconciliation."""
from test_helpers import (
    ADMIN,
    PLANNER,
    WAREHOUSE,
    ApiErrorId,
    activate_planogram,
    confirm_order,
    create_draft_planogram,
    create_location,
    create_operator,
    create_order,
    create_product,
    create_route,
    deliver_order,
    get_order,
    get_success_data,
    ingest_telemetry,
    make_operator_manager_headers,
    setup_selling_location,
    settle_order_with_event,
    submit_order,
    walk_order_to_delivered,
    validate_error,
    validate_success,
)

BOGUS_EVENT = "12121212-1212-1212-1212-121212121212"


def _margin_world(api):
    """2 cases of a pack-10 / base-1000 product, delivered; slot vend 150."""
    world = setup_selling_location(
        products_spec=[{"sku": "COLA-12", "name": "Cola 12oz case",
                        "category": "BEVERAGE", "case_pack_qty": 10,
                        "base_price_cents": 1000, "cost_cents": 600,
                        "shelf_life_days": 180}],
        slots_spec=[{"slot_code": "A1", "product_index": 0,
                     "par_level_units": 20, "vend_price_cents": 150}],
        route_code="R-MON",
        operator_name="Op Margin",
        location_name="L-Margin",
        planogram_name="PG-Margin",
    )
    order = create_order(
        world,
        [{"product_id": world["products"][0]["id"], "quantity_cases": 2}],
    )
    return world, order


class TestMarginDualVariant:
    def test_provisional_margin_pinned_at_submit(self, api):
        """PRD §3.5: "`provisional_margin_per_vend_cents` is that retail value
        minus `order_total_cents`, divided by the total vend units, rounded
        half up." (retail 150*10*2 = 3000 minus total 2000 over 20 vends = 50)

        Design: Difficulty/dual_variant_calc/margin_per_vend_provisional_vs_realized
        """
        world, order = _margin_world(api)
        submitted = submit_order(world, order["id"])
        assert submitted["order_total_cents"] == 2000
        assert submitted["provisional_margin_per_vend_cents"] == 50

    def test_realized_margin_differs_at_settle(self, api):
        """PRD §3.6: "Settlement first computes the cashless processing fee:
        `cashless_fee_cents` is the event's `cashless_sales_cents` times 275
        basis points — two and three-quarter percent — rounded half up. It then
        computes `realized_margin_per_vend_cents`: the total vended units are
        the sum of `units_vended` across the event's items; if that total is
        zero the realized margin is 0; otherwise it is `cash_collected_cents`
        plus `cashless_sales_cents`, minus the cashless fee, minus
        `order_total_cents`, divided by the total vended units, rounded half
        up."
        PRD §3.5: "Because it stands on planogram vend prices and ignores
        cashless fees, the provisional figure generally differs from the
        realized margin computed at settlement"

        Design: Difficulty/dual_variant_calc/margin_per_vend_provisional_vs_realized
        """
        world, order = _margin_world(api)
        submit_order(world, order["id"])
        confirm_order(order["id"])
        deliver_order(order["id"])
        event = ingest_telemetry(
            world["location"]["id"], "2026-08-04T10:00:00Z",
            [{"product_id": world["products"][0]["id"], "units_vended": 20,
              "on_hand_units": 0}],
            cash_collected_cents=2200, cashless_sales_cents=900,
        )
        settled = validate_success(
            api.settle_order(
                order["id"],
                {"tender_type": "CASHLESS", "telemetry_event_id": event["id"]},
                ADMIN,
            ),
            200,
        )
        assert settled["order_total_cents"] == 2000
        # round_half_up(900 * 275 / 10000) == round_half_up(24.75) == 25
        assert settled["cashless_fee_cents"] == 25
        # round_half_up((2200 + 900 - 25 - 2000) / 20) == round_half_up(53.75)
        assert settled["realized_margin_per_vend_cents"] == 54
        assert settled["provisional_margin_per_vend_cents"] == 50
        assert (settled["provisional_margin_per_vend_cents"]
                != settled["realized_margin_per_vend_cents"])
        assert settled["settlement_status"] == "SETTLED"
        assert settled["settled_tender"] == "CASHLESS"
        assert settled["settlement_telemetry_event_id"] == event["id"]


class TestSettlementEdgeCases:
    def test_realized_margin_zero_units_vended(self, api):
        """PRD §3.6: "the total vended units are the sum of `units_vended`
        across the event's items; if that total is zero the realized margin is
        0"

        Design: Corner/calculations/realized_margin_zero_units_vended
        """
        world = setup_selling_location(
            products_spec=[{"sku": "ZRO-1", "name": "Zero item"}],
            route_code="R-ZRO",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        event = ingest_telemetry(
            world["location"]["id"], "2026-08-04T09:00:00Z",
            [], cash_collected_cents=500, cashless_sales_cents=1000,
        )
        settled = validate_success(
            api.settle_order(
                order["id"],
                {"tender_type": "CASHLESS", "telemetry_event_id": event["id"]},
                ADMIN,
            ),
            200,
        )
        # round_half_up(1000 * 275 / 10000) == round_half_up(27.5) == 28
        assert settled["cashless_fee_cents"] == 28
        assert settled["realized_margin_per_vend_cents"] == 0
        assert settled["settlement_status"] == "SETTLED"

    def test_settle_before_delivery_rejected(self, api):
        """PRD §3.6: "Final settlement is performed by a `WholesaleAdmin` on an
        order whose settlement dimension is `OPEN` (else
        `ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT`)"

        Design: Corner/errors/settle_before_delivery_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "STL-1", "name": "Stl item"}],
            route_code="R-STL",
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        submit_order(world, order["id"])
        confirm_order(order["id"])
        event = ingest_telemetry(
            world["location"]["id"], "2026-08-03T09:00:00Z",
            [{"product_id": world["products"][0]["id"], "units_vended": 0,
              "on_hand_units": 10}],
        )
        err = api.settle_order(
            order["id"],
            {"tender_type": "CASH", "telemetry_event_id": event["id"]},
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_OPEN_FOR_SETTLEMENT)
        assert get_order(order["id"])["settlement_status"] == "UNINVOICED"

    def test_settle_nonexistent_telemetry_returns_not_found(self, api):
        """PRD §3.6: "That event must exist (`ERR_TELEMETRY_EVENT_NOT_FOUND`)
        and must belong to the order's location
        (`ERR_TELEMETRY_EVENT_LOCATION_MISMATCH`)."

        Design: Corner/endpoints/settle_nonexistent_telemetry_returns_not_found
        """
        world = setup_selling_location(
            products_spec=[{"sku": "NEV-1", "name": "NoEv item"}],
            route_code="R-NEV",
        )
        order = walk_order_to_delivered(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        err = api.settle_order(
            order["id"],
            {"tender_type": "CASH", "telemetry_event_id": BOGUS_EVENT},
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_TELEMETRY_EVENT_NOT_FOUND)

    def test_settle_telemetry_location_mismatch_rejected(self, api):
        """PRD §3.6: "That event must exist (`ERR_TELEMETRY_EVENT_NOT_FOUND`)
        and must belong to the order's location
        (`ERR_TELEMETRY_EVENT_LOCATION_MISMATCH`)."

        Design: Corner/endpoints/settle_telemetry_location_mismatch_rejected
        """
        op = create_operator("Op Mis")
        route = create_route("R-MIS", ("MON",), 50, 0)
        product = create_product(sku="MIS-1", name="Mis item")
        om = make_operator_manager_headers(op["id"])

        loc_a = create_location(op["id"], route["id"], "L-MisA")
        pg = create_draft_planogram(
            loc_a["id"],
            [{"slot_code": "A1", "product_id": product["id"],
              "par_level_units": 10, "vend_price_cents": 150}],
            op["id"], "PG-MisA",
        )
        activate_planogram(pg["id"], loc_a["id"], op["id"])
        loc_b = create_location(op["id"], route["id"], "L-MisB")

        created = get_success_data(
            api.create_order(
                {"location_id": loc_a["id"],
                 "requested_delivery_date": "2026-08-03",
                 "lines": [{"product_id": product["id"], "quantity_cases": 1}]},
                om,
            )
        )
        get_success_data(api.submit_order(created["id"], om))
        get_success_data(api.confirm_order(created["id"], PLANNER))
        get_success_data(api.mark_order_delivered(created["id"], WAREHOUSE))

        # Event recorded for a DIFFERENT location of the same operator.
        event_b = ingest_telemetry(
            loc_b["id"], "2026-08-04T09:00:00Z",
            [{"product_id": product["id"], "units_vended": 5,
              "on_hand_units": 5}],
            cash_collected_cents=300, cashless_sales_cents=200,
        )
        err = api.settle_order(
            created["id"],
            {"tender_type": "CASH", "telemetry_event_id": event_b["id"]},
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_TELEMETRY_EVENT_LOCATION_MISMATCH)
        assert get_order(created["id"])["settlement_status"] == "OPEN"


class TestClaimDeliveryGate:
    def _gate2_world(self, api):
        world = setup_selling_location(
            products_spec=[{"sku": "GT2-1", "name": "Gate2 item",
                            "category": "CHILLED", "shelf_life_days": 21,
                            "perishability_class": "CHILLED"}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 180}],
            route_code="R-GT2",
            operator_name="Op Gate2",
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        submit_order(world, order["id"])
        confirm_order(order["id"])
        return world, order

    def test_claim_on_confirmed_order_rejected(self, api):
        """PRD §3.7: "Operators claw back shrink through credit claims, filed
        by an `OperatorManager` against a delivered order — the referenced
        order's `fulfillment_status` must be `DELIVERED`, else
        `ERR_ORDER_NOT_DELIVERED`."

        Design: Difficulty/cross_entity_state_dependency/claim_create_gated_by_order_delivered
        """
        world, order = self._gate2_world(api)
        err = api.create_credit_claim(
            {
                "order_id": order["id"],
                "lines": [{"product_id": world["products"][0]["id"],
                           "quantity_units": 1,
                           "expiration_date": "2026-07-30"}],
            },
            world["om_headers"],
        )
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_DELIVERED)

    def test_claim_after_delivery_succeeds(self, api):
        """PRD §3.7: "the referenced order's `fulfillment_status` must be
        `DELIVERED`, else `ERR_ORDER_NOT_DELIVERED`."
        PRD §3.7: "an expired line credits 100 percent of its wholesale value"
        and "A line's credit amount is its order line's pinned
        `unit_price_cents` times `quantity_units` times the tier percentage,
        divided by the product's `case_pack_qty`, rounded half up per line."

        Design: Difficulty/cross_entity_state_dependency/claim_create_gated_by_order_delivered
        """
        world, order = self._gate2_world(api)
        deliver_order(order["id"])
        resp = api.create_credit_claim(
            {
                "order_id": order["id"],
                "lines": [{"product_id": world["products"][0]["id"],
                           "quantity_units": 1,
                           "expiration_date": "2026-07-30"}],
            },
            world["om_headers"],
        )
        claim = validate_success(resp, 201)
        assert claim["status"] == "SUBMITTED"
        # Expired 2 days before the 2026-08-01 logical date, 100% tier:
        # round_half_up(1000 * 1 * 1.00 / 10) == 100.
        assert claim["requested_credit_cents"] == 100
