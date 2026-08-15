"""Run scheduling: optimistic concurrency, buffered-overlap interval
semantics, abort terminal lockout, existence precedence, and the
state-vs-safety validation ordering."""
from test_helpers import (
    ApiErrorId,
    abort_run,
    create_approved_recipe,
    create_run_payload,
    drive_run_to_completed,
    get_die,
    get_line,
    get_run,
    reschedule_run_payload,
    schedule_run,
    set_clock,
    setup_run_world,
    setup_scheduled_run,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OP = TEST_USERS["production_operator_headers"]


def test_occ_run_create_stale_line_version(api):
    """PRD: "Creating a production run requires `expected_line_version`,
    carrying the client's last observed `version` of the target
    `ProductionLine`; if the line's version has advanced since the client read
    it — because another run was scheduled on the line, a cleaning action ran,
    or a posture change bumped it — the create is rejected with
    `ERR_STALE_LINE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_run_create_stale_line_version
    """
    world = setup_run_world(contract_code="C-OCC", with_die=False)
    line = world["line"]
    assert line["version"] == 1

    run1 = schedule_run(world["recipe"]["id"], line["id"], world["lot"]["id"], 100.0)
    assert run1["id"]

    stale = api.create_production_run(
        create_run_payload(world["recipe"]["id"], line["id"], world["lot"]["id"],
                           expected_line_version=1, planned_input_kg=100.0,
                           scheduled_start="2026-08-12T00:00:00Z",
                           scheduled_end="2026-08-13T00:00:00Z"),
        OP,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_LINE_VERSION)

    line_after = get_line(line["id"])
    assert line_after["version"] == 2, "only the accepted run bumped the line"
    runs = validate_success(api.list_production_runs(OP, params={"limit": 100}))
    assert len(runs) == 1, "the stale create produced no run"


def test_occ_reschedule_recomputes_changeover_and_rejects_stale(api):
    """PRD: "Rescheduling a production run requires `expected_run_version`,
    carrying the client's last observed `version` of the run; if any advance,
    abort, quality action, or prior reschedule has moved the version, the
    reschedule is rejected with `ERR_STALE_RUN_VERSION` (HTTP 412)."
    PRD: "the reschedule recomputes the changeover and the overlap check and
    increments the run's `version`"
    PRD: "With no predecessor the base is 45 minutes; when the predecessor and
    new run share a shape family the base is 30"

    Design: Corner/cross_cutting_layers/occ_reschedule_recomputes_changeover_and_rejects_stale
    """
    world = setup_run_world(contract_code="C-OCR", with_die=False)
    line = world["line"]

    run1 = schedule_run(world["recipe"]["id"], line["id"], world["lot"]["id"], 100.0,
                        scheduled_start="2026-08-10T00:00:00Z",
                        scheduled_end="2026-08-11T00:00:00Z")
    assert run1["changeover_minutes"] == 45, "no predecessor at creation"
    run1_version = run1["version"]

    run2 = schedule_run(world["recipe"]["id"], line["id"], world["lot"]["id"], 100.0,
                        scheduled_start="2026-08-13T00:00:00Z",
                        scheduled_end="2026-08-14T00:00:00Z")
    assert run2["changeover_minutes"] == 30, "predecessor run1, same family"

    moved = validate_success(api.reschedule_run(
        run1["id"],
        reschedule_run_payload(run1_version,
                               scheduled_start="2026-08-15T00:00:00Z",
                               scheduled_end="2026-08-16T00:00:00Z"),
        OP,
    ))
    assert moved["changeover_minutes"] == 30, "moved past run2: new predecessor run2"
    assert moved["version"] == run1_version + 1

    stale = api.reschedule_run(
        run1["id"],
        reschedule_run_payload(run1_version,
                               scheduled_start="2026-08-17T00:00:00Z"),
        OP,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_RUN_VERSION)


def test_run_abort_terminal_lockout(api):
    """PRD: "Abortion is available from any non-terminal state and always moves
    the run to `ABORTED` with a version bump"
    PRD: "then transition legality on the target resource as
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/run_abort_terminal_lockout
    """
    sc = setup_scheduled_run(contract_code="C-ABT", planned_input_kg=100.0,
                             with_die=False)
    aborted = abort_run(sc["run"]["id"])
    assert aborted["production_status"] == "ABORTED"

    resp = api.abort_run(sc["run"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_existence_checked_before_state(api):
    """PRD: "then existence of path- and body-referenced resources (the
    entity-specific 404 codes); then payload shape"
    PRD: "A missing resource surfaces as the entity-specific 404"

    Design: Corner/validations/existence_checked_before_state
    """
    world = setup_run_world(contract_code="C-NF", with_die=False)
    resp = api.reschedule_run(
        "55555555-5555-4555-8555-555555555555",
        reschedule_run_payload(world["line"]["version"],
                               scheduled_start="2026-09-01T00:00:00Z"),
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_FOUND)


class TestLineBufferedIntervalOverlap:
    def _setup(self):
        world = setup_run_world(contract_code="C-OVL", with_die=False)
        run1 = schedule_run(world["recipe"]["id"], world["line"]["id"],
                            world["lot"]["id"], 100.0,
                            scheduled_start="2026-08-10T00:00:00Z",
                            scheduled_end="2026-08-11T00:00:00Z")
        return world, run1

    def test_run_starting_at_predecessor_end_collides(self, api):
        """PRD: "The buffered occupancy of the new run is the half-open
        interval from `scheduled_start` minus `changeover_minutes` up to
        `scheduled_end`; it must not intersect the corresponding buffered
        interval of any other non-`ABORTED` run on the same line"
        PRD: "A collision is rejected with `ERR_LINE_WINDOW_OVERLAP`."
        PRD: "With no predecessor the base is 45 minutes"

        Design: Difficulty/resource_temporal_overlap/line_buffered_interval_overlap_half_open
        """
        world, run1 = self._setup()
        assert run1["changeover_minutes"] == 45, "NONE predecessor base"

        line = get_line(world["line"]["id"])
        resp = api.create_production_run(
            create_run_payload(world["recipe"]["id"], world["line"]["id"],
                               world["lot"]["id"], line["version"],
                               planned_input_kg=100.0,
                               scheduled_start="2026-08-11T00:00:00Z",
                               scheduled_end="2026-08-12T00:00:00Z"),
            OP,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_OVERLAP)

    def test_half_open_adjacency_permitted(self, api):
        """PRD: "Touching endpoints do not intersect — adjacency is permitted."
        PRD: "when the predecessor and new run share a shape family the base
        is 30"

        Design: Difficulty/resource_temporal_overlap/line_buffered_interval_overlap_half_open
        """
        world, _ = self._setup()
        line = get_line(world["line"]["id"])
        resp = api.create_production_run(
            create_run_payload(world["recipe"]["id"], world["line"]["id"],
                               world["lot"]["id"], line["version"],
                               planned_input_kg=100.0,
                               scheduled_start="2026-08-11T00:30:00Z",
                               scheduled_end="2026-08-12T00:30:00Z"),
            OP,
        )
        run3 = validate_success(resp, 201)
        assert run3["changeover_minutes"] == 30, (
            "LONG_CUT -> LONG_CUT same-family base; wear 0; allergen 0"
        )


class TestStateTrumpsSafetyOnAbortedGfRun:
    def _setup_aborted_gf_run(self):
        world = setup_run_world(
            contract_code="C-PV1",
            recipe_overrides={"recipe_name": "GF Penne PV1", "gluten_free": True,
                              "shape_family": "SHORT_CUT"},
            with_die=False,
        )
        run = schedule_run(world["recipe"]["id"], world["line"]["id"],
                           world["lot"]["id"], 100.0)
        abort_run(run["id"])
        return world, run

    def test_aborted_gf_run_advance_reports_invalid_state(self, api):
        """PRD: "the server evaluates them in a fixed priority order so that
        the reported error is deterministic"
        PRD: "then transition legality on the target resource as
        `ERR_INVALID_STATE`; then the optimistic-concurrency checks"
        PRD: "then food-safety and gluten-segregation hard caps
        (`ERR_GF_SEGREGATION_VIOLATION`, `ERR_MOISTURE_CAP_EXCEEDED`,
        `ERR_CRACK_RISK`, `ERR_LOT_GRADE_BELOW_CONTRACT`)"

        Design: Difficulty/priority_pair_validation_conflict/state_trumps_safety_on_aborted_gf_run_advance
        """
        _, run = self._setup_aborted_gf_run()
        # The line is GLUTEN_EXPOSED, so the same call would also violate GF
        # segregation; the state error (earlier priority) must win.
        resp = api.advance_run(run["id"], {}, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = get_run(run["id"])
        assert after["production_status"] == "ABORTED"

    def test_gf_safety_fires_in_isolation_when_state_is_legal(self, api):
        """PRD: "If the run is gluten-free, the line's `gluten_posture` must be
        `GF_VALIDATED` (`ERR_GF_SEGREGATION_VIOLATION`)."
        PRD: "then transition legality on the target resource as
        `ERR_INVALID_STATE`; then the optimistic-concurrency checks"

        Design: Difficulty/priority_pair_validation_conflict/state_trumps_safety_on_aborted_gf_run_advance
        """
        world = setup_run_world(
            contract_code="C-PV1B",
            recipe_overrides={"recipe_name": "GF Penne PV1B", "gluten_free": True,
                              "shape_family": "SHORT_CUT"},
            with_die=False,
        )
        run = schedule_run(world["recipe"]["id"], world["line"]["id"],
                           world["lot"]["id"], 100.0)
        # Run is SCHEDULED (legal from-state); only the GF safety gate fails.
        set_clock("2026-08-10T00:00:00Z")
        resp = api.advance_run(run["id"], {}, OP)
        validate_error(resp, ApiErrorId.ERR_GF_SEGREGATION_VIOLATION)


class TestChangeoverMatrixWearComposition:
    def _setup_worn_specialty_line(self):
        """Run1 (SPECIALTY, 1700 kg) COMPLETED on a line whose SPECIALTY die is
        rated 2000 kg, leaving wear ratio 0.85; plus an approved LONG_CUT recipe."""
        world = setup_run_world(
            contract_code="C-CHO", lot_weight_kg=3000.0,
            recipe_overrides={"recipe_name": "Farfalle R1", "shape_family": "SPECIALTY"},
            die_code="D-SPE", die_rated_kg=2000.0, die_shape_family="SPECIALTY",
        )
        r2 = create_approved_recipe(recipe_name="Spaghetti R2", shape_family="LONG_CUT")
        run1 = schedule_run(world["recipe"]["id"], world["line"]["id"],
                            world["lot"]["id"], 1700.0)
        drive_run_to_completed(run1, 1600.0, finish_clock="2026-08-11T00:00:00Z")
        return world, r2, run1

    def test_specialty_to_long_with_tier3_wear_composes_115(self, api):
        """PRD: "With no predecessor the base is 45 minutes; when the
        predecessor and new run share a shape family the base is 30; `LONG_CUT`
        to `SHORT_CUT` or back is 60; anything into `SPECIALTY` is 90; and
        `SPECIALTY` out to a different family is 75."
        PRD: "A wear adder reads the die currently mounted on the line: if the
        ratio of `extruded_kg` to `rated_capacity_kg` is below 0.50 the adder
        is zero; from 0.50 up to but not including 0.80 it is 15 minutes; at
        0.80 or above it is 40 minutes; with no die mounted the adder is zero."
        PRD: "An allergen adder of 20 minutes applies exactly when a
        predecessor exists, the predecessor was gluten-free, and the new run is
        not."

        Design: Difficulty/combinatorial_formula/changeover_matrix_wear_tier_allergen_composition
        """
        world, r2, run1 = self._setup_worn_specialty_line()
        die = get_die(world["die"]["id"])
        assert die["extruded_kg"] == 1700.0, "wear ratio 0.85"
        assert get_run(run1["id"])["production_status"] == "COMPLETED"

        run2 = schedule_run(r2["id"], world["line"]["id"], world["lot"]["id"],
                            100.0, scheduled_start="2026-08-12T00:00:00Z",
                            scheduled_end="2026-08-13T00:00:00Z")
        assert run2["changeover_minutes"] == 115, (
            "75 (SPECIALTY->LONG_CUT) + 40 (wear >= 0.80) + 0 (no allergen transition)"
        )

    def test_long_to_specialty_with_tier3_wear_composes_130(self, api):
        """PRD: "anything into `SPECIALTY` is 90"
        PRD: "at 0.80 or above it is 40 minutes"
        PRD: "among non-`ABORTED` runs on the same line whose `scheduled_end`
        is at or before the new run's `scheduled_start`, the one with the
        greatest `scheduled_end`"

        Design: Difficulty/combinatorial_formula/changeover_matrix_wear_tier_allergen_composition
        """
        world, r2, _ = self._setup_worn_specialty_line()
        schedule_run(r2["id"], world["line"]["id"], world["lot"]["id"],
                     100.0, scheduled_start="2026-08-12T00:00:00Z",
                     scheduled_end="2026-08-13T00:00:00Z")

        run3 = schedule_run(world["recipe"]["id"], world["line"]["id"],
                            world["lot"]["id"], 100.0,
                            scheduled_start="2026-08-14T00:00:00Z",
                            scheduled_end="2026-08-15T00:00:00Z")
        assert run3["changeover_minutes"] == 130, (
            "90 (LONG_CUT->SPECIALTY) + 40 (wear >= 0.80) + 0 (no allergen)"
        )
