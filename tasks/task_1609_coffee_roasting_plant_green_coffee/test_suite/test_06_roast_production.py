"""Roast production: recipe approval, batch lifecycle, yield, void cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    approve_recipe,
    book_shipment,
    create_batch,
    create_counterparty,
    create_draft_recipe,
    create_fixed_contract,
    create_product,
    create_product_with_recipe,
    create_roast_profile,
    cup_batch_pass,
    cup_lot_pass,
    finish_batch,
    get_contract,
    get_lot_for_shipment,
    pack_batch,
    receive_shipment,
    set_clock,
    setup_packed_batch,
    setup_released_lot,
    setup_roasted_batch,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
    walk_shipment_to_arrived,
)

TRADER = TEST_USERS["trader_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
ROAST_OP = TEST_USERS["roast_operator_headers"]
HEAD_ROASTER = TEST_USERS["head_roaster_headers"]
QA = TEST_USERS["qa_grader_headers"]


class TestContractParallelAxes:
    def test_contract_parallel_pricing_x_fulfillment(self, api):
        """PRD §3.1: "A new contract's two parallel state dials start at
        `fulfillment_status` `OPEN` on the receipt side. On the pricing
        side, a differential contract starts at `pricing_status` `UNFIXED`
        with `fixed_lbs_accum` zero."
        PRD §3.2: "A fix that leaves pounds still unpriced carries the
        contract from `UNFIXED` to `PARTIALLY_FIXED`. A fix whose cumulative
        total lands exactly on `total_lbs` — neither more (that is the
        over-fix rejection above) nor less — carries the contract to
        `FULLY_FIXED`, whether from `UNFIXED` in a single full fix or from
        `PARTIALLY_FIXED` as the final tranche."
        PRD §3.4: "Receipt rolls uphill. The contract's `received_lbs_accum`
        is recomputed as the sum of lot `received_lbs` across its shipments
        in `RECEIVED` or later; crossing above zero for the first time moves
        `fulfillment_status` from `OPEN` to `PARTIALLY_RECEIVED`, and
        reaching `total_lbs` exactly moves it on to `FULLY_RECEIVED`."

        Design: Difficulty/non_linear_state_machine/contract_parallel_pricing_x_fulfillment
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-PAR",
                                        legal_name="Parallel Supplier",
                                        credit_limit_usd=5000000)
        contract = create_ptbf_contract_local(api, supplier["id"],
                                               ref="C-PAR",
                                               total_lbs=10000,
                                               differential=0.30)
        # Step 1: receive 4000 lbs -> fulfillment PARTIALLY_RECEIVED, pricing UNFIXED
        sh1 = book_shipment(contract["id"], shipment_ref="SH-P1",
                             planned_lbs=4000)
        walk_shipment_to_arrived(sh1["id"])
        receive_shipment(sh1["id"], 4000, lot_code="L-P1")
        c1 = get_contract(contract["id"])
        assert c1["pricing_status"] == "UNFIXED"
        assert c1["fulfillment_status"] == "PARTIALLY_RECEIVED"
        # Step 2: fix 3000 lbs -> pricing PARTIALLY_FIXED, fulfillment unchanged
        from test_helpers import record_price_fix
        record_price_fix(contract["id"], 3000, 1.80, c1["version"])
        c2 = get_contract(contract["id"])
        assert c2["pricing_status"] == "PARTIALLY_FIXED"
        assert c2["fulfillment_status"] == "PARTIALLY_RECEIVED"
        # Step 3: receive remaining 6000 lbs -> fulfillment FULLY_RECEIVED
        sh2 = book_shipment(contract["id"], shipment_ref="SH-P2",
                             planned_lbs=6000,
                             scheduled_arrival="2026-10-01T00:00:00Z")
        walk_shipment_to_arrived(sh2["id"])
        receive_shipment(sh2["id"], 6000, lot_code="L-P2")
        c3 = get_contract(contract["id"])
        assert c3["pricing_status"] == "PARTIALLY_FIXED"
        assert c3["fulfillment_status"] == "FULLY_RECEIVED"
        # Step 4: fix remaining 7000 lbs -> pricing FULLY_FIXED
        record_price_fix(contract["id"], 7000, 2.00, c3["version"])
        c4 = get_contract(contract["id"])
        assert c4["pricing_status"] == "FULLY_FIXED"
        assert c4["fulfillment_status"] == "FULLY_RECEIVED"

    def test_contract_pricing_axis_advances_after_fully_received(self, api):
        """PRD §3.2: "State preconditions apply before all of these: the
        contract must be a `DIFFERENTIAL_PTBF` contract — a fix attempt
        against an outright contract is rejected with `ERR_INVALID_STATE`
        — and its `fulfillment_status` must be `OPEN`,
        `PARTIALLY_RECEIVED`, or `FULLY_RECEIVED`, since pricing
        legitimately continues after the coffee has finished arriving"
        PRD §3.4: "reaching `total_lbs` exactly moves it on to
        `FULLY_RECEIVED`."

        Design: Difficulty/non_linear_state_machine/contract_parallel_pricing_x_fulfillment
        """
        set_clock()
        supplier = create_counterparty(ref="SUP-PAR2", credit_limit_usd=5000000)
        contract = create_ptbf_contract_local(api, supplier["id"],
                                               ref="C-PAR2",
                                               total_lbs=2000,
                                               differential=0.30)
        # Receive the full contract first (fulfillment axis fully advanced)
        sh = book_shipment(contract["id"], shipment_ref="SH-PAR2",
                            planned_lbs=2000)
        walk_shipment_to_arrived(sh["id"])
        receive_shipment(sh["id"], 2000, lot_code="L-PAR2")
        c1 = get_contract(contract["id"])
        assert c1["fulfillment_status"] == "FULLY_RECEIVED"
        assert c1["pricing_status"] == "UNFIXED"
        # Pricing can still advance: post a fix on a FULLY_RECEIVED contract.
        from test_helpers import record_price_fix
        record_price_fix(contract["id"], 2000, 1.90, c1["version"])
        c2 = get_contract(contract["id"])
        assert c2["pricing_status"] == "FULLY_FIXED"
        # Fulfillment axis unchanged by pricing
        assert c2["fulfillment_status"] == "FULLY_RECEIVED"


