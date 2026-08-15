"""Run scheduling gates: optimistic concurrency on the window, half-open line
occupancy, temporal/fiscal guards, rework source-lot eligibility, and the
run-start gates (line availability, allergen clearance, mold shape)."""
from test_helpers import (
    OPERATOR,
    PLANNER,
    ApiErrorId,
    create_production_run_payload,
    create_quality_hold,
    create_run,
    get_line,
    get_lot,
    get_run,
    get_window,
    hold_run,
    open_changeover,
    prepare_line,
    release_changeover,
    run_changeover_cycle,
    set_clock,
    setup_active_lot,
    setup_runnable_plant,
    start_run,
    swab_changeover,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestWindowOptimisticConcurrency:
    def test_run_create_with_stale_window_version_rejected(self, api):
        """PRD §2.8: "Scheduling a production run requires the non-optional field
        `expected_window_version`, carrying the `version` of the target seasonal
        window as the client last observed it. If the window's current `version`
        no longer matches — because another writer has advanced it since the
        client last read the window — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/complexity_layers/run_create_stale_window_version_rejected
        """
        plant = setup_runnable_plant(season_code="HOLIDAY", target_units=10000)
        # Simulate a client who last read the window before publication: the
        # publish transition has already advanced the window's version.
        stale_version = plant["window"]["version"] - 1
        payload = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], stale_version, planned_units=100)
        resp = api.create_production_run(payload, PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        runs, meta = validate_paginated(api.list_production_runs(PLANNER))
        assert runs == [], "the stale create must not persist a run"
        assert meta["total_count"] == 0


class TestLineScheduleHalfOpen:
    def _plant_with_first_run(self, api):
        plant = setup_runnable_plant()
        run_a = create_run(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], planned_units=100,
            scheduled_start="2026-09-05T08:00:00Z",
            scheduled_end="2026-09-05T12:00:00Z")
        return plant, run_a

    def test_adjacent_after_allowed_overlap_rejected(self, api):
        """PRD §3.5: "a run occupies its line from `scheduled_start` up to but not
        including `scheduled_end`, and the new run is rejected with
        `ERR_LINE_SCHEDULE_CONFLICT` when that span intersects the occupied span
        of any other run on the same line in `PLANNED`, `IN_PROGRESS`, or
        `ON_HOLD` — because the intervals are half-open, two runs that merely
        touch at an endpoint are allowed."

        Design: Difficulty/resource_temporal_overlap/line_runs_half_open_adjacency
        """
        plant, _run_a = self._plant_with_first_run(api)

        adjacent = create_run(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], planned_units=100,
            scheduled_start="2026-09-05T12:00:00Z",
            scheduled_end="2026-09-05T16:00:00Z")
        assert adjacent["status"] == "PLANNED", "touching at an endpoint is allowed"

        overlap = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], get_window(plant["window"]["id"])["version"],
            planned_units=100, scheduled_start="2026-09-05T11:00:00Z",
            scheduled_end="2026-09-05T13:00:00Z")
        validate_error(api.create_production_run(overlap, PLANNER),
                       ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)

        runs, meta = validate_paginated(
            api.list_production_runs(PLANNER, params={"line_id": plant["line"]["id"]}))
        assert len(runs) == 2

    def test_adjacent_before_allowed_interior_rejected(self, api):
        """PRD §3.5: "a run occupies its line from `scheduled_start` up to but not
        including `scheduled_end`" — so a run whose `scheduled_end` equals the
        existing run's `scheduled_start` shares no instant with it, while a run
        strictly inside the occupied span intersects it and "is rejected with
        `ERR_LINE_SCHEDULE_CONFLICT`".

        Design: Difficulty/resource_temporal_overlap/line_runs_half_open_adjacency
        """
        plant, _run_a = self._plant_with_first_run(api)

        before = create_run(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], planned_units=100,
            scheduled_start="2026-09-05T04:00:00Z",
            scheduled_end="2026-09-05T08:00:00Z")
        assert before["status"] == "PLANNED"

        interior = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], get_window(plant["window"]["id"])["version"],
            planned_units=100, scheduled_start="2026-09-05T09:00:00Z",
            scheduled_end="2026-09-05T11:00:00Z")
        validate_error(api.create_production_run(interior, PLANNER),
                       ApiErrorId.ERR_LINE_SCHEDULE_CONFLICT)


