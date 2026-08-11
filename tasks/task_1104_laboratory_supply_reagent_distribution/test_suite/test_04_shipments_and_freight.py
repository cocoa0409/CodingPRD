"""Shipments and freight economics: dual provisional/final variants, the
multi-input freight formula, the free-freight threshold, hazmat load caps,
dry-ice cap, shipment state guards, dispatch gating, and the cost summary."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_shipment,
    get_customer,
    get_lot,
    get_order,
    get_shipment,
    get_success_data,
    make_customer,
    make_customer_headers,
    make_lot,
    make_order,
    make_product,
    make_warehouse,
    make_zone,
    order_line,
    setup_cold_chain_order,
    setup_packed_shipment,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


class TestFreightDualVariant:
    def test_freight_provisional_vs_final_divergence_values(self, api):
        """PRD §3.5: "Freight is priced identically in both its provisional and final variants: a base charge keyed on `shipping_service` — 800 cents for `STANDARD`, 1500 for `EXPRESS`, 2500 for `PRIORITY_OVERNIGHT` — covers the first 5000 grams, and each additional started kilogram beyond that inclusion adds 120 cents; coolant adds nothing for `NONE`, 150 cents per unit for `GEL_PACK`, and 400 per unit for `DRY_ICE`."
        PRD §3.5: "it captures the scale weight into `actual_weight_grams`, recomputes freight in its final variant against that weight and stores it as `final_freight_cents` — the invoiced freight"

        Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_divergence
        """
        ctx = setup_cold_chain_order(api, quantity=2)
        shipment = add_shipment(api, ctx, coolant_type="DRY_ICE", coolant_units=2,
                                declared_weight_grams=3000)
        # EXPRESS base 1500 + no extra weight at 3000 g + 2 x 400 dry ice = 2300.
        assert shipment["provisional_freight_cents"] == 2300, (
            f"provisional must use declared weight: {shipment}"
        )
        get_success_data(api.pack_shipment(shipment["id"], CLERK))

        resp = api.dispatch_shipment(shipment["id"], {"actual_weight_grams": 7500}, CLERK)
        dispatched = validate_success(resp, 200)
        # Final: 1500 base + ceil((7500-5000)/1000) = 3 started kg x 120 = 360 + 800.
        assert dispatched["final_freight_cents"] == 2660, (
            f"final must use actual weight: {dispatched}"
        )
        assert dispatched["status"] == "IN_TRANSIT"
        order = get_order(api, ctx["order"]["id"])
        assert order["status"] == "SHIPPED", "the order advances PACKED -> SHIPPED on dispatch"

    def test_freight_invoice_posts_final_variant_only(self, api):
        """PRD §3.5: "The order advances from `PACKED` to `SHIPPED`, the invoice posts by adding `product_total_cents` plus `final_freight_cents` to the customer's `outstanding_balance_cents`, the auto-suspension check of §3.3 runs,"

        Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_divergence
        """
        ctx = setup_cold_chain_order(api, quantity=2)
        shipment = add_shipment(api, ctx, coolant_type="DRY_ICE", coolant_units=2,
                                declared_weight_grams=3000)
        provisional = shipment["provisional_freight_cents"]
        get_success_data(api.pack_shipment(shipment["id"], CLERK))
        dispatched = validate_success(
            api.dispatch_shipment(shipment["id"], {"actual_weight_grams": 7500}, CLERK), 200
        )
        final = dispatched["final_freight_cents"]
        assert provisional != final, "the two variants diverge on the same order data"

        customer = get_customer(api, ctx["customer"]["id"])
        # 40000 product total + 2660 final freight; the 2300 provisional is never invoiced.
        assert customer["outstanding_balance_cents"] == 40000 + 2660, (
            f"invoice must post the final variant only: {customer}"
        )


class TestFreightMultiInputFormula:
    def _setup_hazmat_allocated_order(self, api, quantity=4):
        warehouse = make_warehouse(api, name="WH-HZ", region_code="US-SW")
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(
            api, sku="HZ-200", name="Solvent X", hazard_class="FLAMMABLE",
            unit_haz_factor=2, max_qty_per_shipment=100, unit_price_cents=10000,
        )
        customer = make_customer(api, name="Lab Beta", hazmat_endorsement="FULL")
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=50)
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], quantity, "ANY")],
        )
        submitted = submit_order(api, order["id"], customer["id"])
        assert submitted["status"] == "ALLOCATED"
        return order

    def test_freight_multi_input_nonlinear_formula_total(self, api):
        """PRD §3.5: "Freight is priced identically in both its provisional and final variants: a base charge keyed on `shipping_service` — 800 cents for `STANDARD`, 1500 for `EXPRESS`, 2500 for `PRIORITY_OVERNIGHT` — covers the first 5000 grams, and each additional started kilogram beyond that inclusion adds 120 cents; coolant adds nothing for `NONE`, 150 cents per unit for `GEL_PACK`, and 400 per unit for `DRY_ICE`. When any line's product is not `NON_HAZARDOUS`, a hazmat surcharge of 25% of that subtotal, rounded half up to whole cents, is added."

        Design: Difficulty/combinatorial_formula/freight_multi_input_nonlinear_formula
        """
        order = self._setup_hazmat_allocated_order(api, quantity=4)
        resp = api.create_shipment(
            {
                "order_id": order["id"],
                "coolant_type": "GEL_PACK",
                "coolant_units": 3,
                "declared_weight_grams": 12500,
            },
            CLERK,
        )
        shipment = validate_success(resp, 201)
        # subtotal = 800 + ceil((12500-5000)/1000)=8 x 120 + 3 x 150 = 2210;
        # surcharge = round_half_up(2210 * 0.25) = round_half_up(552.5) = 553.
        assert shipment["provisional_freight_cents"] == 2763, (
            f"2210 subtotal + 553 half-up surcharge; floor 500 not binding, "
            f"product_total 40000 below the free-freight threshold: {shipment}"
        )

    def test_freight_multi_input_coolant_contribution(self, api):
        """PRD §3.5: "coolant adds nothing for `NONE`, 150 cents per unit for `GEL_PACK`, and 400 per unit for `DRY_ICE`."
        PRD §3.5: "The resulting total is floored at 500 cents — unless the order's `product_total_cents` reaches the free-freight threshold of 250000 cents, in which case freight is zero and the floor and surcharges are skipped entirely."

        Design: Difficulty/combinatorial_formula/freight_multi_input_nonlinear_formula
        """
        order = self._setup_hazmat_allocated_order(api, quantity=4)
        resp = api.create_shipment(
            {
                "order_id": order["id"],
                "coolant_type": "NONE",
                "coolant_units": 0,
                "declared_weight_grams": 12500,
            },
            CLERK,
        )
        shipment = validate_success(resp, 201)
        # subtotal = 800 + 8 x 120 + 0 = 1760; surcharge = round_half_up(440.0) = 440.
        assert shipment["provisional_freight_cents"] == 2200, (
            f"NONE coolant contributes zero to the same subtotal: {shipment}"
        )


class TestFreeFreightThreshold:
    def _setup_order_with_total(self, api, unit_price_cents, quantity):
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(
            api, sku=f"PX-{unit_price_cents}", unit_price_cents=unit_price_cents
        )
        customer = make_customer(api, name="Lab Big", credit_limit_cents=100000000)
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=5)
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], quantity, "ANY")],
        )
        return submit_order(api, order["id"], customer["id"])

    def test_free_freight_at_threshold_pays_zero(self, api):
        """PRD §3.5: "The resulting total is floored at 500 cents — unless the order's `product_total_cents` reaches the free-freight threshold of 250000 cents, in which case freight is zero and the floor and surcharges are skipped entirely."

        Design: Difficulty/boundary_precision_check/free_freight_threshold_boundary
        """
        submitted = self._setup_order_with_total(api, 125000, 2)
        assert submitted["product_total_cents"] == 250000
        resp = api.create_shipment(
            {
                "order_id": submitted["id"],
                "coolant_type": "NONE",
                "coolant_units": 0,
                "declared_weight_grams": 3000,
            },
            CLERK,
        )
        shipment = validate_success(resp, 201)
        assert shipment["provisional_freight_cents"] == 0, (
            "reaching the 250000 threshold makes freight zero, floor skipped"
        )

    def test_free_freight_one_cent_below_pays_base(self, api):
        """PRD §3.5: "The resulting total is floored at 500 cents — unless the order's `product_total_cents` reaches the free-freight threshold of 250000 cents, in which case freight is zero and the floor and surcharges are skipped entirely."
        PRD §3.5: "a base charge keyed on `shipping_service` — 800 cents for `STANDARD`, 1500 for `EXPRESS`, 2500 for `PRIORITY_OVERNIGHT` — covers the first 5000 grams"

        Design: Difficulty/boundary_precision_check/free_freight_threshold_boundary
        """
        submitted = self._setup_order_with_total(api, 249999, 1)
        assert submitted["product_total_cents"] == 249999
        resp = api.create_shipment(
            {
                "order_id": submitted["id"],
                "coolant_type": "NONE",
                "coolant_units": 0,
                "declared_weight_grams": 3000,
            },
            CLERK,
        )
        shipment = validate_success(resp, 201)
        assert shipment["provisional_freight_cents"] == 800, (
            "one cent below the threshold pays the full STANDARD base of 800"
        )


class TestHazmatLoadCaps:
    def _setup_toxic_order(self, api, quantity):
        warehouse = make_warehouse(api, name="WH-HZ", region_code="US-SW")
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(
            api, sku="TX-10", name="Toxin Reagent", hazard_class="TOXIC",
            unit_haz_factor=1, max_qty_per_shipment=100, unit_price_cents=1000,
        )
        customer = make_customer(api, name="Lab Haz", hazmat_endorsement="FULL")
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=30)
        order = make_order(
            api, customer["id"], warehouse["id"],
            [order_line(product["id"], quantity, "ANY")],
        )
        submitted = submit_order(api, order["id"], customer["id"])
        assert submitted["status"] == "ALLOCATED"
        return submitted

    def test_hazmat_class_cap_exactly_at_limit_passes(self, api):
        """PRD §2.10: "The load of each hazard class — the sum, over lines of that class, of line quantity times the product's `unit_haz_factor` — is capped at 30 units for `FLAMMABLE`, 30 for `CORROSIVE`, 10 for `TOXIC`, and 10 for `OXIDIZER`; the aggregate load across all four classes is capped at 50 units."
        PRD §3.5: "the per-class loads — line quantity times `unit_haz_factor`, summed per class — must respect the caps of §2.10, 30 each for `FLAMMABLE` and `CORROSIVE` and 10 each for `TOXIC` and `OXIDIZER` (`ERR_HAZMAT_CLASS_LIMIT_EXCEEDED`)"

        Design: Difficulty/boundary_precision_check/hazmat_class_cap_exactly_at_limit
        """
        order = self._setup_toxic_order(api, 10)
        resp = api.create_shipment(
            {
                "order_id": order["id"],
                "coolant_type": "NONE",
                "coolant_units": 0,
                "declared_weight_grams": 3000,
            },
            CLERK,
        )
        shipment = validate_success(resp, 201)
        assert shipment["id"], "a TOXIC class load of exactly 10 respects the cap (<=, not <)"

    def test_hazmat_class_cap_over_limit_rejected(self, api):
        """PRD §3.5: "the per-class loads — line quantity times `unit_haz_factor`, summed per class — must respect the caps of §2.10, 30 each for `FLAMMABLE` and `CORROSIVE` and 10 each for `TOXIC` and `OXIDIZER` (`ERR_HAZMAT_CLASS_LIMIT_EXCEEDED`)"

        Design: Difficulty/boundary_precision_check/hazmat_class_cap_exactly_at_limit
        """
        order = self._setup_toxic_order(api, 11)
        resp = api.create_shipment(
            {
                "order_id": order["id"],
                "coolant_type": "NONE",
                "coolant_units": 0,
                "declared_weight_grams": 3000,
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_HAZMAT_CLASS_LIMIT_EXCEEDED)
        assert get_order(api, order["id"])["status"] == "ALLOCATED", (
            "the rejected shipment creation frees nothing on the order"
        )

    def test_dry_ice_cap_boundary(self, api):
        """PRD §2.10: "Dry ice is itself a dangerous good: a shipment cooled by `DRY_ICE` may carry at most 20 coolant units."
        PRD §3.5: "and `DRY_ICE` shipments must carry at most 20 coolant units (`ERR_DRY_ICE_LIMIT_EXCEEDED`)."

        Design: Corner/validations/dry_ice_cap_boundary
        """
        ctx_a = setup_cold_chain_order(api, quantity=1)
        ok = api.create_shipment(
            {
                "order_id": ctx_a["order"]["id"],
                "coolant_type": "DRY_ICE",
                "coolant_units": 20,
                "declared_weight_grams": 3000,
            },
            CLERK,
        )
        shipment = validate_success(ok, 201)
        assert shipment["id"], "20 coolant units equals the DRY_ICE cap and passes"

        ctx_b = setup_cold_chain_order(api, quantity=1, product_overrides={"sku": "RG-101"})
        over = api.create_shipment(
            {
                "order_id": ctx_b["order"]["id"],
                "coolant_type": "DRY_ICE",
                "coolant_units": 21,
                "declared_weight_grams": 3000,
            },
            CLERK,
        )
        validate_error(over, ApiErrorId.ERR_DRY_ICE_LIMIT_EXCEEDED)


class TestShipmentStateGuards:
    def test_shipment_deliver_from_created_returns_invalid_state(self, api):
        """PRD §3.5: "Delivery moves the shipment from `IN_TRANSIT` to `DELIVERED` and the order from `SHIPPED` to `DELIVERED`; it is permitted only from `IN_TRANSIT` (`ERR_SHIPMENT_NOT_IN_TRANSIT`) and is blocked while any excursion of the shipment remains `OPEN` (`ERR_DELIVERY_BLOCKED_OPEN_EXCURSION`)."

        Design: Corner/state_machines/shipment_deliver_from_created_returns_invalid_state
        """
        ctx = setup_cold_chain_order(api, quantity=2)
        shipment = add_shipment(api, ctx, coolant_type="DRY_ICE", coolant_units=2,
                                declared_weight_grams=3000)
        resp = api.deliver_shipment(shipment["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_IN_TRANSIT)
        assert get_shipment(api, shipment["id"])["status"] == "CREATED"
        assert get_order(api, ctx["order"]["id"])["status"] == "ALLOCATED", (
            "the rejected delivery must not bubble up to the order"
        )

    def test_order_cancel_after_packed_rejected(self, api):
        """PRD §3.4: "Finally, the customer may cancel an order outright while it is `DRAFT`, `BACKORDERED`, or `ALLOCATED` — any other state yields `ERR_ORDER_NOT_CANCELLABLE` — which releases every `HELD` reservation with compensation and moves every line, from whichever of `PENDING`, `PARTIALLY_ALLOCATED`, or `ALLOCATED` it occupied, to `CANCELLED`."
        PRD §3.5: "Packing — permitted only from `CREATED` (`ERR_SHIPMENT_NOT_PACKABLE`) and only while the order is `ALLOCATED` (`ERR_ORDER_NOT_ALLOCATED`) — commits the allocation: every `HELD` reservation of the order transitions to `COMMITTED`,"

        Design: Corner/state_machines/order_cancel_after_packed_rejected
        """
        ctx = setup_packed_shipment(api, quantity=2)
        resp = api.cancel_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        assert get_order(api, ctx["order"]["id"])["status"] == "PACKED"
        lot = get_lot(api, ctx["lot"]["id"])
        assert lot["quantity_reserved"] == 2, (
            "COMMITTED reservations stay committed when the cancel is rejected"
        )


class TestDispatchRequiresOperationalWarehouse:
    def test_dispatch_requires_warehouse_operational_error(self, api):
        """PRD §3.5: "Dispatch requires `PACKED` (`ERR_SHIPMENT_NOT_DISPATCHABLE`) and an `OPERATIONAL` warehouse for the order (`ERR_WAREHOUSE_NOT_OPERATIONAL`);"

        Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_warehouse_operational
        """
        ctx = setup_packed_shipment(api, quantity=2)
        get_success_data(api.suspend_warehouse(ctx["warehouse"]["id"], OPS))
        resp = api.dispatch_shipment(
            ctx["shipment"]["id"], {"actual_weight_grams": 3000}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_NOT_OPERATIONAL)
        assert get_shipment(api, ctx["shipment"]["id"])["status"] == "PACKED", (
            "the rejected dispatch leaves the shipment PACKED"
        )

    def test_dispatch_blocked_posts_no_invoice(self, api):
        """PRD §3.5: "The order advances from `PACKED` to `SHIPPED`, the invoice posts by adding `product_total_cents` plus `final_freight_cents` to the customer's `outstanding_balance_cents`, the auto-suspension check of §3.3 runs,"
        PRD §3.3: "The outstanding balance is a derived figure, recomputed from its sources: the sum, over the customer's orders in `SHIPPED` or `DELIVERED` status, of each order's `product_total_cents` plus its shipment's `final_freight_cents`;"

        Design: Difficulty/cross_entity_state_dependency/shipment_dispatch_requires_warehouse_operational
        """
        ctx = setup_packed_shipment(api, quantity=2)
        get_success_data(api.suspend_warehouse(ctx["warehouse"]["id"], OPS))
        resp = api.dispatch_shipment(
            ctx["shipment"]["id"], {"actual_weight_grams": 3000}, CLERK
        )
        validate_error(resp, ApiErrorId.ERR_WAREHOUSE_NOT_OPERATIONAL)
        customer = get_customer(api, ctx["customer"]["id"])
        assert customer["outstanding_balance_cents"] == 0, (
            "no invoice posts when dispatch is rejected"
        )


class TestCostSummary:
    def test_cost_summary_computed_read(self, api):
        """PRD §3.5: "Freight visibility is available throughout: a computed read on the order returns its `product_total_cents`, the shipment's `provisional_freight_cents` and `final_freight_cents`, the `freight_to_product_ratio`, and the `projected_outstanding_cents` impact of the order on the customer's balance."
        PRD §3.5: "the invoice posts by adding `product_total_cents` plus `final_freight_cents` to the customer's `outstanding_balance_cents`"

        Design: Corner/endpoints/cost_summary_computed_read
        """
        ctx = setup_cold_chain_order(api, quantity=2)
        shipment = add_shipment(api, ctx, coolant_type="DRY_ICE", coolant_units=2,
                                declared_weight_grams=3000)
        get_success_data(api.pack_shipment(shipment["id"], CLERK))
        get_success_data(
            api.dispatch_shipment(shipment["id"], {"actual_weight_grams": 7500}, CLERK)
        )

        resp = api.get_cost_summary(ctx["order"]["id"], ACCOUNTS)
        summary = validate_success(resp, 200)
        assert summary["product_total_cents"] == 40000
        assert summary["provisional_freight_cents"] == 2300
        assert summary["final_freight_cents"] == 2660
        assert summary["freight_to_product_ratio"] == pytest.approx(0.0665, abs=1e-6), (
            f"2660 / 40000: {summary}"
        )
        assert summary["projected_outstanding_cents"] == 42660, (
            "post-dispatch the projected outstanding includes the posted invoice"
        )