def create_ptbf_contract_local(api, counterparty_id, ref, total_lbs,
                                 differential):
    """Local helper — PTBF contract creation."""
    from test_helpers import create_ptbf_contract
    return create_ptbf_contract(counterparty_id, contract_ref=ref,
                                 total_lbs=total_lbs,
                                 differential=differential)


class TestCrossEntityStateDependency:
    def test_roast_start_blocked_by_stale_recipe_version(self, api):
        """PRD §3.8: "Starting the roast — `SCHEDULED` to `IN_DRUM` —
        re-validates the world. The pinned recipe must still be `APPROVED`
        and its current `recipe_version` must still equal
        `recipe_version_pinned`; a recipe superseded since scheduling trips
        this stale-recipe guard and the start is rejected with
        `ERR_INVALID_STATE`."
        PRD §3.7: "On approval the recipe moves from `DRAFT` to `APPROVED`,
        `approved_at` is stamped from the server clock, any previously
        `APPROVED` recipe for the same product auto-transitions from
        `APPROVED` to `SUPERSEDED`, and both the recipe and the product
        increment their `version`"

        Design: Difficulty/cross_entity_state_dependency/roast_start_blocked_by_stale_recipe_version
        """
        set_clock()
        # Build a RELEASED SHB lot large enough for the batch.
        ctx = setup_released_lot(supplier_ref="SUP-XD", contract_ref="C-XD",
                                  shipment_ref="SH-XD", lot_code="L-XD",
                                  received_lbs=5000, fixed_price=2.00,
                                  coffee_grade="SHB")
        profile = create_roast_profile(profile_code="RP-XD")
        product = create_product(profile["id"], sku="P-XD",
                                  display_name="Xdep Product")
        # Recipe R1 APPROVED (version 1)
        r1 = create_draft_recipe(product["id"])
        add_component(r1["id"], required_grade="SHB", component_pct=1.0)
        r1 = approve_recipe(r1["id"], product["version"])
        assert r1["recipe_version"] == 1
        # Schedule batch pinned to R1
        batch = create_batch(product["id"], r1["id"], 100)
        assert batch["recipe_version_pinned"] == 1
        # R2 approved for same product; R1 becomes SUPERSEDED; Product.version bumps.
        product_now = validate_success(api.get_product(product["id"],
                                                        HEAD_ROASTER))
        r2 = create_draft_recipe(product["id"])
        add_component(r2["id"], required_grade="SHB", component_pct=1.0)
        r2 = approve_recipe(r2["id"], product_now["version"])
        assert r2["recipe_version"] == 2
        # R1 is now SUPERSEDED; batch's pinned version (1) is stale.
        resp = api.start_roast_batch(batch["id"], ROAST_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        # Batch remains SCHEDULED
        batch_after = validate_success(api.get_roast_batch(batch["id"],
                                                            ROAST_OP))
        assert batch_after["production_status"] == "SCHEDULED"

    def test_roast_start_succeeds_on_current_recipe_version(self, api):
        """PRD §3.8: "Starting the roast — `SCHEDULED` to `IN_DRUM` —
        re-validates the world. The pinned recipe must still be
        `APPROVED` and its current `recipe_version` must still equal
        `recipe_version_pinned`; a recipe superseded since scheduling
        trips this stale-recipe guard and the start is rejected with
        `ERR_INVALID_STATE`."
        PRD §3.8: "Starting consumes the inputs: every allocation moves
        from `ACTIVE` to `CONSUMED`, each referenced lot's `available_lbs`
        falls by its allocated pounds"

        Design: Difficulty/cross_entity_state_dependency/roast_start_blocked_by_stale_recipe_version
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-XD2",
                                  contract_ref="C-XD2",
                                  shipment_ref="SH-XD2", lot_code="L-XD2",
                                  received_lbs=5000, fixed_price=2.00,
                                  coffee_grade="SHB")
        lot = ctx["green_lot"]
        profile = create_roast_profile(profile_code="RP-XD2")
        product = create_product(profile["id"], sku="P-XD2")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        batch = create_batch(product["id"], recipe["id"], 500)
        # Recipe has not been superseded; start succeeds.
        batch = start_batch(batch["id"])
        assert batch["production_status"] == "IN_DRUM"
        # Lot available_lbs fell by the batch's allocated pounds
        lot_after = validate_success(api.get_green_lot(lot["id"], TRADER))
        assert lot_after["available_lbs"] == 4500


class TestYieldVarianceBoundary:
    def test_yield_variance_flag_within_band_at_boundary(self, api):
        """PRD §3.8: "The batch's `actual_yield_loss_pct` is computed as one
        minus the ratio of `actual_roasted_lbs` to `scheduled_green_lbs`,
        at 5 decimal places rounded half-up, and its `yield_variance_flag`
        is set against the product's roast profile: strictly above
        `expected_yield_loss_pct` plus `shrinkage_alert_band_pct` is
        `ABOVE_BAND`, strictly below the expectation minus the band is
        `BELOW_BAND`, and anything in between — including exactly on either
        boundary — is `WITHIN_BAND`."

        Design: Corner/calculations/yield_variance_flag_within_band_at_boundary
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-YB", contract_ref="C-YB",
                                  shipment_ref="SH-YB", lot_code="L-YB",
                                  received_lbs=5000, fixed_price=2.00,
                                  coffee_grade="SHB")
        profile = create_roast_profile(
            profile_code="RP-YB", expected_yield_loss_pct=0.16,
            shrinkage_alert_band_pct=0.02,
        )
        product = create_product(profile["id"], sku="P-YB",
                                  display_name="Yield Bnd P")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        batch = create_batch(product["id"], recipe["id"], 1000)
        start_batch(batch["id"])
        # 1 - 820/1000 = 0.18 == expected (0.16) + band (0.02) -> WITHIN_BAND
        batch = finish_batch(batch["id"], 820)
        assert batch["actual_yield_loss_pct"] == pytest.approx(0.18, abs=1e-5)
        assert batch["yield_variance_flag"] == "WITHIN_BAND"


