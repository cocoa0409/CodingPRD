"""Price-fix calculations, weighted-average computation, dual basis, and boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_shipment,
    create_counterparty,
    create_fixed_contract,
    create_ptbf_contract,
    get_contract,
    get_lot_for_shipment,
    record_price_fix,
    receive_shipment,
    set_clock,
    validate_error,
    validate_success,
    walk_shipment_to_arrived,
)

TRADER = TEST_USERS["trader_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestWeightedAvgFixedFutures:
    def test_weighted_avg_fixed_futures_aggregation(self, api):
        """PRD §3.2: "`weighted_avg_fixed_futures_usd` is recomputed as the
        pound-weighted average futures level across **all** of the contract's
        price-fix events — each event contributes its `fix_lbs` times its
        `futures_price_usd_per_lb`, the products summed and divided by the
        total fixed pounds, at 5 decimal places rounded half-up; the value
        stays null until the first fix exists."
        PRD §3.2: "`priced_notional_usd` follows as `fixed_lbs_accum` times
        the sum of `weighted_avg_fixed_futures_usd` and
        `differential_usd_per_lb`, rounded half-up to 2 decimals, and
        `unpriced_lbs` is `total_lbs` minus `fixed_lbs_accum`."

        Design: Corner/calculations/weighted_avg_fixed_futures_aggregation
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-WAVG")
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-WAVG",
                                         total_lbs=10000, differential=0.30)
        record_price_fix(contract["id"], 4000, 1.50, contract["version"])
        c1 = get_contract(contract["id"])
        record_price_fix(contract["id"], 2000, 2.00, c1["version"])
        c2 = get_contract(contract["id"])
        # weighted avg: (4000*1.50 + 2000*2.00) / 6000 = 10000/6000 = 1.66667
        assert c2["weighted_avg_fixed_futures_usd"] == pytest.approx(
            1.66667, abs=1e-5)
        # priced_notional = 6000 * (1.66667 + 0.30) = 6000 * 1.96667 = 11800.02
        assert c2["priced_notional_usd"] == pytest.approx(11800.02, abs=0.01)
        assert c2["pricing_status"] == "PARTIALLY_FIXED"
        assert c2["unpriced_lbs"] == 4000


