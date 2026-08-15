"""Order completion boundary, close-out price adjustment, and outside
processing returns (PRD §2.9, §3.5, §3.8, §3.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_run,
    create_and_release_order,
    create_approved_coil,
    create_customer,
    create_order,
    create_outside_processing_order_payload,
    create_part,
    create_press,
    get_order,
    install_die_on_press,
    publish_index,
    schedule_run,
    set_clock,
    setup_completed_order,
    setup_part_ready,
    setup_runnable,
    start_run,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOrderCompletionBoundary:
    def _setup_two_orders(self):
        """Two orders of 50 each on one part; the first run delivers 50 good,
        the second delivers 49."""
        ctx = setup_runnable(quantity_ordered=50, coil_weight_kg=500)
        order_lt = create_and_release_order(ctx["part"]["id"], quantity_ordered=50)
        run_eq = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z")
        run_lt = schedule_run(ctx, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z",
                              order_id=order_lt["id"])
        start_run(run_eq["id"])
        complete_run(run_eq["id"], 50, ctx["coil"]["id"])
        start_run(run_lt["id"])
        complete_run(run_lt["id"], 49, ctx["coil"]["id"])
        return ctx, order_lt

    def test_complete_at_exactly_ordered_quantity_succeeds(self, api, production_planner_headers):
        """PRD §3.10: "When production has satisfied the contract, a `ProductionPlanner` completes the order: the order must be `IN_PROGRESS`, its accumulated `quantity_produced_good` must be at least its `quantity_ordered`, and no run of the order may still be `RUNNING`."

        Design: Difficulty/boundary_precision_check/order_completion_at_exact_ordered_quantity
        """
        ctx, _order_lt = self._setup_two_orders()
        completed = validate_success(
            api.complete_production_order(ctx["order"]["id"], production_planner_headers)
        )
        assert completed["status"] == "COMPLETED", (
            "quantity_produced_good == quantity_ordered == 50 satisfies the at-least boundary"
        )

    def test_complete_one_good_part_short_rejected(self, api, production_planner_headers):
        """PRD §3.10: "When production has satisfied the contract, a `ProductionPlanner` completes the order: the order must be `IN_PROGRESS`, its accumulated `quantity_produced_good` must be at least its `quantity_ordered`, and no run of the order may still be `RUNNING`."
        PRD §2.5: "4. **State-machine precondition.** The target resource's current state permits the requested action — a run must be `RUNNING` to complete, a coil must be `APPROVED` to feed a run start, and so on through every state machine in §3. Failure: `ERR_INVALID_STATE` (409)."

        Design: Difficulty/boundary_precision_check/order_completion_at_exact_ordered_quantity
        """
        _ctx, order_lt = self._setup_two_orders()
        resp = api.complete_production_order(order_lt["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order_lt["id"])["status"] == "IN_PROGRESS"


class TestIndexLinkedPriceAdjustment:
    def _setup_two_variant_orders(self):
        """Identical orders A (RELEASE_LOCKED, default) and B (SHIPMENT_SPOT) on a
        part with 0.85 kg steel content and a 2500-cent base price; the customer's
        basis is CRU_HRC with base 900 and 0.8 pass-through; the index reads 940
        when both orders release (clock 2026-08-03) and 1020 prints before close."""
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_part_ready(
            customer_overrides={"name": "Acme Auto", "customer_code": "ACME",
                                "steel_index_basis": "CRU_HRC",
                                "base_index_value": 900, "pass_through_pct": 0.8},
            part_overrides={"part_number": "P-100", "base_piece_price_cents": 2500,
                            "ppap_required_level": 3},
        )
        publish_index(940, published_at="2026-08-02T00:00:00Z")
        set_clock("2026-08-03T00:00:00Z")
        ctx["order"] = create_and_release_order(ctx["part"]["id"], quantity_ordered=100)
        ctx["order_b"] = create_and_release_order(
            ctx["part"]["id"], quantity_ordered=100, pricing_variant="SHIPMENT_SPOT"
        )
        # The pinned release-time reading is observable on the order itself.
        assert ctx["order"]["steel_index_at_release"] == 940
        assert ctx["order_b"]["steel_index_at_release"] == 940
        ctx["press"] = create_press()
        ctx["changeover"] = install_die_on_press(ctx["press"]["id"], ctx["die"]["id"])
        ctx["coil"] = create_approved_coil(received_weight_kg=5000)
        return ctx

    def test_release_locked_uses_index_pinned_at_release(self, api, cost_analyst_headers, production_planner_headers):
        """PRD §3.10: "Which index value fills `applied_index_value` depends on the order's `pricing_variant`. Under `RELEASE_LOCKED` — the default — the adjustment applies the value captured at release in `steel_index_at_release`; spot movement after release has no effect on the order's price."
        PRD §3.10: "Third, the material term in cents is the pass-through amount multiplied by the part's `steel_content_kg`, multiplied by 100, and divided by 1,000 — converting dollars per metric ton into cents per part through the part's steel content. Fourth, the material term is rounded to whole cents, round half up, before any addition takes place; this per-part rounding happens first, deliberately. Fifth, the adjusted piece price is the part's `base_piece_price_cents` plus the rounded material term, yielding integer cents."

        Design: Difficulty/dual_variant_calc/price_adjustment_release_locked_vs_shipment_spot
        """
        ctx = self._setup_two_variant_orders()
        order_a = ctx["order"]
        run_a = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z")
        start_run(run_a["id"])
        complete_run(run_a["id"], 100, ctx["coil"]["id"])
        validate_success(api.complete_production_order(order_a["id"], production_planner_headers))
        publish_index(1020, published_at="2026-08-05T00:00:00Z")
        set_clock("2026-08-06T00:00:00Z")
        validate_success(api.close_production_order(order_a["id"], production_planner_headers))

        rows, _meta = validate_paginated(
            api.list_order_price_adjustments(order_a["id"], cost_analyst_headers)
        )
        assert len(rows) == 1
        adj = rows[0]
        # delta 940-900 = 40 USD/ton; pass-through 32; material 32*0.85*100/1000
        # = 2.72 cents -> round half up to 3 -> 2500 + 3 = 2503.
        assert adj["adjusted_piece_price_cents"] == 2503
        assert adj["applied_index_value"] == 940
        assert adj["variant_applied"] == "RELEASE_LOCKED"
        assert adj["base_index_value"] == 900

    def test_shipment_spot_uses_index_at_close_and_diverges(self, api, cost_analyst_headers, production_planner_headers):
        """PRD §3.10: "Under `SHIPMENT_SPOT`, the adjustment applies the latest index publication for the customer's `steel_index_basis` with a `published_at` at or before the close timestamp, selected by latest `published_at` with ties broken by earliest `created_at`; identical order data yields a different adjusted price whenever the index moved between release and close."

        Design: Difficulty/dual_variant_calc/price_adjustment_release_locked_vs_shipment_spot
        """
        ctx = self._setup_two_variant_orders()
        order_a, order_b = ctx["order"], ctx["order_b"]
        run_a = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z")
        run_b = schedule_run(ctx, "2026-08-01T13:00:00Z", "2026-08-01T17:00:00Z",
                             order_id=order_b["id"])
        start_run(run_a["id"])
        complete_run(run_a["id"], 100, ctx["coil"]["id"])
        start_run(run_b["id"])
        complete_run(run_b["id"], 100, ctx["coil"]["id"])
        validate_success(api.complete_production_order(order_a["id"], production_planner_headers))
        validate_success(api.complete_production_order(order_b["id"], production_planner_headers))
        publish_index(1020, published_at="2026-08-05T00:00:00Z")
        set_clock("2026-08-06T00:00:00Z")
        validate_success(api.close_production_order(order_a["id"], production_planner_headers))
        validate_success(api.close_production_order(order_b["id"], production_planner_headers))

        rows_a, _ = validate_paginated(api.list_order_price_adjustments(order_a["id"], cost_analyst_headers))
        rows_b, _ = validate_paginated(api.list_order_price_adjustments(order_b["id"], cost_analyst_headers))
        assert len(rows_a) == 1 and len(rows_b) == 1
        adj_a = rows_a[0]["adjusted_piece_price_cents"]
        adj_b = rows_b[0]["adjusted_piece_price_cents"]
        # Spot at close is 1020: delta 120; pass-through 96; material 8.16 -> 8.
        assert adj_a == 2503
        assert adj_b == 2508
        assert rows_b[0]["applied_index_value"] == 1020
        assert adj_a != adj_b, "identical order data must reprice differently once the index moved"


class TestNestedRoundingOrder:
    def _setup_and_close(self, api, production_planner_headers):
        """Base index 900, release index 950, pass-through 0.5, steel content 1.0 kg:
        the material term lands on exactly 2.5 cents."""
        ctx = setup_completed_order(
            shots_recorded=10, quantity_ordered=10, coil_weight_kg=500,
            customer_overrides={"name": "Gamma Truck", "customer_code": "GAMMA",
                                "base_index_value": 900, "pass_through_pct": 0.5},
            part_overrides={"part_number": "P-300", "material_spec": "DC04",
                            "thickness_mm": 0.8, "net_weight_kg": 0.9,
                            "base_piece_price_cents": 2500},
            gross_weight_per_part_kg=1.0,
            coil_overrides={"material_spec": "DC04", "thickness_mm": 0.8},
            set_clock_first=False,
        )
        return ctx

    def test_material_term_rounds_half_up_before_addition(self, api, production_planner_headers, cost_analyst_headers, plant_admin_headers):
        """PRD §3.10: "Third, the material term in cents is the pass-through amount multiplied by the part's `steel_content_kg`, multiplied by 100, and divided by 1,000 — converting dollars per metric ton into cents per part through the part's steel content. Fourth, the material term is rounded to whole cents, round half up, before any addition takes place; this per-part rounding happens first, deliberately. Fifth, the adjusted piece price is the part's `base_piece_price_cents` plus the rounded material term, yielding integer cents."

        Design: Difficulty/combinatorial_formula/price_adjustment_nested_rounding_order
        """
        set_clock()
        publish_index(950, published_at="2026-08-01T00:00:00Z")
        ctx = self._setup_and_close(api, production_planner_headers)
        validate_success(api.close_production_order(ctx["order"]["id"], production_planner_headers))
        rows, _meta = validate_paginated(
            api.list_order_price_adjustments(ctx["order"]["id"], cost_analyst_headers)
        )
        assert len(rows) == 1
        # delta 50 -> pass-through 25 USD/ton -> material exactly 2.5 cents;
        # round half up gives 3 (banker's rounding would give 2).
        assert rows[0]["adjusted_piece_price_cents"] == 2503, (
            f"expected 2503 via round-half-up of the 2.5-cent material term, got "
            f"{rows[0]['adjusted_piece_price_cents']}"
        )

    def test_adjustment_records_variant_and_applied_index(self, api, production_planner_headers, cost_analyst_headers):
        """PRD §3.10: "At close the system writes a `PriceAdjustment`, an append-only record carrying the `production_order_id`, the `variant_applied`, a snapshot of the customer's `base_index_value`, the `applied_index_value` the variant selected, and the resulting `adjusted_piece_price_cents`."

        Design: Difficulty/combinatorial_formula/price_adjustment_nested_rounding_order
        """
        set_clock()
        publish_index(950, published_at="2026-08-01T00:00:00Z")
        ctx = self._setup_and_close(api, production_planner_headers)
        validate_success(api.close_production_order(ctx["order"]["id"], production_planner_headers))
        rows, _meta = validate_paginated(
            api.list_order_price_adjustments(ctx["order"]["id"], cost_analyst_headers)
        )
        assert len(rows) == 1
        adj = rows[0]
        assert adj["variant_applied"] == "RELEASE_LOCKED"
        assert adj["applied_index_value"] == 950
        assert adj["base_index_value"] == 900
        assert adj["production_order_id"] == ctx["order"]["id"]


class TestPriceFloor:
    def test_index_collapse_below_one_cent_blocks_close(self, api, production_planner_headers, cost_analyst_headers):
        """PRD §3.10: "Finally the floor is enforced: the adjusted piece price must come to at least 1 cent, and if it would not, the close is rejected with `ERR_PRICE_FLOOR_BREACH` (422) and no adjustment is written."

        Design: Corner/errors/price_floor_breach_at_close
        """
        set_clock()
        publish_index(500, published_at="2026-08-01T00:00:00Z")
        # Base price 10 cents, full pass-through, index delta -400: the material
        # term is -34 cents exactly and 10 - 34 = -24 breaches the 1-cent floor.
        ctx = setup_completed_order(
            shots_recorded=10, quantity_ordered=10, coil_weight_kg=100,
            customer_overrides={"name": "Floor Co", "customer_code": "FLOOR",
                                "base_index_value": 900, "pass_through_pct": 1.0},
            part_overrides={"part_number": "P-FLOOR", "base_piece_price_cents": 10},
            set_clock_first=False,
        )
        resp = api.close_production_order(ctx["order"]["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_PRICE_FLOOR_BREACH)
        assert get_order(ctx["order"]["id"])["status"] == "COMPLETED"
        rows, meta = validate_paginated(
            api.list_order_price_adjustments(ctx["order"]["id"], cost_analyst_headers)
        )
        assert rows == [], "no adjustment may be written when the floor is breached"


class TestOutsideProcessingReturns:
    def test_over_return_beyond_quantity_sent_rejected(self, api, shipping_clerk_headers):
        """PRD §3.8: "The cumulative return totals after each receipt may never exceed the `quantity_sent` — an over-shipment is rejected with `ERR_RETURN_QUANTITY_EXCEEDED` (422) — and within that bound the counters simply accumulate."

        Design: Corner/validations/outside_processing_over_return_rejected
        """
        customer = create_customer(name="OP Co", customer_code="OP")
        part = create_part(customer["id"], part_number="P-OP")
        order = create_order(part["id"], quantity_ordered=50)
        opo = validate_success(
            api.create_outside_processing_order(
                create_outside_processing_order_payload(
                    order["id"], operation_type="PLATING", quantity_sent=10
                ),
                shipping_clerk_headers,
            ),
            expected_status=201,
        )
        assert opo["status"] == "SENT"
        resp = api.receive_outside_processing_return(
            opo["id"], {"quantity_returned_good": 11, "quantity_returned_scrap": 0},
            shipping_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDED)
        after = validate_success(api.get_outside_processing_order(opo["id"], shipping_clerk_headers))
        assert after["quantity_returned_good"] == 0
        assert after["quantity_returned_scrap"] == 0
        assert after["status"] == "SENT"