class TestInsufficientGreenInventory:
    def test_insufficient_green_inventory_rejected(self, api):
        """PRD §3.8: "Creation runs the inventory check first — sufficient
        `RELEASED` green mass must exist to satisfy every component, within
        the substitution rules, otherwise `ERR_INSUFFICIENT_GREEN_INVENTORY`"

        Design: Corner/validations/insufficient_green_inventory_rejected
        """
        set_clock()
        # Only 600 lbs SHB RELEASED.
        setup_released_lot(supplier_ref="SUP-ISG", contract_ref="C-ISG",
                            shipment_ref="SH-ISG", lot_code="L-ISG",
                            received_lbs=600, fixed_price=2.00,
                            coffee_grade="SHB")
        profile = create_roast_profile(profile_code="RP-ISG")
        product = create_product(profile["id"], sku="P-ISG")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        # Batch wants 1000 lbs; only 600 available -> ERR_INSUFFICIENT_GREEN_INVENTORY
        resp = api.create_roast_batch(
            {"product_id": product["id"], "recipe_id": recipe["id"],
             "scheduled_green_lbs": 1000},
            ROAST_OP,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_GREEN_INVENTORY)


class TestRecipeNotApproved:
    def test_recipe_not_approved_rejected_on_batch_create(self, api):
        """PRD §3.8: "the pinned recipe must be `APPROVED` and must belong
        to the specified product, otherwise `ERR_RECIPE_NOT_APPROVED`."

        Design: Corner/validations/recipe_not_approved_rejected_on_batch_create
        """
        set_clock()
        profile = create_roast_profile(profile_code="RP-RNA")
        product = create_product(profile["id"], sku="P-RNA")
        # DRAFT recipe (never approved).
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        resp = api.create_roast_batch(
            {"product_id": product["id"], "recipe_id": recipe["id"],
             "scheduled_green_lbs": 100},
            ROAST_OP,
        )
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_APPROVED)