class TestLandedCostDualBasis:
    def test_landed_cost_fixed_outright_simple(self, api):
        """PRD §2.7: "When a lot is received under a `FIXED_OUTRIGHT`
        contract, its basis is simply the contract's
        `fixed_price_usd_per_lb`."

        Design: Corner/calculations/landed_cost_fixed_outright_simple
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-LC")
        contract = create_fixed_contract(
            supplier["id"], contract_ref="C-LC", total_lbs=1000,
            fixed_price=2.35,
        )
        shipment = book_shipment(contract["id"], shipment_ref="SH-LC",
                                  planned_lbs=1000)
        walk_shipment_to_arrived(shipment["id"])
        receive_shipment(shipment["id"], 1000, lot_code="L-LC")
        lot = get_lot_for_shipment(shipment["id"])
        assert lot["landed_cost_usd_per_lb"] == pytest.approx(2.35, abs=1e-5)


class TestDualVariantCalculation:
    def test_landed_cost_provisional_vs_final_basis(self, api):
        """PRD §2.7: "Under a differential contract with no price-fix
        recorded at receipt time, the basis is provisional: the
        `differential_usd_per_lb` alone, and later price-fixes do **not**
        retroactively revalue the lot. Under a differential contract with at
        least one price-fix already recorded, the basis is final, locked at
        the receipt timestamp as `weighted_avg_fixed_futures_usd` plus
        `differential_usd_per_lb`."

        Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_basis
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-001",
                                        legal_name="Finca Supplier SA",
                                        credit_limit_usd=5000000)
        # C1: UNFIXED at receipt
        c1 = create_ptbf_contract(supplier["id"], contract_ref="C1-UNFIXED",
                                   total_lbs=10000, differential=0.25)
        # C2: will be PARTIALLY_FIXED at receipt (one prior fix @ 1.80)
        c2 = create_ptbf_contract(supplier["id"], contract_ref="C2-FIXED",
                                   total_lbs=10000, differential=0.25)
        record_price_fix(c2["id"], 5000, 1.80, c2["version"])
        sh1 = book_shipment(c1["id"], shipment_ref="SH-C1-001",
                             planned_lbs=4000,
                             scheduled_arrival="2026-09-15T10:00:00Z")
        sh2 = book_shipment(c2["id"], shipment_ref="SH-C2-001",
                             planned_lbs=4000,
                             scheduled_arrival="2026-09-15T10:00:00Z")
        walk_shipment_to_arrived(sh1["id"])
        walk_shipment_to_arrived(sh2["id"])
        receive_shipment(sh1["id"], 4000, lot_code="LOT-C1-A",
                          warehouse_location="WH-A-1")
        receive_shipment(sh2["id"], 4000, lot_code="LOT-C2-A",
                          warehouse_location="WH-A-2")
        lot1 = get_lot_for_shipment(sh1["id"])
        lot2 = get_lot_for_shipment(sh2["id"])
        # C1 UNFIXED: provisional = differential alone
        assert lot1["landed_cost_usd_per_lb"] == pytest.approx(0.25, abs=1e-5)
        # C2 PARTIALLY_FIXED: weighted_avg_fixed_futures (1.80) + diff (0.25) = 2.05
        assert lot2["landed_cost_usd_per_lb"] == pytest.approx(2.05, abs=1e-5)
        assert lot1["landed_cost_usd_per_lb"] != lot2["landed_cost_usd_per_lb"]

    def test_landed_cost_provisional_does_not_retroactively_revalue(self, api):
        """PRD §2.7: "Under a differential contract with no price-fix
        recorded at receipt time, the basis is provisional: the
        `differential_usd_per_lb` alone, and later price-fixes do **not**
        retroactively revalue the lot."

        Design: Difficulty/dual_variant_calc/landed_cost_provisional_vs_final_basis
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-NORETRO",
                                        credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-NR",
                                         total_lbs=10000, differential=0.25)
        sh = book_shipment(contract["id"], shipment_ref="SH-NR",
                            planned_lbs=4000)
        walk_shipment_to_arrived(sh["id"])
        # Receipt BEFORE any fix -> provisional basis = differential alone
        receive_shipment(sh["id"], 4000, lot_code="L-NR")
        lot_at_receipt = get_lot_for_shipment(sh["id"])
        assert lot_at_receipt["landed_cost_usd_per_lb"] == pytest.approx(
            0.25, abs=1e-5)
        # Now post a fix; the previously received lot's basis must NOT move.
        c = get_contract(contract["id"])
        record_price_fix(contract["id"], 1000, 5.00, c["version"])
        lot_after_fix = get_lot_for_shipment(sh["id"])
        assert lot_after_fix["landed_cost_usd_per_lb"] == pytest.approx(
            0.25, abs=1e-5), (
            "later price-fixes do NOT retroactively revalue the lot"
        )

    def test_counterparty_exposure_provisional_vs_final(self, api):
        """PRD §2.7: "The **provisional** variant is used for credit-limit
        gating when a new price-fix is attempted: it sums, over the
        counterparty's contracts whose `fulfillment_status` is `OPEN` or
        `PARTIALLY_RECEIVED`, each contract's `unpriced_lbs` marked at the
        current spot futures level plus the contract's
        `differential_usd_per_lb`. The current spot futures level is the
        `futures_price_usd_per_lb` of the most recent price-fix event
        recorded anywhere in the system, across any contract; if no price-fix
        exists yet anywhere, the fallback marks each unfixed pound at its
        differential alone — a flat price with the futures leg at zero. To
        this the provisional variant adds, for each `FIXED_OUTRIGHT`
        contract, the not-yet-received remainder (total pounds minus
        `received_lbs_accum`) times `fixed_price_usd_per_lb`, and finally
        subtracts, for every futures hedge in `hedge_status` `APPROVED` on
        those contracts, the hedge's pounds times its
        `entry_price_usd_per_lb`."
        PRD §3.2: "The counterparty's `open_exposure_usd` is recomputed, and
        the contract `version` increments by 1."

        Design: Difficulty/dual_variant_calc/counterparty_exposure_provisional_vs_final
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-EXPO", legal_name="Exporter Ltd",
                                        credit_limit_usd=100000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-EXPO",
                                         total_lbs=10000, differential=0.25,
                                         coffee_grade="HG")
        # Record a fix of 4000 lbs at futures 2.00 (latest observed spot = 2.00).
        record_price_fix(contract["id"], 4000, 2.00, contract["version"])
        sup = validate_success(api.get_counterparty(supplier["id"], TRADER))
        # Provisional (used for credit-limit gating):
        #   unpriced 6000 * (2.00 + 0.25) + priced 4000*(2.00+0.25) = 22500.00
        # The contract is OPEN (no receipt), so it contributes.
        assert sup["open_exposure_usd"] == pytest.approx(22500.00, abs=0.01)

    def test_counterparty_exposure_provisional_includes_unfixed_remainder(
            self, api):
        """PRD §2.7: "The **provisional** variant is used for credit-limit
        gating when a new price-fix is attempted: it sums, over the
        counterparty's contracts whose `fulfillment_status` is `OPEN` or
        `PARTIALLY_RECEIVED`, each contract's `unpriced_lbs` marked at the
        current spot futures level plus the contract's
        `differential_usd_per_lb`."
        PRD §2.7: "The **final** variant is used for margin-call evaluation
        and counterparty reporting: it sums only the already-priced
        `priced_notional_usd` of those same `OPEN` or `PARTIALLY_RECEIVED`
        contracts — the unfixed remainder contributes nothing"

        Design: Difficulty/dual_variant_calc/counterparty_exposure_provisional_vs_final
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-EXP2", credit_limit_usd=1000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-EXP2",
                                         total_lbs=10000, differential=0.25)
        # Before any fix: no price-fix exists anywhere, so fallback marks each
        # unfixed pound at its differential alone -> exposure = 10000 * 0.25
        sup0 = validate_success(api.get_counterparty(supplier["id"], TRADER))
        assert sup0["open_exposure_usd"] == pytest.approx(2500.00, abs=0.01)
        # After a fix of 4000 at 2.00, provisional moves to:
        #   priced 4000*(2.00+0.25) + unpriced 6000*(2.00+0.25) = 22500.00
        record_price_fix(contract["id"], 4000, 2.00, contract["version"])
        sup1 = validate_success(api.get_counterparty(supplier["id"], TRADER))
        assert sup1["open_exposure_usd"] == pytest.approx(22500.00, abs=0.01)


class TestOverFixBoundary:
    def test_over_fix_boundary_exact_total_vs_one_over(self, api):
        """PRD §3.2: "A fix whose cumulative total lands exactly on
        `total_lbs` — neither more (that is the over-fix rejection above)
        nor less — carries the contract to `FULLY_FIXED`, whether from
        `UNFIXED` in a single full fix or from `PARTIALLY_FIXED` as the
        final tranche."
        PRD §3.2: "Second the over-fix cap: the cumulative `fixed_lbs_accum`
        plus the new `fix_lbs` must not exceed the contract's `total_lbs`,
        otherwise `ERR_OVER_FIX`."

        Design: Difficulty/boundary_precision_check/over_fix_boundary_exact_total_vs_one_over
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-OFB", credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-OFB",
                                         total_lbs=1000, differential=0.30)
        # Boundary: cumulative exactly at total_lbs is accepted.
        record_price_fix(contract["id"], 1000, 1.80, contract["version"])
        c = get_contract(contract["id"])
        assert c["pricing_status"] == "FULLY_FIXED"
        assert c["fixed_lbs_accum"] == 1000
        # One lb beyond the terminal state: FULLY_FIXED is terminal, so a
        # further fix attempt is rejected at state precondition.
        resp = api.create_price_fix(
            contract["id"],
            {"fix_lbs": 1, "futures_price_usd_per_lb": 1.80,
             "expected_contract_version": c["version"]},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_over_fix_boundary_one_over_rejected(self, api):
        """PRD §3.2: "Second the over-fix cap: the cumulative
        `fixed_lbs_accum` plus the new `fix_lbs` must not exceed the
        contract's `total_lbs`, otherwise `ERR_OVER_FIX`."
        PRD §3.2: "A fix whose cumulative total lands exactly on
        `total_lbs` — neither more (that is the over-fix rejection above)
        nor less — carries the contract to `FULLY_FIXED`"

        Design: Difficulty/boundary_precision_check/over_fix_boundary_exact_total_vs_one_over
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-OFB2", credit_limit_usd=10000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-OFB2",
                                         total_lbs=1000, differential=0.30)
        # fix_lbs = 1001 on the very first call: cumulative 1001 > 1000 -> reject
        resp = api.create_price_fix(
            contract["id"],
            {"fix_lbs": 1001, "futures_price_usd_per_lb": 1.80,
             "expected_contract_version": contract["version"]},
            TRADER,
        )
        validate_error(resp, ApiErrorId.ERR_OVER_FIX)
        # The contract is untouched: still UNFIXED, no fix events persisted
        c = get_contract(contract["id"])
        assert c["pricing_status"] == "UNFIXED"
        assert c["fixed_lbs_accum"] == 0


class TestCombinatorialFormula:
    def test_priced_notional_circular_dependency_pinned_order(self, api):
        """PRD §3.2: "A recorded fix appends an immutable `PriceFixEvent`
        whose `contract_id` ties it to the contract... The contract's
        `fixed_lbs_accum` grows by `fix_lbs`, and
        `weighted_avg_fixed_futures_usd` is recomputed as the pound-weighted
        average futures level across **all** of the contract's price-fix
        events — each event contributes its `fix_lbs` times its
        `futures_price_usd_per_lb`, the products summed and divided by the
        total fixed pounds, at 5 decimal places rounded half-up...
        `priced_notional_usd` follows as `fixed_lbs_accum` times the sum of
        `weighted_avg_fixed_futures_usd` and `differential_usd_per_lb`,
        rounded half-up to 2 decimals."

        Design: Difficulty/combinatorial_formula/priced_notional_circular_dependency_pinned_order
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-CIRC",
                                        legal_name="Circular Co",
                                        credit_limit_usd=1000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-CIRC",
                                         total_lbs=10000, differential=0.50)
        record_price_fix(contract["id"], 4000, 1.50, contract["version"])
        c1 = get_contract(contract["id"])
        # After fix1: wavg = 1.50; notional = 4000 * (1.50 + 0.50) = 8000.00
        assert c1["weighted_avg_fixed_futures_usd"] == pytest.approx(
            1.50, abs=1e-5)
        assert c1["priced_notional_usd"] == pytest.approx(8000.00, abs=0.01)
        # Fix2 completes the total (10000 lbs)
        record_price_fix(contract["id"], 6000, 2.50, c1["version"])
        c2 = get_contract(contract["id"])
        # wavg = (4000*1.50 + 6000*2.50) / 10000 = 21000/10000 = 2.10
        assert c2["weighted_avg_fixed_futures_usd"] == pytest.approx(
            2.10, abs=1e-5)
        # notional = 10000 * (2.10 + 0.50) = 26000.00 (uses updated wavg,
        # not a per-event sum 8000+15000=23000)
        assert c2["priced_notional_usd"] == pytest.approx(26000.00, abs=0.01)
        assert c2["pricing_status"] == "FULLY_FIXED"

    def test_priced_notional_uses_updated_weighted_avg_not_per_event_sum(
            self, api):
        """PRD §3.2: "`priced_notional_usd` follows as `fixed_lbs_accum`
        times the sum of `weighted_avg_fixed_futures_usd` and
        `differential_usd_per_lb`, rounded half-up to 2 decimals, and
        `unpriced_lbs` is `total_lbs` minus `fixed_lbs_accum`."
        PRD §3.2: "`weighted_avg_fixed_futures_usd` is recomputed as the
        pound-weighted average futures level across **all** of the
        contract's price-fix events — each event contributes its `fix_lbs`
        times its `futures_price_usd_per_lb`, the products summed and
        divided by the total fixed pounds, at 5 decimal places rounded
        half-up"

        Design: Difficulty/combinatorial_formula/priced_notional_circular_dependency_pinned_order
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-CIRC2", credit_limit_usd=1000000)
        contract = create_ptbf_contract(supplier["id"], contract_ref="C-CIRC2",
                                         total_lbs=10000, differential=0.50)
        # Single fix covering everything in one shot.
        record_price_fix(contract["id"], 10000, 1.75, contract["version"])
        c = get_contract(contract["id"])
        # Single event: wavg = 1.75
        assert c["weighted_avg_fixed_futures_usd"] == pytest.approx(
            1.75, abs=1e-5)
        # notional = 10000 * (1.75 + 0.50) = 22500.00
        assert c["priced_notional_usd"] == pytest.approx(22500.00, abs=0.01)
        assert c["pricing_status"] == "FULLY_FIXED"
        assert c["unpriced_lbs"] == 0

    def test_blend_allocation_per_component_rounding(self, api):
        """PRD §3.8: "Allocation happens in the same call, atomically, as a
        waterfall over the pinned recipe's components. Components are
        processed in descending order of `component_pct`, ties broken by the
        component's earlier creation. Each component's target is
        `scheduled_green_lbs` times its `component_pct`, rounded half-up to
        whole pounds; the rounding remainder is then reconciled into the
        largest component by percentage (ties again broken by earliest
        creation) so the allocated total equals `scheduled_green_lbs`
        exactly."

        Design: Difficulty/combinatorial_formula/blend_allocation_per_component_rounding
        """
        set_clock()
        # Build RELEASED lots for SHB, HG, NY2_3 at 5000 lbs each.
        shb_ctx = _build_released_lot_for_grade(api, "SHB", "BL-SHB", 5000, 2.00)
        hg_ctx = _build_released_lot_for_grade(api, "HG", "BL-HG", 5000, 1.80)
        ny_ctx = _build_released_lot_for_grade(api, "NY2_3", "BL-NY", 5000, 1.50)

        profile = validate_success(api.create_roast_profile(
            {"profile_code": "RP-STD", "charge_temp_c": 200,
             "target_drop_temp_c": 210, "expected_yield_loss_pct": 0.16,
             "shrinkage_alert_band_pct": 0.02},
            TEST_USERS["head_roaster_headers"]), 201)
        product = validate_success(api.create_product(
            {"sku": "P-BLEND", "display_name": "House Blend",
             "channel": "WHOLESALE", "target_roast_profile_id": profile["id"],
             "freshness_days": 30},
            TEST_USERS["head_roaster_headers"]), 201)
        recipe = validate_success(
            api.create_recipe(product["id"],
                               TEST_USERS["head_roaster_headers"]), 201)
        # Components: 0.334 SHB, 0.333 HG, 0.333 NY2_3 (sum 1.00000)
        validate_success(api.add_recipe_component(
            recipe["id"], {"required_grade": "SHB", "component_pct": 0.334},
            TEST_USERS["head_roaster_headers"]), 201)
        validate_success(api.add_recipe_component(
            recipe["id"], {"required_grade": "HG", "component_pct": 0.333},
            TEST_USERS["head_roaster_headers"]), 201)
        validate_success(api.add_recipe_component(
            recipe["id"], {"required_grade": "NY2_3", "component_pct": 0.333},
            TEST_USERS["head_roaster_headers"]), 201)
        validate_success(api.approve_recipe(
            recipe["id"], {"expected_product_version": product["version"]},
            TEST_USERS["head_roaster_headers"]))

        # Batch of 1001 lbs
        batch = validate_success(api.create_roast_batch(
            {"product_id": product["id"], "recipe_id": recipe["id"],
             "scheduled_green_lbs": 1001},
            TEST_USERS["roast_operator_headers"]), 201)
        allocs, _meta = __import__("test_helpers").validate_paginated(
            api.list_batch_allocations(batch["id"],
                                        TEST_USERS["roast_operator_headers"]))
        # Map component_id -> allocated_lbs by looking up component grade
        components = {}
        comp_list, _ = __import__("test_helpers").validate_paginated(
            api.list_recipe_components(recipe["id"],
                                        TEST_USERS["head_roaster_headers"]))
        for c in comp_list:
            components[c["id"]] = c["required_grade"]
        by_grade = {}
        total = 0
        for a in allocs:
            grade = components[a["component_id"]]
            by_grade[grade] = by_grade.get(grade, 0) + a["allocated_lbs"]
            total += a["allocated_lbs"]
        # Sum equals scheduled_green_lbs exactly.
        assert total == 1001
        # 0.334*1001 = 334.334 -> 334 rounded; +1 reconcile to largest -> 335
        assert by_grade["SHB"] == 335
        # 0.333*1001 = 333.333 -> 333 each (no reconcile)
        assert by_grade["HG"] == 333
        assert by_grade["NY2_3"] == 333

    def test_blend_allocation_exact_no_rounding_reconcile(self, api):
        """PRD §3.8: "Each component's target is `scheduled_green_lbs`
        times its `component_pct`, rounded half-up to whole pounds; the
        rounding remainder is then reconciled into the largest component
        by percentage (ties again broken by earliest creation) so the
        allocated total equals `scheduled_green_lbs` exactly."

        Design: Difficulty/combinatorial_formula/blend_allocation_per_component_rounding
        """
        set_clock()
        _build_released_lot_for_grade(api, "SHB", "BL2-SHB", 5000, 2.00)
        _build_released_lot_for_grade(api, "HG", "BL2-HG", 5000, 1.80)
        _build_released_lot_for_grade(api, "NY2_3", "BL2-NY", 5000, 1.50)
        profile = validate_success(api.create_roast_profile(
            {"profile_code": "RP-STD2", "charge_temp_c": 200,
             "target_drop_temp_c": 210, "expected_yield_loss_pct": 0.16,
             "shrinkage_alert_band_pct": 0.02},
            TEST_USERS["head_roaster_headers"]), 201)
        product = validate_success(api.create_product(
            {"sku": "P-BLEND2", "display_name": "House Blend 2",
             "channel": "WHOLESALE", "target_roast_profile_id": profile["id"],
             "freshness_days": 30},
            TEST_USERS["head_roaster_headers"]), 201)
        recipe = validate_success(
            api.create_recipe(product["id"],
                               TEST_USERS["head_roaster_headers"]), 201)
        for grade, pct in (("SHB", 0.334), ("HG", 0.333), ("NY2_3", 0.333)):
            validate_success(api.add_recipe_component(
                recipe["id"], {"required_grade": grade, "component_pct": pct},
                TEST_USERS["head_roaster_headers"]), 201)
        validate_success(api.approve_recipe(
            recipe["id"], {"expected_product_version": product["version"]},
            TEST_USERS["head_roaster_headers"]))
        # Batch of 1000 lbs: each component rounds cleanly (334, 333, 333).
        batch = validate_success(api.create_roast_batch(
            {"product_id": product["id"], "recipe_id": recipe["id"],
             "scheduled_green_lbs": 1000},
            TEST_USERS["roast_operator_headers"]), 201)
        from test_helpers import validate_paginated as vp
        allocs, _ = vp(api.list_batch_allocations(
            batch["id"], TEST_USERS["roast_operator_headers"]))
        comp_list, _ = vp(api.list_recipe_components(
            recipe["id"], TEST_USERS["head_roaster_headers"]))
        comp_grade = {c["id"]: c["required_grade"] for c in comp_list}
        by_grade = {}
        total = 0
        for a in allocs:
            g = comp_grade[a["component_id"]]
            by_grade[g] = by_grade.get(g, 0) + a["allocated_lbs"]
            total += a["allocated_lbs"]
        assert total == 1000
        # 0.334*1000 = 334.000; 0.333*1000 = 333.000 each — no remainder
        assert by_grade["SHB"] == 334
        assert by_grade["HG"] == 333
        assert by_grade["NY2_3"] == 333


def _build_released_lot_for_grade(api, grade, ref_suffix, received_lbs,
                                    fixed_price):
    """Utility local to this module: build a FIXED_OUTRIGHT contract of the
    given grade, receive it, cup PASS it, and return the lot."""
    supplier = create_counterparty(ref=f"SUP-{ref_suffix}",
                                    credit_limit_usd=10000000)
    contract = create_fixed_contract(
        supplier["id"], contract_ref=f"C-{ref_suffix}",
        total_lbs=received_lbs, fixed_price=fixed_price,
        coffee_grade=grade,
    )
    shipment = book_shipment(contract["id"], shipment_ref=f"SH-{ref_suffix}",
                              planned_lbs=received_lbs)
    walk_shipment_to_arrived(shipment["id"])
    receive_shipment(shipment["id"], received_lbs, lot_code=f"L-{ref_suffix}")
    # Cup PASS: 86 - 0 = 86 >= 80.
    from test_helpers import cup_lot_pass
    cup_lot_pass(shipment["id"])
    return {"supplier": supplier, "contract": contract,
            "shipment": shipment,
            "green_lot": get_lot_for_shipment(shipment["id"])}