class TestTemporalVsFiscalPriority:
    def test_outside_window_beats_packaging_shortage(self, api):
        """PRD §2.7: "7. **Temporal window rules** — schedule containment within
        the build window, close timing, purchase-order due dates, and rework lot
        expiry." precedes "8. **Capacity and quota** — packaging availability,
        rework quantity against source-lot stock, and gift-component pool
        sufficiency.", and "An earlier failure masks every later category".
        PRD §3.5: "The schedule must sit inside the build corridor:
        `scheduled_start` no earlier than the window's `build_start` and
        `scheduled_end` no later than its `build_end`, otherwise
        `ERR_OUTSIDE_PRODUCTION_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_run_create_conflict
        """
        plant = setup_runnable_plant(product_type="SEASONAL", sku_code="TRUFFLE-24",
                                     base_price_cents=1000, shelf_life_days=180,
                                     qty_on_hand=100, season_code="HOLIDAY",
                                     target_units=10000)
        payload = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], plant["window"]["version"], planned_units=5000,
            scheduled_start="2026-10-20T08:00:00Z",
            scheduled_end="2026-10-21T16:00:00Z")
        resp = api.create_production_run(payload, PLANNER)
        error = validate_error(resp, ApiErrorId.ERR_OUTSIDE_PRODUCTION_WINDOW)
        assert error["error_id"] != ApiErrorId.ERR_PACKAGING_SHORTAGE

        runs, _ = validate_paginated(api.list_production_runs(PLANNER))
        assert runs == []

    def test_packaging_shortage_fires_when_temporal_passes(self, api):
        """PRD §3.5: "if that requirement exceeds the component's `qty_available`,
        the create is rejected with `ERR_PACKAGING_SHORTAGE`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_run_create_conflict
        """
        plant = setup_runnable_plant(product_type="SEASONAL", sku_code="TRUFFLE-24",
                                     base_price_cents=1000, shelf_life_days=180,
                                     qty_on_hand=100, season_code="HOLIDAY",
                                     target_units=10000)
        payload = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], plant["window"]["version"], planned_units=5000,
            scheduled_start="2026-09-05T08:00:00Z",
            scheduled_end="2026-09-05T16:00:00Z")
        validate_error(api.create_production_run(payload, PLANNER),
                       ApiErrorId.ERR_PACKAGING_SHORTAGE)


class TestRunStartRequiresAvailableLine:
    def test_start_during_changeover_rejected(self, api):
        """PRD §3.6: "The line must be `AVAILABLE` — not mid-changeover — or the
        start fails with `ERR_LINE_NOT_AVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_available_line
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        open_changeover(plant["line"]["id"], "SHAPE_ONLY")

        resp = api.start_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_AVAILABLE)
        assert get_run(run["id"])["status"] == "PLANNED"
        assert get_line(plant["line"]["id"])["status"] == "CHANGEOVER"

    def test_start_succeeds_after_changeover_released(self, api):
        """PRD §3.3: "The line returns to `AVAILABLE` with its own `version`
        incremented"
        PRD §3.6: "Starting a run moves it from `PLANNED` to `IN_PROGRESS`"

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_available_line
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        open_changeover(plant["line"]["id"], "FULL")
        validate_error(api.start_run(run["id"], OPERATOR),
                       ApiErrorId.ERR_LINE_NOT_AVAILABLE)

        # The changeover only blocks while it is open; releasing restores the line.
        # The list is sorted by created_at ascending (PRD §2.3), so the setup
        # changeover (already RELEASED) precedes the one just opened; target
        # the changeover still awaiting a swab.
        changeovers, _ = validate_paginated(
            api.list_line_changeovers(plant["line"]["id"], PLANNER))
        pending = [c for c in changeovers if c["status"] == "PENDING_SWAB"]
        assert len(pending) == 1
        swab_changeover(pending[0]["id"])
        release_changeover(pending[0]["id"])

        started = validate_success(api.start_run(run["id"], OPERATOR))
        assert started["status"] == "IN_PROGRESS"


