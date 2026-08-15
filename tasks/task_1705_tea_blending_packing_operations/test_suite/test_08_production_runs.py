"""Production runs: line state gates, half-open window overlap, the
45-minute allergen changeover buffer, format/contract matching, the
outside-window start gate, batch-recall interaction at completion, and
the dual-variant shelf-life calculation.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_contract,
    create_active_recipe,
    create_contract,
    create_flavoring,
    create_packaging_line,
    create_qc_batch,
    create_released_lot,
    create_run,
    create_run_payload,
    create_supplier,
    get_run,
    is_iso8601_timestamp,
    release_batch,
    set_clock,
    setup_released_batch_with_line,
    single_component,
    start_run,
    validate_error,
    validate_success,
)

PP = TEST_USERS["production_planner_headers"]
QA = TEST_USERS["qa_manager_headers"]
BM = TEST_USERS["blend_master_headers"]

W_START = "2026-08-05T08:00:00Z"
W_END = "2026-08-05T10:00:00Z"


def test_line_maintenance_blocks_run_create(api):
    """PRD §3.7: "neither scheduling nor starting is possible on a line in
    `MAINTENANCE` — both attempts fail with `ERR_LINE_NOT_ACTIVE`"
    PRD §3.7: "Taking a line down moves it to `MAINTENANCE` — runs
    already `SCHEDULED` on it keep their bookings but cannot start while
    the line is down — and maintenance exit returns it to `ACTIVE`."

    Design: Corner/state_machines/line_maintenance_blocks_run_create
    """
    ctx = setup_released_batch_with_line(line_name="LP-M")
    line = ctx["line"]
    down = validate_success(api.enter_maintenance(line["id"], PP), 200)
    assert down["status"] == "MAINTENANCE"

    res = api.create_run(
        create_run_payload(line["id"], ctx["batch"]["id"], W_START, W_END,
                           100), PP)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_ACTIVE)

    validate_success(api.exit_maintenance(line["id"], PP), 200)
    run = create_run(line["id"], ctx["batch"]["id"], W_START, W_END, 100)
    assert run["status"] == "SCHEDULED"


def test_run_start_outside_window_rejected(api):
    """PRD §3.7: "Starting a run is a clock-gated act: the run must be
    `SCHEDULED`, the line must be `ACTIVE`, and the logical clock must
    read at or after `planned_start` and strictly before `planned_end` —
    a start outside that half-open window is rejected with
    `ERR_RUN_OUTSIDE_WINDOW`."

    The logical clock reads 07:00, one hour before planned_start 08:00.

    Design: Corner/state_machines/run_start_outside_window_rejected
    """
    ctx = setup_released_batch_with_line(line_name="LP-E")
    run = create_run(ctx["line"]["id"], ctx["batch"]["id"], W_START, W_END,
                     100)
    set_clock("2026-08-05T07:00:00Z")
    res = api.start_run(run["id"], PP)
    validate_error(res, ApiErrorId.ERR_RUN_OUTSIDE_WINDOW)


def test_run_cancel_from_in_progress_rejected(api):
    """PRD §3.7: "Cancelling a run — directly by a `ProductionPlanner`, or
    through the cascades of §2.8 — is possible while it is `SCHEDULED`,
    frees its window, and moves it to `CANCELLED`."

    Cancelling an IN_PROGRESS run is an invalid transition and reports
    the generic state error.

    Design: Corner/state_machines/run_cancel_from_in_progress_rejected
    """
    ctx = setup_released_batch_with_line(line_name="LP-C")
    run = create_run(ctx["line"]["id"], ctx["batch"]["id"], W_START, W_END,
                     100)
    set_clock("2026-08-05T08:30:00Z")
    started = start_run(run["id"])
    assert started["status"] == "IN_PROGRESS"

    res = api.cancel_run(run["id"], PP)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_run(run["id"])["status"] == "IN_PROGRESS"


class TestHalfOpenAdjacency:
    def _line_with_first_run(self):
        ctx = setup_released_batch_with_line(line_name="LP-5")
        run1 = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                          W_START, W_END, 100)
        return ctx, run1

    def test_adjacent_window_accepted(self, api):
        """PRD §3.7: "Windows are half-open — a run occupies its line
        from `planned_start` up to but not including `planned_end` — so
        when the new run's window intersects the window of another
        `SCHEDULED` or `IN_PROGRESS` run on the same line, the newcomer
        is rejected with `ERR_LINE_WINDOW_CONFLICT`, while back-to-back
        bookings that merely touch are allowed."

        A run starting at 10:00 exactly when the previous one ends at
        10:00 merely touches — accepted.

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency
        """
        ctx, _ = self._line_with_first_run()
        run2 = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                          "2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z", 100)
        assert run2["status"] == "SCHEDULED"

    def test_overlapping_window_rejected(self, api):
        """PRD §3.7: "when the new run's window intersects the window of
        another `SCHEDULED` or `IN_PROGRESS` run on the same line, the
        newcomer is rejected with `ERR_LINE_WINDOW_CONFLICT`"

        09:30–10:30 genuinely intersects the booked 08:00–10:00.

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency
        """
        ctx, _ = self._line_with_first_run()
        res = api.create_run(
            create_run_payload(ctx["line"]["id"], ctx["batch"]["id"],
                               "2026-08-05T09:30:00Z",
                               "2026-08-05T10:30:00Z", 100), PP)
        validate_error(res, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)


def test_changeover_buffer_boundary(api):
    """PRD §3.7: "Allergen changeover adds a spacing rule on top: when
    the new run would sit adjacent to another `SCHEDULED` or
    `IN_PROGRESS` run on the same line whose batch carries a different
    `allergen_tags` set, the gap between the two windows must be at
    least 45 minutes, and a tighter gap is rejected with
    `ERR_ALLERGEN_CHANGEOVER_BUFFER`."

    After a TREE_NUT run ending 10:00, an allergen-free run at 10:44
    (gap 44 min) fails; at exactly 10:45 (gap 45 min) it is accepted.

    Design: Corner/validations/changeover_buffer_boundary
    """
    supplier = create_supplier(name="ChCo")
    lot1 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-01", weight_kg=30.0)
    lot2 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-02", weight_kg=30.0)
    flavoring = create_flavoring(name="Nut Essence",
                                 allergen_tags=["TREE_NUT"],
                                 natural_certified=True,
                                 cost_per_kg_cents=2500)
    flavored_recipe = create_active_recipe(
        name="RFlav", pack_format="TEA_BAG",
        components=[single_component("GREEN", "C", 95.0)],
        flavoring_id=flavoring["id"], flavoring_pct=5.0)
    plain_recipe = create_active_recipe(
        name="RPlain", pack_format="TEA_BAG",
        components=[single_component("GREEN", "C", 100.0)])

    batch_f = create_qc_batch(flavored_recipe, 20.0, [(lot1["id"], 19.0)],
                              measured_moisture_pct=5.0)
    release_batch(batch_f["id"])
    batch_u = create_qc_batch(plain_recipe, 20.0, [(lot2["id"], 20.0)],
                              measured_moisture_pct=5.0)
    release_batch(batch_u["id"])

    line = create_packaging_line(name="TB-CH", line_type="TEA_BAG")
    create_run(line["id"], batch_f["id"], W_START, W_END, 100)

    res = api.create_run(
        create_run_payload(line["id"], batch_u["id"],
                           "2026-08-05T10:44:00Z", "2026-08-05T12:00:00Z",
                           100), PP)
    validate_error(res, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_BUFFER)

    ok = validate_success(
        api.create_run(
            create_run_payload(line["id"], batch_u["id"],
                               "2026-08-05T10:45:00Z",
                               "2026-08-05T12:00:00Z", 100), PP), 201)
    assert ok["status"] == "SCHEDULED", "45-minute gap is exactly enough"


def test_line_format_mismatch_rejected(api):
    """PRD §3.7: "Format discipline is strict throughout: the line's
    `line_type` must equal the packed batch's `pack_format`, or
    scheduling is rejected with `ERR_LINE_FORMAT_MISMATCH`"

    A LOOSE_PACK batch cannot be scheduled on a TEA_BAG line.

    Design: Corner/validations/line_format_mismatch_rejected
    """
    ctx = setup_released_batch_with_line(pack_format="LOOSE_PACK",
                                         line_name="LP-unused")
    tea_bag_line = create_packaging_line(name="TB-F", line_type="TEA_BAG")
    res = api.create_run(
        create_run_payload(tea_bag_line["id"], ctx["batch"]["id"],
                           W_START, W_END, 100), PP)
    validate_error(res, ApiErrorId.ERR_LINE_FORMAT_MISMATCH)


def test_invalid_run_window_rejected(api):
    """PRD §3.7: "The window must open before it closes: a
    `planned_start` that is not strictly earlier than `planned_end` is
    rejected with `ERR_INVALID_WINDOW`."

    A zero-length window (start == end) fails before any overlap
    analysis.

    Design: Corner/validations/invalid_run_window_rejected
    """
    ctx = setup_released_batch_with_line(line_name="LP-W")
    res = api.create_run(
        create_run_payload(ctx["line"]["id"], ctx["batch"]["id"],
                           W_START, W_START, 100), PP)
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)


def test_contract_recipe_mismatch_rejected(api):
    """PRD §3.8: "A run booked against a contract must reference an
    `ACTIVE` contract — a `DRAFT`, `CANCELLED`, or `FULFILLED` contract
    is rejected with `ERR_CONTRACT_NOT_ACTIVE` — and the contract's
    `recipe_id` must match the packed batch's recipe, else
    `ERR_CONTRACT_RECIPE_MISMATCH`."

    The contract governs recipe RA; the batch was built on recipe RB.

    Design: Corner/validations/contract_recipe_mismatch_rejected
    """
    ctx = setup_released_batch_with_line(line_name="LP-X")
    other_recipe = create_active_recipe(
        name="RA", pack_format="LOOSE_PACK",
        components=[single_component("GREEN", "C", 100.0)])
    contract = create_active_contract(
        other_recipe["id"], customer_name="Mix Mart",
        minimum_units_per_run=100, contracted_total_units=10000,
        base_unit_price_cents=200)

    payload = create_run_payload(ctx["line"]["id"], ctx["batch"]["id"],
                                 W_START, W_END, 500,
                                 contract_id=contract["id"])
    res = api.create_run(payload, PP)
    validate_error(res, ApiErrorId.ERR_CONTRACT_RECIPE_MISMATCH)


def test_contract_not_active_rejected(api):
    """PRD §3.8: "A run booked against a contract must reference an
    `ACTIVE` contract — a `DRAFT`, `CANCELLED`, or `FULFILLED` contract
    is rejected with `ERR_CONTRACT_NOT_ACTIVE`"

    The contract is left in DRAFT.

    Design: Corner/validations/contract_not_active_rejected
    """
    ctx = setup_released_batch_with_line(line_name="LP-D")
    contract = create_contract(ctx["recipe"]["id"], customer_name="Draft Mart",
                               minimum_units_per_run=100,
                               contracted_total_units=10000,
                               base_unit_price_cents=200)
    assert contract["status"] == "DRAFT"

    payload = create_run_payload(ctx["line"]["id"], ctx["batch"]["id"],
                                 W_START, W_END, 500,
                                 contract_id=contract["id"])
    res = api.create_run(payload, PP)
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


class TestRunCompleteRequiresBatchReleased:
    def test_complete_after_batch_recall_rejected(self, api):
        """PRD §3.7: "Completion reports the `actual_units` produced —
        at least one, and at least the contract's per-run minimum when
        the run is contracted, else `ERR_PRIVATE_LABEL_MINIMUM_UNMET` —
        and requires the packed batch to still be `RELEASED`, else
        `ERR_BATCH_NOT_RELEASABLE`."

        The batch is recalled while the run is IN_PROGRESS; the run is
        not cascade-cancelled (it is past SCHEDULED) and then fails at
        completion.

        Design: Difficulty/cross_entity_state_dependency/run_complete_requires_batch_released
        """
        ctx = setup_released_batch_with_line(line_name="LP-4")
        run = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                         W_START, W_END, 500)
        set_clock("2026-08-05T08:30:00Z")
        start_run(run["id"])

        recalled = validate_success(
            api.recall_batch(ctx["batch"]["id"], QA), 200)
        assert recalled["status"] == "RECALLED"

        res = api.complete_run(run["id"], {"actual_units": 500}, PP)
        validate_error(res, ApiErrorId.ERR_BATCH_NOT_RELEASABLE)
        run_after = validate_success(api.get_run(run["id"], PP), 200)
        assert run_after["status"] == "IN_PROGRESS", (
            "only SCHEDULED runs are cascade-cancelled")

    def test_recall_cancels_scheduled_run_but_not_in_progress(self, api):
        """PRD §3.5: "a `RELEASED` batch moves to `RECALLED`, every
        charge recorded in its `cert_charges` is returned to the
        corresponding grant and the `cert_charges` ledger is cleared,
        and every still-`SCHEDULED` run booked for the batch is
        cancelled — runs already `IN_PROGRESS` are left untouched."

        Design: Difficulty/cross_entity_state_dependency/run_complete_requires_batch_released
        """
        ctx = setup_released_batch_with_line(line_name="LP-4b")
        run_live = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                              W_START, W_END, 500)
        run_queued = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                                "2026-08-05T12:00:00Z",
                                "2026-08-05T14:00:00Z", 500)
        set_clock("2026-08-05T08:30:00Z")
        start_run(run_live["id"])

        validate_success(api.recall_batch(ctx["batch"]["id"], QA), 200)

        live_after = validate_success(api.get_run(run_live["id"], PP), 200)
        queued_after = validate_success(api.get_run(run_queued["id"], PP), 200)
        assert live_after["status"] == "IN_PROGRESS", (
            "IN_PROGRESS runs are left untouched")
        assert queued_after["status"] == "CANCELLED", (
            "SCHEDULED runs are cancelled")

        res = api.complete_run(run_live["id"], {"actual_units": 500}, PP)
        validate_error(res, ApiErrorId.ERR_BATCH_NOT_RELEASABLE)


class TestShelfLifeVariants:
    def _scenario(self):
        """GREEN lot harvested 2025-06-01 at intake moisture 5.0, batch
        blended at measured 6.25, LOOSE_PACK, RELEASED; LOOSE_PACK line."""
        return setup_released_batch_with_line(
            leaf_type="GREEN", harvest_date="2025-06-01", lot_weight_kg=50.0,
            lot_cost_per_kg_cents=800, lot_moisture_pct=5.0,
            min_grade="C", target_weight_kg=20.0, allocated_kg=20.0,
            measured_moisture_pct=6.25, pack_format="LOOSE_PACK",
            line_name="LP-1")

    def test_provisional_shelf_life_at_creation(self, api):
        """PRD §3.7: "The excess is the amount by which the batch's
        `measured_moisture_pct` exceeds the 5.0 percent target, or zero
        when it does not exceed it."
        PRD §3.7: "The penalty takes that excess, multiplies it by ten,
        rounds the product up to the next whole number, and then
        multiplies by three days."
        PRD §3.7: "The `provisional_shelf_life_days` is the pack format's
        base shelf life — 540 days for `TEA_BAG`, 365 days for
        `LOOSE_PACK` — minus the penalty."

        excess 1.25 -> ceil(12.5) = 13 -> penalty 39; LOOSE_PACK base
        365 - 39 = 326.

        Design: Difficulty/dual_variant_calc/shelf_life_provisional_vs_final
        """
        ctx = self._scenario()
        run = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                         "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z", 500)
        assert run["status"] == "SCHEDULED"
        assert run["provisional_shelf_life_days"] == 326

    def test_final_shelf_life_at_completion(self, api):
        """PRD §3.7: "For every lot with an `ACTIVE` allocation in the
        packed batch, the system counts the whole UTC calendar days
        between the lot's `harvest_date` and the completion date and
        subtracts that count from the 730-day harvest ceiling; the
        smallest such remainder across those lots becomes a floor, and
        the `final_shelf_life_days` is the smaller of the provisional
        estimate and that floor — strictly below the estimate whenever a
        constituent lot is old enough to bind the ceiling."
        PRD §3.7: "A successful start stamps `started_at` from the
        logical clock and moves the run to `IN_PROGRESS`."

        Completing on 2026-08-10 against a 2025-06-01 harvest gives a
        435-day age, a 730 - 435 = 295 floor, and
        min(326, 295) = 295.

        Design: Difficulty/dual_variant_calc/shelf_life_provisional_vs_final
        """
        ctx = self._scenario()
        run = create_run(ctx["line"]["id"], ctx["batch"]["id"],
                         "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z", 500)
        set_clock("2026-08-10T08:30:00Z")
        started = start_run(run["id"])
        assert started["status"] == "IN_PROGRESS"
        assert is_iso8601_timestamp(started["started_at"])
        assert started["started_at"].startswith("2026-08-10T08:30:00")

        completed = validate_success(
            api.complete_run(run["id"], {"actual_units": 500}, PP), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["final_shelf_life_days"] == 295
        assert completed["final_shelf_life_days"] != completed[
            "provisional_shelf_life_days"], (
            "the final variant joins the harvest-age ceiling the "
            "provisional ignores")
