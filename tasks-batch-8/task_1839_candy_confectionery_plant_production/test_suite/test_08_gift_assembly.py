"""Gift-set assembly: pinned per-line price rounding, FEFO component backflush,
and the component-pool sufficiency gate."""
from test_helpers import (
    OPERATOR,
    ApiErrorId,
    add_gift_component,
    complete_run,
    complete_run_payload,
    create_packaging_component,
    create_product,
    create_published_window,
    create_quality_hold,
    create_recipe,
    create_run,
    get_lot,
    get_run,
    prepare_line,
    produce_lot,
    set_clock,
    start_run,
    validate_error,
)

BAR_RECIPE = dict(shape_code="BAR", cook_temp_min_c=80, cook_temp_max_c=90,
                  temper_exit_min_c=28, temper_exit_max_c=30, allergens=[])


def _setup_gift_floor(api, component_specs, gift_spec):
    """Component products/lots plus a GIFT_SET product with its bill of material,
    a BAR line, and a published BASE window.

    component_specs: [{"sku", "base_price_cents", "qty_per_set", "lots": [units...]}]
    gift_spec: {"sku", "base_price_cents"}
    Returns a dict with window/line/component, gift product + recipe, and per-
    component {"product", "recipe", "lots"} entries."""
    set_clock("2026-09-01T00:00:00Z")
    component = create_packaging_component()
    line, _mold = prepare_line(shape_code="BAR")
    window = create_published_window(season_code="BASE", target_units=5000)

    components = []
    for i, spec in enumerate(component_specs):
        product = create_product(component["id"], sku_code=spec["sku"],
                                 base_price_cents=spec["base_price_cents"],
                                 shelf_life_days=spec.get("shelf_life_days", 200))
        recipe = create_recipe(product["id"], name=f"{spec['sku']} mass",
                               standard_yield_pct=0.95, **BAR_RECIPE)
        lots = []
        for j, units in enumerate(spec.get("lots", [])):
            complete_clock = spec.get("complete_clock")
            if complete_clock:
                set_clock(complete_clock if not isinstance(complete_clock, list)
                          else complete_clock[j])
            _run, lot = produce_lot(
                window["id"], product["id"], recipe["id"], line["id"],
                planned_units=units, output_units=units,
                scheduled_start=f"2026-09-{5 + i + j:02d}T08:00:00Z",
                scheduled_end=f"2026-09-{5 + i + j:02d}T16:00:00Z")
            lots.append(lot)
        components.append({"product": product, "recipe": recipe, "lots": lots})

    gift = create_product(component["id"], sku_code=gift_spec["sku"],
                          product_type="GIFT_SET",
                          base_price_cents=gift_spec["base_price_cents"],
                          unit_weight_grams=700, shelf_life_days=120)
    gift_recipe = create_recipe(gift["id"], name="Assembly spec",
                                standard_yield_pct=1.0, **BAR_RECIPE)
    for spec, entry in zip(component_specs, components):
        add_gift_component(gift["id"], entry["product"]["id"], spec["qty_per_set"])

    return {"component": component, "line": line, "window": window,
            "gift": gift, "gift_recipe": gift_recipe, "components": components}


def _create_gift_run(ctx, planned_units, day="2026-09-07"):
    return create_run(ctx["window"]["id"], ctx["gift"]["id"],
                      ctx["gift_recipe"]["id"], ctx["line"]["id"],
                      run_type="GIFT_ASSEMBLY", planned_units=planned_units,
                      scheduled_start=f"{day}T08:00:00Z",
                      scheduled_end=f"{day}T16:00:00Z")