class TestRecipeComponentSumValidation:
    def test_recipe_component_sum_invalid(self, api):
        """PRD §3.7: "first the component-sum check — the `component_pct`
        values across all of the recipe's components must sum to exactly
        1.00000 at five-decimal precision, otherwise
        `ERR_RECIPE_COMPONENT_SUM_INVALID`"

        Design: Corner/validations/recipe_component_sum_invalid
        """
        set_clock()
        profile = create_roast_profile(profile_code="RP-RCS")
        product = create_product(profile["id"], sku="P-RCS")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=0.5)
        add_component(recipe["id"], required_grade="HG", component_pct=0.49999)
        resp = api.approve_recipe(
            recipe["id"],
            {"expected_product_version": product["version"]},
            HEAD_ROASTER,
        )
        validate_error(resp, ApiErrorId.ERR_RECIPE_COMPONENT_SUM_INVALID)


class TestSubstitutionRule:
    def test_substitution_rule_invalid(self, api):
        """PRD §3.7: "The pair is all-or-nothing: `substitution_grade` is
        non-null exactly when `substitution_max_pct` is non-null, and any
        inconsistency — a grade without a cap, a cap without a grade, or a
        substitute equal to the required grade — is rejected with
        `ERR_SUBSTITUTION_RULE_INVALID`, both when a component is added and
        again at approval time."

        Design: Corner/validations/substitution_rule_invalid
        """
        set_clock()
        profile = create_roast_profile(profile_code="RP-SUB")
        product = create_product(profile["id"], sku="P-SUB")
        recipe = create_draft_recipe(product["id"])
        # substitution_grade set but substitution_max_pct missing.
        resp = api.add_recipe_component(
            recipe["id"],
            {"required_grade": "SHB", "component_pct": 1.0,
             "substitution_grade": "HG"},
            HEAD_ROASTER,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTION_RULE_INVALID)