class TestStateVsSafetyPriority:
    def _plant_with_milk_recipe(self, api):
        return setup_runnable_plant(
            product_type="SEASONAL", sku_code="TRUFFLE-24", base_price_cents=1000,
            shelf_life_days=180, allergens=["MILK"], shape_code="SHELL-HEART",
            cleared_allergens=["MILK"], season_code="HOLIDAY", target_units=10000)

    def test_state_error_masks_allergen_error(self, api):
        """PRD §2.7: "4. **State preconditions** — the target resources must be in
        the states the transition requires" precedes "5. **Allergen and sanitation
        safety**", and "An earlier failure masks every later category".
        PRD §3.6: "Starting a run moves it from `PLANNED` to `IN_PROGRESS`, but
        only through three gates beyond the state check itself (a start attempted
        from any other run state is `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_run_start_conflict
        """
        plant = self._plant_with_milk_recipe(api)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        start_run(run["id"])
        hold_run(run["id"])

        # A mold-swap-free changeover resets the line's clearance to empty while
        # the MILK recipe run sits ON_HOLD.
        run_changeover_cycle(plant["line"]["id"], "SHAPE_ONLY")

        resp = api.start_run(run["id"], OPERATOR)
        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert error["error_id"] != ApiErrorId.ERR_ALLERGEN_WASH_REQUIRED
        assert get_run(run["id"])["status"] == "ON_HOLD"

    def test_allergen_error_fires_when_state_passes(self, api):
        """PRD §3.6: "Every allergen in the recipe's `allergens` must be present
        in the line's `cleared_allergens`, per the cross-contact rule of §2.10,
        otherwise `ERR_ALLERGEN_WASH_REQUIRED` tells the operator a validated wash
        stands between this line and this recipe."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_run_start_conflict
        """
        plant = self._plant_with_milk_recipe(api)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)

        # Clearance reset while the run is still PLANNED: the state check passes,
        # so the allergen gate now reports.
        run_changeover_cycle(plant["line"]["id"], "SHAPE_ONLY")

        resp = api.start_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_WASH_REQUIRED)
        assert get_run(run["id"])["status"] == "PLANNED"


class TestRunStartMoldGate:
    def test_shape_mismatch_rejected(self, api):
        """PRD §3.6: "the mold referenced by the line's `current_mold_id` must
        carry a `shape_code` equal to the recipe's `shape_code`, with any
        mismatch — including a line with no mold installed at all — rejected as
        `ERR_MOLD_SHAPE_MISMATCH`."

        Design: Corner/validations/run_start_mold_shape_mismatch_rejected
        """
        # Recipe needs BAR; the line carries a SHELL-HEART mold (allergen-free
        # recipe on an allergen-free line, so only the mold gate can fail).
        plant = setup_runnable_plant(sku_code="BAR-01", shape_code="BAR")
        line, _mold = prepare_line(shape_code="SHELL-HEART", name="LINE-9")
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], line["id"], planned_units=100)
        resp = api.start_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_MOLD_SHAPE_MISMATCH)
        assert get_run(run["id"])["status"] == "PLANNED"


class TestRunStartAllergenGate:
    def test_allergen_wash_required(self, api):
        """PRD §3.6: "Every allergen in the recipe's `allergens` must be present
        in the line's `cleared_allergens`, per the cross-contact rule of §2.10,
        otherwise `ERR_ALLERGEN_WASH_REQUIRED` tells the operator a validated wash
        stands between this line and this recipe."
        PRD §2.10: "a line cleared for nothing can only run allergen-free recipes."

        Design: Corner/errors/run_start_allergen_wash_required_rejected
        """
        plant = setup_runnable_plant(
            product_type="SEASONAL", sku_code="TRUFFLE-24", base_price_cents=1000,
            shelf_life_days=180, allergens=["MILK"], shape_code="SHELL-HEART",
            cleared_allergens=(), season_code="HOLIDAY", target_units=10000)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=100)
        resp = api.start_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_WASH_REQUIRED)
        assert get_run(run["id"])["status"] == "PLANNED"


