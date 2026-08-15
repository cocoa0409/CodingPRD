"""Production requirement computation: gross-keyed buffer tiers and pinned
evaluation order (PRD §3.3)."""
from test_helpers import (
    TEST_USERS,
    create_plan,
    create_plant,
    create_product,
    create_store,
    create_order,
    confirm_order,
    lock_order,
    set_clock,
    setup_locked_plan_with_gross,
    validate_success,
)


class TestProductionRequirementChainedTierOrder:
    def test_planned_units_uses_gross_keyed_tier(self, api):
        """PRD §3.3: "Second, a buffer percentage is selected for each product
        keyed on its gross units — never on the later planned figure: below
        1,000 gross units the buffer is 10%." And: "Third, planned units per
        product are the gross units multiplied by one plus the buffer, rounded
        up to a whole unit, and stored in `planned_units_by_product`."

        Design: Difficulty/combinatorial_formula/production_requirement_chained_tier_order
        """
        ctx = setup_locked_plan_with_gross(500, plant_name="Plant Gamma")
        plan = ctx["plan"]
        product_a = ctx["product_a"]

        locked = validate_success(
            api.lock_production_plan(plan["id"], TEST_USERS["planner_headers"])
        )
        assert locked["planned_units_by_product"][product_a["id"]] == 550, (
            f"gross 500 must use 10% tier: planned=ceil(500*1.10)=550, "
            f"got {locked['planned_units_by_product'][product_a['id']]}"
        )
        assert locked["total_planned_units"] == 550

    def test_batches_and_flour_derived_from_planned(self, api):
        """PRD §3.3: "Fourth, `batches_required_by_product` divides each
        product's planned units by the product's `batch_capacity_units`, again
        rounding up." And: "Fifth, `flour_required_kg` sums, across products,
        the product of batches required, `batch_capacity_units`, and
        `unit_weight_g`, multiplied by the standard 60% flour fraction of
        dough weight, then divides by 1,000 to convert grams to kilograms and
        rounds half-up to exactly one decimal place."

        Design: Difficulty/combinatorial_formula/production_requirement_chained_tier_order
        """
        ctx = setup_locked_plan_with_gross(500, plant_name="Plant Gamma 2")
        plan = ctx["plan"]
        product_a = ctx["product_a"]

        locked = validate_success(
            api.lock_production_plan(plan["id"], TEST_USERS["planner_headers"])
        )
        # planned 550 / capacity 240 -> ceil = 3 batches
        assert locked["batches_required_by_product"][product_a["id"]] == 3, (
            f"ceil(550/240) must be 3, got {locked['batches_required_by_product'][product_a['id']]}"
        )
        # flour: 3 * 240 * 500 * 0.60 / 1000 = 216.0 kg
        assert locked["flour_required_kg"] == 216.0, (
            f"3*240*500*0.60/1000 must round-half-up to 216.0, got {locked['flour_required_kg']}"
        )


class TestBufferTierBoundary:
    def test_buffer_tier_boundary_999_vs_1000(self, api):
        """PRD §3.3: "below 1,000 gross units the buffer is 10%; from 1,000 up
        to but not including 5,000 the buffer is 7%."
        PRD §3.3: "Third, planned units per product are the gross units
        multiplied by one plus the buffer, rounded up to a whole unit."

        Design: Corner/calculations/buffer_tier_boundary_999_vs_1000
        """
        # Plan 1: gross 999 -> 10% tier -> planned ceil(999*1.10) = 1099
        ctx1 = setup_locked_plan_with_gross(999, plant_name="Plant P 999")
        plan1 = ctx1["plan"]
        locked1 = validate_success(
            api.lock_production_plan(plan1["id"], TEST_USERS["planner_headers"])
        )
        assert locked1["total_planned_units"] == 1099, (
            f"ceil(999 * 1.10) = 1099, got {locked1['total_planned_units']}"
        )

        # Plan 2: gross 1000 -> 7% tier -> planned ceil(1000*1.07) = 1070
        # Build a separate plant so the LOCKED orders don't mix.
        ctx2 = setup_locked_plan_with_gross(1000, plant_name="Plant P 1000")
        plan2 = ctx2["plan"]
        locked2 = validate_success(
            api.lock_production_plan(plan2["id"], TEST_USERS["planner_headers"])
        )
        assert locked2["total_planned_units"] == 1070, (
            f"ceil(1000 * 1.07) = 1070, got {locked2['total_planned_units']}"
        )
        # Non-monotone: the 1000-unit order plans FEWER units than the 999-unit order.
        assert locked2["total_planned_units"] < locked1["total_planned_units"]