class TestGiftKitPriceRounding:
    def _setup(self, api):
        return _setup_gift_floor(
            api,
            [{"sku": "PRC-A", "base_price_cents": 1006, "qty_per_set": 1,
              "lots": [10]},
             {"sku": "PRC-B", "base_price_cents": 506, "qty_per_set": 1,
              "lots": [10]}],
            {"sku": "GIFT-01", "base_price_cents": 2000})

    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.6: "for each bill-of-material row, the component product's
        current `base_price_cents` is multiplied by `qty_per_set` and reduced by
        the kit discount of ten percent, and that per-line amount is rounded
        half-up to a whole cent; the gift lot's `unit_price_cents` is the sum of
        those rounded per-line amounts."
        PRD §3.6: "The rounding order is pinned — round each component line first,
        then sum — because summing first and rounding once can differ by a cent,
        and the per-line order is the contract."

        Design: Difficulty/combinatorial_formula/gift_kit_per_line_rounding
        """
        ctx = self._setup(api)
        run = _create_gift_run(ctx, 5)
        start_run(run["id"])
        done = complete_run(run["id"], output_units=5)

        lot = get_lot(done["created_lot_id"])
        # round_half_up(1006 * 0.9) = 905; round_half_up(506 * 0.9) = 455.
        assert lot["unit_price_cents"] == 1360, "905 + 455, per-line then summed"
        assert lot["unit_price_cents"] != 1361, "the sum-then-round order is not the contract"
        assert lot["qty_on_hand"] == 5
        assert lot["status"] == "ACTIVE"
        assert lot["quality_status"] == "OK"

    def test_components_backflushed_by_qty_per_set_times_output(self, api):
        """PRD §3.6: "For each component product in the gift set's bill of
        material, the need is the row's `qty_per_set` multiplied by the reported
        `output_units`."

        Design: Difficulty/combinatorial_formula/gift_kit_per_line_rounding
        """
        ctx = self._setup(api)
        run = _create_gift_run(ctx, 5)
        start_run(run["id"])
        complete_run(run["id"], output_units=5)

        for entry in ctx["components"]:
            lot = get_lot(entry["lots"][0]["id"])
            assert lot["qty_on_hand"] == 5, "10 on hand minus 1 x 5 backflushed"
            assert lot["status"] == "ACTIVE"


class TestGiftComponentPoolGate:
    def _setup(self, api, extra_active_lot=False):
        ctx = _setup_gift_floor(
            api,
            [{"sku": "CX", "base_price_cents": 300, "qty_per_set": 13,
              "lots": [130] + ([130] if extra_active_lot else [])}],
            {"sku": "GS", "base_price_cents": 5000})
        return ctx

    def test_blocked_component_lot_excluded_from_pool(self, api):
        """PRD §3.6: "The eligible pool for a component is exactly the lots of
        that component product whose `status` is `ACTIVE`, whose `quality_status`
        is `OK`, whose `expiry_date` is strictly later than the current logical
        clock, and whose `qty_on_hand` is greater than zero."
        PRD §3.6: "If the eligible pool for any component cannot cover that
        component's need, the entire completion is rejected with
        `ERR_INSUFFICIENT_COMPONENT_LOTS` and no lot anywhere is partially
        deducted."

        Design: Difficulty/cross_entity_state_dependency/gift_complete_requires_active_component_lots
        """
        ctx = self._setup(api)
        blocked_lot = ctx["components"][0]["lots"][0]
        create_quality_hold(blocked_lot["id"], defect_type="BLOOM",
                            affected_units=5)
        assert get_lot(blocked_lot["id"])["status"] == "BLOCKED"

        run = _create_gift_run(ctx, 10)
        start_run(run["id"])
        payload = complete_run_payload(10)
        resp = api.complete_run(run["id"], payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COMPONENT_LOTS)

        run = get_run(run["id"])
        assert run["status"] == "IN_PROGRESS"
        assert run["created_lot_id"] is None
        lot = get_lot(blocked_lot["id"])
        assert lot["qty_on_hand"] == 130, "no partial deduction on failure"

    def test_completion_succeeds_from_active_stock_alone(self, api):
        """PRD §3.6: "The pool is walked first-expiry-first-out — ordered by
        `expiry_date` ascending, ties broken by `created_at` ascending — taking
        from each lot the smaller of the remaining need and that lot's
        `qty_on_hand`, and any lot whose `qty_on_hand` reaches zero transitions
        to `DEPLETED`"

        Design: Difficulty/cross_entity_state_dependency/gift_complete_requires_active_component_lots
        """
        ctx = self._setup(api, extra_active_lot=True)
        blocked_lot, active_lot = ctx["components"][0]["lots"]
        create_quality_hold(blocked_lot["id"], defect_type="BLOOM",
                            affected_units=5)

        run = _create_gift_run(ctx, 10)
        start_run(run["id"])
        done = complete_run(run["id"], output_units=10)

        gift_lot = get_lot(done["created_lot_id"])
        assert gift_lot["qty_on_hand"] == 10
        active_lot = get_lot(active_lot["id"])
        assert active_lot["qty_on_hand"] == 0
        assert active_lot["status"] == "DEPLETED"
        blocked_lot = get_lot(blocked_lot["id"])
        assert blocked_lot["qty_on_hand"] == 130, "blocked lots are not in the pool"
        assert blocked_lot["status"] == "BLOCKED"


class TestFefoOrdering:
    def test_earlier_expiry_consumed_first(self, api):
        """PRD §3.6: "The pool is walked first-expiry-first-out — ordered by
        `expiry_date` ascending, ties broken by `created_at` ascending — taking
        from each lot the smaller of the remaining need and that lot's
        `qty_on_hand`, and any lot whose `qty_on_hand` reaches zero transitions
        to `DEPLETED`, each depletion re-triggering its own window's build
        projection."

        Design: Corner/calculations/fefo_allocation_expiry_then_created
        """
        # CX lots: L1 100 units manufactured 2026-09-10 (expiry 2026-12-09),
        # L2 60 units manufactured 2026-09-12 (expiry 2026-12-11).
        ctx = _setup_gift_floor(
            api,
            [{"sku": "CX", "base_price_cents": 300, "qty_per_set": 13,
              "shelf_life_days": 90, "lots": [100, 60],
              "complete_clock": ["2026-09-10T00:00:00Z",
                                 "2026-09-12T00:00:00Z"]}],
            {"sku": "GS", "base_price_cents": 5000})
        lot_1, lot_2 = ctx["components"][0]["lots"]

        run = _create_gift_run(ctx, 10, day="2026-10-01")
        start_run(run["id"])
        set_clock("2026-10-01T00:00:00Z")
        done = complete_run(run["id"], output_units=10)

        lot_1 = get_lot(lot_1["id"])
        assert lot_1["qty_on_hand"] == 0, "earlier-expiring lot consumed first"
        assert lot_1["status"] == "DEPLETED"
        lot_2 = get_lot(lot_2["id"])
        assert lot_2["qty_on_hand"] == 30, "the remaining 30 come from the later lot"
        assert lot_2["status"] == "ACTIVE"

        gift_lot = get_lot(done["created_lot_id"])
        assert gift_lot["qty_on_hand"] == 10
        assert gift_lot["status"] == "ACTIVE"