class TestReworkSourceEligibility:
    def test_expired_source_lot_rejected(self, api):
        """PRD §3.5: "The source lot must not be expired — the logical clock must
        be strictly earlier than the lot's `expiry_date`, otherwise
        `ERR_LOT_EXPIRED`."
        PRD §3.6: "`expiry_date` is `mfg_date` plus the product's
        `shelf_life_days`"

        Design: Corner/validations/rework_expired_lot_rejected
        """
        plant = setup_active_lot(output_units=500, shelf_life_days=30,
                                 standard_yield_pct=0.90,
                                 complete_clock="2026-09-05T00:00:00Z")
        lot = plant["lot"]
        # mfg 2026-09-05 + 30 days -> expiry 2026-10-05; clock is now past it.
        set_clock("2026-10-06T00:00:00Z")

        payload = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], get_window(plant["window"]["id"])["version"],
            run_type="REWORK", planned_units=400,
            scheduled_start="2026-10-06T08:00:00Z",
            scheduled_end="2026-10-06T16:00:00Z",
            source_lot_id=lot["id"], rework_qty=500)
        validate_error(api.create_production_run(payload, PLANNER),
                       ApiErrorId.ERR_LOT_EXPIRED)

        lot = get_lot(lot["id"])
        assert lot["qty_on_hand"] == 500
        assert lot["qty_reserved_rework"] == 0
        assert lot["status"] == "ACTIVE"

    def test_rework_qty_exceeding_source_rejected(self, api):
        """PRD §3.5: "And `rework_qty` must not exceed the source lot's
        `qty_on_hand`, or the create fails with `ERR_REWORK_QTY_EXCEEDS_LOT`."

        Design: Corner/validations/rework_qty_exceeds_lot_rejected
        """
        plant = setup_active_lot(output_units=1000, standard_yield_pct=0.90)
        payload = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], get_window(plant["window"]["id"])["version"],
            run_type="REWORK", planned_units=900,
            scheduled_start="2026-09-07T08:00:00Z",
            scheduled_end="2026-09-07T16:00:00Z",
            source_lot_id=plant["lot"]["id"], rework_qty=1001)
        validate_error(api.create_production_run(payload, PLANNER),
                       ApiErrorId.ERR_REWORK_QTY_EXCEEDS_LOT)

        lot = get_lot(plant["lot"]["id"])
        assert lot["qty_on_hand"] == 1000
        assert lot["qty_reserved_rework"] == 0

    def test_blocked_lot_without_rework_pending_rejected(self, api):
        """PRD §3.5: "The source lot must be reworkable: `ACTIVE`, or `BLOCKED`
        with a hold sitting in `REWORK_PENDING`; a `DEPLETED` or `SCRAPPED` lot,
        or a blocked lot without such a hold, is rejected with
        `ERR_LOT_NOT_REWORKABLE`."

        Design: Corner/validations/rework_blocked_lot_without_pending_rejected
        """
        plant = setup_active_lot(output_units=1000, standard_yield_pct=0.90)
        create_quality_hold(plant["lot"]["id"], defect_type="BLOOM",
                            affected_units=10)
        assert get_lot(plant["lot"]["id"])["status"] == "BLOCKED"

        payload = create_production_run_payload(
            plant["window"]["id"], plant["product"]["id"], plant["recipe"]["id"],
            plant["line"]["id"], get_window(plant["window"]["id"])["version"],
            run_type="REWORK", planned_units=900,
            scheduled_start="2026-09-07T08:00:00Z",
            scheduled_end="2026-09-07T16:00:00Z",
            source_lot_id=plant["lot"]["id"], rework_qty=1000)
        validate_error(api.create_production_run(payload, PLANNER),
                       ApiErrorId.ERR_LOT_NOT_REWORKABLE)
