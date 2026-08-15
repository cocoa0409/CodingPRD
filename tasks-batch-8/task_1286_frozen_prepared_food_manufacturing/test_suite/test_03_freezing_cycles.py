"""Blast-freezer cells and freezing cycles: dwell math, windows, OCC (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_cycle,
    complete_cycle,
    cook_batch,
    create_approved_recipe,
    create_batch,
    create_freezer_cell,
    create_order,
    get_batch,
    kit_batch,
    pin_clock,
    setup_cooked_batch,
    setup_kitted_batch,
    start_cycle,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]


class TestFreezerLoadBounds:
    def test_freezer_load_exact_capacity_accepted(self, api):
        """PRD §3.4: "a `load_kg` exceeding the cell's `capacity_kg` is rejected
        with `ERR_CAPACITY_EXCEEDED`, and one below its `min_load_kg` is rejected
        with `ERR_BELOW_MIN_LOAD`."
        PRD §3.4: "The base dwell is `load_kg` divided by the cell's
        `pull_down_kg_per_hour`, rounded up to a whole hour." / "The cycle's
        `required_hours` is the greater of four hours and the computed base dwell,
        and its `planned_end` is `planned_start` plus exactly `required_hours`
        hours."

        Design: Difficulty/boundary_precision_check/freezer_load_exact_capacity_boundary
        """
        env = setup_cooked_batch(cooked_mass_kg=2000)
        cell = create_freezer_cell()  # capacity 2000, rate 400, sanitation 30
        # load == capacity is not "exceeding": inclusive upper bound.
        cycle = book_cycle(
            env["batch"]["id"], cell_id=cell["id"],
            load_kg=2000, entry_temp_c=0, planned_start="2026-08-02T00:00:00Z",
        )
        assert cycle["status"] == "RESERVED"
        # ceil(2000/400) = 5; entry_temp 0 is not "above zero" so no thermal factor.
        assert cycle["required_hours"] == 5, (
            f"required_hours must be max(4, ceil(2000/400)) = 5, got {cycle['required_hours']}"
        )
        assert cycle["planned_end"] == "2026-08-02T05:00:00Z", (
            f"planned_end must be planned_start + 5h, got {cycle['planned_end']}"
        )

    def test_freezer_load_one_above_capacity_rejected(self, api):
        """PRD §3.4: "a `load_kg` exceeding the cell's `capacity_kg` is rejected
        with `ERR_CAPACITY_EXCEEDED`, and one below its `min_load_kg` is rejected
        with `ERR_BELOW_MIN_LOAD`."

        Design: Difficulty/boundary_precision_check/freezer_load_exact_capacity_boundary
        """
        env = setup_cooked_batch(cooked_mass_kg=2000)
        cell = create_freezer_cell()  # capacity 2000
        batch = get_batch(env["batch"]["id"])
        resp = api.create_freezing_cycle(
            env["batch"]["id"],
            {
                "cell_id": cell["id"], "load_kg": 2001, "entry_temp_c": 0,
                "planned_start": "2026-08-02T00:00:00Z",
                "expected_batch_version": batch["version"],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED, expected_status=409)

    def test_below_min_load_rejected(self, api):
        """PRD §3.4: "a `load_kg` exceeding the cell's `capacity_kg` is rejected
        with `ERR_CAPACITY_EXCEEDED`, and one below its `min_load_kg` is rejected
        with `ERR_BELOW_MIN_LOAD`."
        PRD §3.4: "The cycle's `required_hours` is the greater of four hours and
        the computed base dwell"

        Design: Corner/validations/below_min_load_rejected
        """
        env = setup_cooked_batch(cooked_mass_kg=300)
        cell = create_freezer_cell()  # min_load 200
        batch = get_batch(env["batch"]["id"])
        resp = api.create_freezing_cycle(
            env["batch"]["id"],
            {
                "cell_id": cell["id"], "load_kg": 199, "entry_temp_c": -5,
                "planned_start": "2026-08-02T00:00:00Z",
                "expected_batch_version": batch["version"],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_LOAD, expected_status=409)

        # 199 is below the minimum; 200 exactly equals it and must be accepted.
        cycle = book_cycle(
            env["batch"]["id"], cell_id=cell["id"],
            load_kg=200, entry_temp_c=-5, planned_start="2026-08-02T00:00:00Z",
        )
        assert cycle["required_hours"] == 4, (
            f"max(4, ceil(200/400)=1) = 4 at the inclusive lower bound, got {cycle['required_hours']}"
        )


class TestFreezerDwellMath:
    def test_freezer_duration_min_dwell_and_temp_factor(self, api):
        """PRD §3.4: "The base dwell is `load_kg` divided by the cell's
        `pull_down_kg_per_hour`, rounded up to a whole hour. When `entry_temp_c`
        is above zero degrees, that base dwell is multiplied by 1.25 and rounded
        up to a whole hour again, capturing the extra thermal load of warm
        product. The cycle's `required_hours` is the greater of four hours and
        the computed base dwell, and its `planned_end` is `planned_start` plus
        exactly `required_hours` hours."

        Design: Corner/calculations/freezer_duration_min_dwell_and_temp_factor
        """
        pin_clock()
        recipe = create_approved_recipe(name="R-Dur")
        cell1 = create_freezer_cell(cell_code="FC-1")
        cell2 = create_freezer_cell(cell_code="FC-2")
        order = create_order(recipe["id"], units_planned=12000)
        b1 = create_batch(order["id"], units_planned=6000)
        b2 = create_batch(order["id"], units_planned=6000)
        kit_batch(b1["id"])
        cook_batch(b1["id"], cooked_mass_kg=800)
        kit_batch(b2["id"])
        cook_batch(b2["id"], cooked_mass_kg=1600)

        # Light, already-frozen load: ceil(800/400) = 2 -> min-dwell floor of 4.
        cy1 = book_cycle(
            b1["id"], cell_id=cell1["id"],
            load_kg=800, entry_temp_c=-5, planned_start="2026-08-02T00:00:00Z",
        )
        assert cy1["required_hours"] == 4, (
            f"min-dwell floor: max(4, 2) = 4, got {cy1['required_hours']}"
        )
        assert cy1["planned_end"] == "2026-08-02T04:00:00Z"

        # Heavier warm load: ceil(1600/400) = 4 -> ceil(4 * 1.25) = 5.
        cy2 = book_cycle(
            b2["id"], cell_id=cell2["id"],
            load_kg=1600, entry_temp_c=5, planned_start="2026-08-02T00:00:00Z",
        )
        assert cy2["required_hours"] == 5, (
            f"warm-load factor: ceil(4 * 1.25) = 5, got {cy2['required_hours']}"
        )
        assert cy2["planned_end"] == "2026-08-02T05:00:00Z"


class TestCellAutoSelect:
    def test_cell_auto_select_best_fit_and_tiebreak(self, api):
        """PRD §3.4: "Candidates are ranked by ascending `capacity_kg`, so the
        tightest fitting cell wins; ties break toward the earlier `created_at`,
        and any remaining tie breaks toward the lexicographically smaller
        `cell_code`."

        Design: Corner/calculations/cell_auto_select_best_fit_and_tiebreak
        """
        env = setup_cooked_batch()
        create_freezer_cell(cell_code="FC-BIG", capacity_kg=3000)
        fit1 = create_freezer_cell(cell_code="FC-F1", capacity_kg=2000)
        create_freezer_cell(cell_code="FC-F2", capacity_kg=2000)
        cycle = book_cycle(env["batch"]["id"], cell_id=None, load_kg=1600)
        assert cycle["cell_id"] == fit1["id"], (
            "best fit is the 2000-kg cells; the created_at tiebreak must pick "
            f"FC-F1 ({fit1['id']}), got {cycle['cell_id']}"
        )

    def test_cell_auto_select_empty_pool_rejected(self, api):
        """PRD §3.4: "The candidate pool is every cell whose bounds admit the
        load — capacity at least `load_kg`, minimum load at most `load_kg` — and
        on which no reserved or in-progress cycle violates the sanitation-buffered
        window rule for the requested start."
        PRD §3.4: "An empty candidate pool rejects the booking with
        `ERR_NO_CELL_AVAILABLE`."

        Design: Corner/calculations/cell_auto_select_empty_pool_rejected
        """
        env = setup_cooked_batch()
        create_freezer_cell(cell_code="FC-1", capacity_kg=2000)
        batch = get_batch(env["batch"]["id"])
        resp = api.create_freezing_cycle(
            env["batch"]["id"],
            {
                "load_kg": 5000, "entry_temp_c": 5,
                "planned_start": "2026-08-02T00:00:00Z",
                "expected_batch_version": batch["version"],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_NO_CELL_AVAILABLE, expected_status=409)


class TestCycleStartGate:
    def test_cycle_start_before_cooked_rejected(self, api):
        """PRD §3.4: "Starting a reserved cycle moves it from `RESERVED` to
        `IN_PROGRESS` and is permitted only while the batch is `COOKED` —
        starting earlier, before the cook step has landed, is rejected with
        `ERR_BATCH_STATE`."

        Design: Difficulty/cross_entity_state_dependency/cycle_start_requires_batch_cooked
        """
        env = setup_kitted_batch()
        cell = create_freezer_cell()
        cycle = book_cycle(env["batch"]["id"], cell_id=cell["id"])
        assert cycle["status"] == "RESERVED"
        # Batch is only KITTED: the cycle start must be rejected.
        resp = api.start_freezing_cycle(cycle["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_BATCH_STATE, expected_status=409)

    def test_cycle_start_after_cook_succeeds(self, api):
        """PRD §3.4: "Starting a reserved cycle moves it from `RESERVED` to
        `IN_PROGRESS` and is permitted only while the batch is `COOKED` —
        starting earlier, before the cook step has landed, is rejected with
        `ERR_BATCH_STATE`."

        Design: Difficulty/cross_entity_state_dependency/cycle_start_requires_batch_cooked
        """
        env = setup_kitted_batch()
        cell = create_freezer_cell()
        cycle = book_cycle(env["batch"]["id"], cell_id=cell["id"])
        cook_batch(env["batch"]["id"], cooked_mass_kg=1550)
        started = validate_success(
            api.start_freezing_cycle(cycle["id"], OPERATOR), expected_status=200
        )
        assert started["status"] == "IN_PROGRESS", (
            f"once the batch is COOKED the cycle starts, got {started['status']}"
        )


class TestCycleCompletion:
    def test_cycle_complete_with_warm_core_marks_failed(self, api):
        """PRD §3.4: "the cycle becomes `VERIFIED` when the final core temperature
        is at or below minus eighteen degrees Celsius and the elapsed time from
        `planned_start` to `actual_end` does not exceed `required_hours` plus a
        two-hour grace; otherwise the cycle becomes `FAILED`."
        PRD §3.4: "a failed cycle leaves the batch in `COOKED` so the planner may
        book a replacement cycle"

        Design: Corner/state_machines/cycle_complete_with_warm_core_marks_failed
        """
        env = setup_cooked_batch()
        cell = create_freezer_cell()
        cycle = book_cycle(env["batch"]["id"], cell_id=cell["id"])
        start_cycle(cycle["id"])

        # Core temperature -10 is above the -18 target: computed outcome is FAILED
        # even though the elapsed time (5h) is within the 5h + 2h grace.
        failed = complete_cycle(
            cycle["id"], actual_end="2026-08-02T05:00:00Z", final_core_temp_c=-10
        )
        assert failed["status"] == "FAILED", (
            f"warm core must mark the cycle FAILED, got {failed['status']}"
        )
        batch = get_batch(env["batch"]["id"])
        assert batch["status"] == "COOKED", (
            f"a failed cycle leaves the batch COOKED, got {batch['status']}"
        )
        # A replacement cycle can be booked on the same cell: a FAILED cycle is
        # neither RESERVED nor IN_PROGRESS, so it does not block the window.
        replacement = book_cycle(
            env["batch"]["id"], cell_id=cell["id"],
            load_kg=1600, entry_temp_c=5, planned_start="2026-08-02T06:00:00Z",
        )
        assert replacement["status"] == "RESERVED"


class TestCycleSupersede:
    def test_new_cycle_supersedes_reserved_cycle(self, api):
        """PRD §3.4: "Booking also supersedes: if a previous cycle of the same
        batch is still `RESERVED`, it automatically becomes `VOIDED` the moment
        the new reservation is created, and this supersede is applied before the
        window-conflict validation runs, so a batch's own superseded cycle never
        conflicts with its replacement."

        Design: Corner/state_machines/new_cycle_supersedes_reserved_cycle
        """
        env = setup_cooked_batch()
        cell = create_freezer_cell()
        first = book_cycle(
            env["batch"]["id"], cell_id=cell["id"],
            load_kg=1600, entry_temp_c=5, planned_start="2026-08-02T00:00:00Z",
        )
        # The replacement overlaps the first cycle's window on the same cell;
        # it is accepted because the supersede runs before the conflict check.
        second = book_cycle(
            env["batch"]["id"], cell_id=cell["id"],
            load_kg=1600, entry_temp_c=5, planned_start="2026-08-02T02:00:00Z",
        )
        assert second["status"] == "RESERVED"
        stale = validate_success(api.get_freezing_cycle(first["id"], PLANNER))
        assert stale["status"] == "VOIDED", (
            f"the superseded cycle must be VOIDED, got {stale['status']}"
        )


class TestCycleVoid:
    def test_void_in_progress_cycle_rejected(self, api):
        """PRD §3.4: "A `ProductionPlanner` may also void a cycle outright, moving
        it from `RESERVED` to `VOIDED`; attempting to void a cycle already
        `IN_PROGRESS` — or any cycle transition from a state where it is
        undefined — is rejected with `ERR_CYCLE_STATE`."

        Design: Corner/validations/void_in_progress_cycle_rejected
        """
        env = setup_cooked_batch()
        cell = create_freezer_cell()
        cycle = book_cycle(env["batch"]["id"], cell_id=cell["id"])
        start_cycle(cycle["id"])
        resp = api.void_freezing_cycle(cycle["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_STATE, expected_status=409)
        after = validate_success(api.get_freezing_cycle(cycle["id"], PLANNER))
        assert after["status"] == "IN_PROGRESS", "rejected void must leave the cycle IN_PROGRESS"


class TestSanitationBuffer:
    def _two_cooked_batches_one_cell(self):
        recipe = create_approved_recipe(name="R-Win1")
        cell = create_freezer_cell(cell_code="FC-1", capacity_kg=2500)
        o1 = create_order(recipe["id"], units_planned=6000)
        b1 = create_batch(o1["id"], units_planned=6000)
        kit_batch(b1["id"])
        cook_batch(b1["id"], cooked_mass_kg=1550)
        o2 = create_order(recipe["id"], units_planned=6000)
        b2 = create_batch(o2["id"], units_planned=6000)
        kit_batch(b2["id"])
        cook_batch(b2["id"], cooked_mass_kg=1550)
        # Cycle on b1: 00:00 + required 5h -> planned_end 05:00; sanitation 30 min.
        cy1 = book_cycle(
            b1["id"], cell_id=cell["id"],
            load_kg=1600, entry_temp_c=5, planned_start="2026-08-02T00:00:00Z",
        )
        assert cy1["planned_end"] == "2026-08-02T05:00:00Z"
        return cell, b2

    def test_sanitation_buffer_conflict_one_minute_early(self, api):
        """PRD §2.10: "On a blast freezer cell, a mandatory sanitation gap follows
        each cycle: the next cycle on that cell may not begin until the cell's
        `sanitation_minutes` have elapsed after the preceding cycle's
        `planned_end`, and this buffered window participates in the conflict check
        against every other reserved or in-progress cycle on the cell."
        PRD §2.4: "10. **Temporal windows.** Freezer-cell windows including the
        sanitation buffer, packaging-line windows including changeover buffers,
        and expiry gates all hold; otherwise `ERR_CELL_WINDOW_CONFLICT`,
        `ERR_LINE_WINDOW_CONFLICT`, or `ERR_LOT_EXPIRED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/freezer_cycle_sanitation_buffer
        """
        pin_clock()
        cell, b2 = self._two_cooked_batches_one_cell()
        batch = get_batch(b2["id"])
        # 05:29 is one minute inside the 30-minute sanitation buffer after 05:00.
        resp = api.create_freezing_cycle(
            b2["id"],
            {
                "cell_id": cell["id"], "load_kg": 1600, "entry_temp_c": 5,
                "planned_start": "2026-08-02T05:29:00Z",
                "expected_batch_version": batch["version"],
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_CELL_WINDOW_CONFLICT, expected_status=409)

    def test_sanitation_buffer_exact_boundary_accepted(self, api):
        """PRD §2.10: "On a blast freezer cell, a mandatory sanitation gap follows
        each cycle: the next cycle on that cell may not begin until the cell's
        `sanitation_minutes` have elapsed after the preceding cycle's
        `planned_end`"
        PRD §3.4: "its `planned_end` is `planned_start` plus exactly
        `required_hours` hours. A new cycle starts life in `RESERVED` status."

        Design: Difficulty/resource_temporal_overlap/freezer_cycle_sanitation_buffer
        """
        pin_clock()
        cell, b2 = self._two_cooked_batches_one_cell()
        # 05:30 is exactly planned_end (05:00) + sanitation_minutes (30): elapsed, accepted.
        cycle = book_cycle(
            b2["id"], cell_id=cell["id"],
            load_kg=1600, entry_temp_c=5, planned_start="2026-08-02T05:30:00Z",
        )
        assert cycle["status"] == "RESERVED"
        assert cycle["planned_end"] == "2026-08-02T10:30:00Z", (
            f"05:30 + 5h = 10:30, got {cycle['planned_end']}"
        )


class TestCycleOcc:
    def test_occ_stale_version_on_cycle_create(self, api):
        """PRD §2.8: "When booking a freezing cycle for a batch, the request must
        carry `expected_batch_version` holding the client's last-observed `version`
        of the target batch. A mismatch with the batch's current `version` is
        likewise rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.4: "The new cycle's `batch_id` ties it to its batch, the batch's
        `version` increments by one, and the server computes the cycle's dwell."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_cycle_create
        """
        pin_clock()
        recipe = create_approved_recipe(name="R-OCC2")
        order = create_order(recipe["id"], units_planned=6000)
        batch = create_batch(order["id"], units_planned=6000)
        stale_version = batch["version"]
        kit_batch(batch["id"])
        cook_batch(batch["id"], cooked_mass_kg=1550)
        cell = create_freezer_cell()

        # Kit and cook each incremented the batch version: the captured one is stale.
        resp = api.create_freezing_cycle(
            batch["id"],
            {
                "cell_id": cell["id"], "load_kg": 1600, "entry_temp_c": 5,
                "planned_start": "2026-08-02T00:00:00Z",
                "expected_batch_version": stale_version,
            },
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        fresh = get_batch(batch["id"])
        assert fresh["version"] > stale_version
        cycle = validate_success(
            api.create_freezing_cycle(
                batch["id"],
                {
                    "cell_id": cell["id"], "load_kg": 1600, "entry_temp_c": 5,
                    "planned_start": "2026-08-02T00:00:00Z",
                    "expected_batch_version": fresh["version"],
                },
                PLANNER,
            ),
            expected_status=201,
        )
        assert cycle["status"] == "RESERVED"
        after = get_batch(batch["id"])
        assert after["version"] == fresh["version"] + 1, (
            "a successful cycle booking increments the batch version by exactly one"
        )