class TestInvalidPackQuantity:
    def test_invalid_pack_quantity_zero_or_over(self, api):
        """PRD §3.8: "Packing — `ROASTED` to `PACKED` — is allowed only
        after the batch's `qc_status` is `QC_PASSED`, and the `packed_lbs`
        must be strictly positive and no more than `actual_roasted_lbs`,
        otherwise `ERR_INVALID_PACK_QUANTITY`."

        Design: Corner/validations/invalid_pack_quantity_zero_or_over
        """
        set_clock()
        ctx = setup_roasted_batch(
            supplier_ref="SUP-IPQ", product_sku="P-IPQ",
            scheduled_green_lbs=100, actual_roasted_lbs=84,
        )
        batch = ctx["batch"]
        cup_batch_pass(batch["id"])
        # 200 > actual_roasted_lbs=84 -> ERR_INVALID_PACK_QUANTITY
        resp = api.pack_roast_batch(batch["id"], {"packed_lbs": 200}, ROAST_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_PACK_QUANTITY)


class TestInvalidYield:
    def test_invalid_yield_zero_or_full(self, api):
        """PRD §3.8: "The operator reports `actual_roasted_lbs`, which must
        be strictly positive and strictly less than `scheduled_green_lbs`;
        a zero or a hundred-percent yield is physically impossible and is
        rejected with `ERR_INVALID_YIELD`."

        Design: Corner/validations/invalid_yield_zero_or_full
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-IY", contract_ref="C-IY",
                                  shipment_ref="SH-IY", lot_code="L-IY",
                                  received_lbs=5000, fixed_price=2.00,
                                  coffee_grade="SHB")
        profile = create_roast_profile(profile_code="RP-IY")
        product = create_product(profile["id"], sku="P-IY")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        batch = create_batch(product["id"], recipe["id"], 100)
        start_batch(batch["id"])
        # actual_roasted_lbs == scheduled_green_lbs (zero shrinkage)
        resp = api.finish_roast_batch(batch["id"],
                                       {"actual_roasted_lbs": 100}, ROAST_OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_YIELD)


class TestCompensatingInvariant:
    def test_green_lot_mass_conserved_under_void(self, api):
        """PRD §3.8: "Finally, a batch still in `SCHEDULED` can be voided:
        voiding moves it to `VOIDED`, releases every allocation from
        `ACTIVE` back to `RELEASED`, returns the mass to each lot's
        `available_lbs`, and recomputes the position."
        PRD §3.4: "its `available_lbs` is derived as its `received_lbs`
        minus any `ACTIVE` roast allocations against it minus any pounds
        pledged under active financing reserves."

        Design: Difficulty/compensating_invariant/green_lot_mass_conserved_under_void
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-INV", contract_ref="C-INV",
                                  shipment_ref="SH-INV", lot_code="L-INV",
                                  received_lbs=2000, fixed_price=2.00,
                                  coffee_grade="SHB")
        lot = ctx["green_lot"]
        lot_before = validate_success(api.get_green_lot(lot["id"], TRADER))
        assert lot_before["available_lbs"] == 2000
        # Build an APPROVED recipe (1.0 SHB) and a batch consuming 700 lbs.
        profile = create_roast_profile(profile_code="RP-INV")
        product = create_product(profile["id"], sku="P-INV")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        batch = create_batch(product["id"], recipe["id"], 700)
        lot_mid = validate_success(api.get_green_lot(lot["id"], TRADER))
        assert lot_mid["available_lbs"] == 1300, (
            "forward action debits available_lbs by 700"
        )
        # Compensating action: void the batch, mass returns exactly.
        validate_success(api.void_roast_batch(batch["id"], ROAST_OP))
        lot_after = validate_success(api.get_green_lot(lot["id"], TRADER))
        assert lot_after["available_lbs"] == 2000, (
            "void credits back available_lbs exactly (zero drift)"
        )
        batch_after = validate_success(api.get_roast_batch(batch["id"],
                                                            ROAST_OP))
        assert batch_after["production_status"] == "VOIDED"

    def test_green_lot_mass_conserved_under_void_allocations_released(
            self, api):
        """PRD §3.8: "voiding moves it to `VOIDED`, releases every
        allocation from `ACTIVE` back to `RELEASED`, returns the mass to
        each lot's `available_lbs`, and recomputes the position."
        PRD §3.8: "Allocation happens in the same call, atomically, as a
        waterfall over the pinned recipe's components... Each allocation
        row records its `roast_batch_id`, `green_lot_id`, and
        `component_id`, with a strictly positive `allocated_lbs`, and
        starts `ACTIVE`"

        Design: Difficulty/compensating_invariant/green_lot_mass_conserved_under_void
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-INV2",
                                  contract_ref="C-INV2",
                                  shipment_ref="SH-INV2", lot_code="L-INV2",
                                  received_lbs=2000, fixed_price=2.00,
                                  coffee_grade="SHB")
        lot = ctx["green_lot"]
        profile = create_roast_profile(profile_code="RP-INV2")
        product = create_product(profile["id"], sku="P-INV2")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        batch = create_batch(product["id"], recipe["id"], 700)
        # Allocations are born ACTIVE
        allocs, _ = validate_paginated(api.list_batch_allocations(
            batch["id"], ROAST_OP))
        assert len(allocs) >= 1
        for a in allocs:
            assert a["allocation_status"] == "ACTIVE"
        # Void transitions every allocation ACTIVE -> RELEASED
        validate_success(api.void_roast_batch(batch["id"], ROAST_OP))
        allocs_after, _ = validate_paginated(api.list_batch_allocations(
            batch["id"], ROAST_OP))
        for a in allocs_after:
            assert a["allocation_status"] == "RELEASED", (
                "voiding releases every allocation"
            )
        # Lot available returns exactly
        lot_after = validate_success(api.get_green_lot(lot["id"], TRADER))
        assert lot_after["available_lbs"] == 2000

    def test_derived_field_position_open_to_sell_reconciles_on_void(self, api):
        """PRD §2.6: "From these, `open_to_sell_lbs` is what remains once
        commitments and financing pledges are subtracted from the physical
        pile: physical minus committed minus reserved. This value must
        remain greater than or equal to zero at all times; any mutation
        that would drive it negative is rejected rather than applied."
        PRD §3.8: "voiding moves it to `VOIDED`, releases every allocation
        from `ACTIVE` back to `RELEASED`, returns the mass to each lot's
        `available_lbs`, and recomputes the position."

        Design: Corner/complexity_layers/derived_field_position_open_to_sell_reconciles_on_void
        """
        set_clock()
        ctx = setup_released_lot(supplier_ref="SUP-DF", contract_ref="C-DF",
                                  shipment_ref="SH-DF", lot_code="L-DF",
                                  received_lbs=2000, fixed_price=2.00,
                                  coffee_grade="SHB")
        profile = create_roast_profile(profile_code="RP-DF")
        product = create_product(profile["id"], sku="P-DF")
        recipe = create_draft_recipe(product["id"])
        add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
        recipe = approve_recipe(recipe["id"], product["version"])
        pos_before = validate_success(api.get_warehouse_position(TRADER))
        assert pos_before["open_to_sell_lbs"] == 2000
        batch = create_batch(product["id"], recipe["id"], 700)
        pos_mid = validate_success(api.get_warehouse_position(TRADER))
        assert pos_mid["open_to_sell_lbs"] == 1300
        validate_success(api.void_roast_batch(batch["id"], ROAST_OP))
        pos_after = validate_success(api.get_warehouse_position(TRADER))
        assert pos_after["open_to_sell_lbs"] == 2000
