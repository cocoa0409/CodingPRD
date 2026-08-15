"""Lines and run scheduling: initial states, OCC on line version, half-open
window overlap, capacity, allergen zoning, changeover buffer, version bumps."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_production_line,
    assert_production_run,
    create_line,
    create_product,
    create_run,
    create_run_payload,
    get_line,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
SCHED = TEST_USERS["line_scheduler_headers"]


def _corn_product(**overrides):
    overrides.setdefault("allergen_class", "CORN_ONLY")
    return create_product(**overrides)


class TestRunCreationBasics:
    def test_new_run_enters_planned_and_pending(self, api):
        """PRD §3.5: "The new run enters with `production_status` `PLANNED` and
        `qc_status` `PENDING`." PRD §3.5: "Run creation also computes
        `masa_required_kg` as `planned_cases` multiplied by `packs_per_case`
        multiplied by `count_per_pack` multiplied by `unit_weight_g`, divided by
        1000, multiplied by the masa loss factor 1.05, rounded to two decimal
        places".
        planned 10 cases of 10 packs x 12 count x 30 g: 10 x 10 x 12 x 30 / 1000
        x 1.05 = 37.8 kg.

        Design: Corner/state_machines/sm_run_initial_states_are_planned_and_pending
        """
        product = _corn_product(sku_code="SM-INIT")
        line = create_line(line_code="L-INIT")
        run = create_run(
            product["id"], line["id"], planned_cases=10,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
        )
        assert_production_run(run)
        assert run["production_status"] == "PLANNED"
        assert run["qc_status"] == "PENDING"
        assert run["masa_required_kg"] == pytest.approx(37.8)

    def test_start_from_planned_rejected(self, api):
        """PRD §3.5: "Starting the run requires the run to be in `SCHEDULED`,
        requires any gating `ChangeoverRecord` to be `VERIFIED` (otherwise
        `ERR_CHANGEOVER_NOT_VERIFIED`), and requires full masa coverage — the sum
        of `allocated_kg` over the run's `RESERVED` allocations must be at least
        `masa_required_kg` (otherwise `ERR_MASA_INSUFFICIENT`)." A PLANNED run
        fails the from-state check with ERR_RUN_INVALID_STATE (§5).

        Design: Corner/state_machines/sm_run_start_from_planned_rejected
        """
        product = _corn_product(sku_code="SM-PS")
        line = create_line(line_code="L-PS")
        run = create_run(
            product["id"], line["id"], planned_cases=10,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T11:00:00Z",
        )
        validate_error(api.start_run(run["id"], SCHED), ApiErrorId.ERR_RUN_INVALID_STATE)


class TestLineWindowOverlap:
    def test_adjacent_run_accepted_half_open_semantics(self, api):
        """PRD §3.5: "The run's time window is a **half-open interval** `[start_at,
        end_at)`: two sibling runs on the same line overlap when the first's
        `start_at` is before the second's `end_at` and the first's `end_at` is
        after the second's `start_at`." and "Adjacency — one run's `end_at`
        exactly equal to the next's `start_at` — is **not** a conflict."
        run2 [12:00, 14:00) starts exactly at run1's end_at 12:00 -> accepted.

        Design: Difficulty/resource_temporal_overlap/line_run_windows_half_open_adjacency
        """
        product = _corn_product(sku_code="CORN-6-O1")
        line = create_line(line_code="L-O1")
        create_run(
            product["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
        )
        run2 = create_run(
            product["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T12:00:00Z", end_at="2026-08-02T14:00:00Z",
        )
        assert run2["production_status"] == "PLANNED"

    def test_overlapping_run_rejected(self, api):
        """PRD §3.5: "An overlap is rejected with `ERR_LINE_WINDOW_OVERLAP`."
        [11:59, 13:00) intersects the existing [10:00, 12:00) window because
        11:59 < 12:00.

        Design: Difficulty/resource_temporal_overlap/line_run_windows_half_open_adjacency
        """
        product = _corn_product(sku_code="CORN-6-O1")
        line = create_line(line_code="L-O1")
        create_run(
            product["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
        )
        create_run(
            product["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T12:00:00Z", end_at="2026-08-02T14:00:00Z",
        )
        validate_error(
            api.create_run(
                create_run_payload(
                    product["id"], line["id"], get_line(line["id"])["version"],
                    planned_cases=50,
                    start_at="2026-08-02T11:59:00Z", end_at="2026-08-02T13:00:00Z",
                ),
                SCHED,
            ),
            ApiErrorId.ERR_LINE_WINDOW_OVERLAP,
        )


class TestLineCapacity:
    def test_capacity_boundary_inclusive_then_exceeded(self, api):
        """PRD §3.5: "Line throughput is also enforced: `planned_cases` may not
        exceed `cases_per_hour` multiplied by the window length in hours; an
        overrun is rejected with `ERR_LINE_CAPACITY_EXCEEDED`."
        100 cases/hour x 2.5 h = 250: exactly 250 is accepted (inclusive),
        251 is rejected.

        Design: Corner/calculations/calc_line_capacity_exceeded
        """
        product = _corn_product(sku_code="C-CAP")
        line = create_line(line_code="L-CAP", cases_per_hour=100)
        ok_run = create_run(
            product["id"], line["id"], planned_cases=250,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:30:00Z",
        )
        assert ok_run["production_status"] == "PLANNED"
        validate_error(
            api.create_run(
                create_run_payload(
                    product["id"], line["id"], get_line(line["id"])["version"],
                    planned_cases=251,
                    start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T12:30:00Z",
                ),
                SCHED,
            ),
            ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED,
        )


class TestChangeoverWindowBuffer:
    def test_product_switch_without_buffer_rejected(self, api):
        """PRD §3.5: "When the immediately-preceding non-`CANCELLED` run on the
        line used a different product, a **product-switch buffer** is additionally
        required: the new run's `start_at` must be at least the previous run's
        `end_at` plus the `required_downtime_min` of the changeover that would be
        required between the two products; a shortfall is rejected with
        `ERR_CHANGEOVER_WINDOW_INSUFFICIENT`."
        SOY_BLENDED -> CORN_ONLY demands 120 minutes (FULL_SANITATION); the new
        run starts 60 minutes after the previous run's end -> rejected.

        Design: Corner/validations/val_changeover_window_insufficient
        """
        soy = create_product(
            sku_code="C-CWI-S", unit_weight_g=32, allergen_class="SOY_BLENDED"
        )
        corn = _corn_product(sku_code="C-CWI-C")
        line = create_line(line_code="L-CWI")
        create_run(
            soy["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T08:00:00Z", end_at="2026-08-02T10:00:00Z",
        )
        validate_error(
            api.create_run(
                create_run_payload(
                    corn["id"], line["id"], get_line(line["id"])["version"],
                    planned_cases=100,
                    start_at="2026-08-02T11:00:00Z", end_at="2026-08-02T13:00:00Z",
                ),
                SCHED,
            ),
            ApiErrorId.ERR_CHANGEOVER_WINDOW_INSUFFICIENT,
        )


class TestAllergenZoneVsTemporalPriority:
    def test_zone_violation_reported_over_window_overlap(self, api):
        """PRD §2.9: "When a request triggers multiple validations, they are
        evaluated in a fixed priority order, and the first failure surfaces its
        error; later failures are masked." with "6. Business safety — allergen
        zone, shelf-life gate, QC hold, changeover verification
        (`ERR_ALLERGEN_ZONE_VIOLATION`, `ERR_SHELF_LIFE_INSUFFICIENT`,
        `ERR_QC_HOLD_ACTIVE`, `ERR_CHANGEOVER_NOT_VERIFIED`)." listed ahead of
        "7. Business temporal — cook, steep, line-window overlap, changeover
        buffer, seasonal-window overlap (`ERR_COOK_INCOMPLETE`,
        `ERR_STEEP_INCOMPLETE`, `ERR_LINE_WINDOW_OVERLAP`,
        `ERR_CHANGEOVER_WINDOW_INSUFFICIENT`, `ERR_WINDOW_DATE_OVERLAP`)."
        PRD §3.5: "a product with `allergen_class` `WHEAT_FLOUR` or `SOY_BLENDED`
        may not be scheduled on a `DEDICATED_CORN` line — violation yields
        `ERR_ALLERGEN_ZONE_VIOLATION`."
        WHEAT_FLOUR on DEDICATED_CORN plus an overlapping window: the safety
        error wins.

        Design: Difficulty/priority_pair_validation_conflict/run_create_safety_beats_business_temporal
        """
        corn = _corn_product(sku_code="CORN-6-P2")
        wheat = create_product(
            sku_code="WHEAT-8-10", diameter_in="D8", count_per_pack=10,
            packs_per_case=8, unit_weight_g=45, allergen_class="WHEAT_FLOUR",
        )
        line = create_line(line_code="L-DED", allergen_zone="DEDICATED_CORN")
        create_run(
            corn["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
        )
        resp = api.create_run(
            create_run_payload(
                wheat["id"], line["id"], get_line(line["id"])["version"],
                planned_cases=50,
                start_at="2026-08-02T11:00:00Z", end_at="2026-08-02T13:00:00Z",
            ),
            SCHED,
        )
        err = validate_error(resp, ApiErrorId.ERR_ALLERGEN_ZONE_VIOLATION)
        assert err["error_id"] != ApiErrorId.ERR_LINE_WINDOW_OVERLAP

    def test_rejected_dual_failure_run_persists_nothing(self, api):
        """PRD §2.9: "When a request triggers multiple validations, they are
        evaluated in a fixed priority order, and the first failure surfaces its
        error; later failures are masked." PRD §2.4: "`version` (an integer that
        increments on every mutation of that entity)". A rejected create is no
        mutation: the line version stays put and no second run appears.

        Design: Difficulty/priority_pair_validation_conflict/run_create_safety_beats_business_temporal
        """
        corn = _corn_product(sku_code="CORN-6-P2")
        wheat = create_product(
            sku_code="WHEAT-8-10", diameter_in="D8", count_per_pack=10,
            packs_per_case=8, unit_weight_g=45, allergen_class="WHEAT_FLOUR",
        )
        line = create_line(line_code="L-DED", allergen_zone="DEDICATED_CORN")
        create_run(
            corn["id"], line["id"], planned_cases=100,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
        )
        before = get_line(line["id"])
        validate_error(
            api.create_run(
                create_run_payload(
                    wheat["id"], line["id"], before["version"],
                    planned_cases=50,
                    start_at="2026-08-02T11:00:00Z", end_at="2026-08-02T13:00:00Z",
                ),
                SCHED,
            ),
            ApiErrorId.ERR_ALLERGEN_ZONE_VIOLATION,
        )
        after = get_line(line["id"])
        assert after["version"] == before["version"], "rejection must not bump version"
        runs, meta = validate_paginated(api.list_line_runs(line["id"], SCHED))
        assert meta["total_count"] == 1 and len(runs) == 1


class TestLineOccAndVersioning:
    def test_stale_line_version_returns_412(self, api):
        """PRD §2.6: "Creating a production run requires `expected_line_version`
        as a non-optional input field carrying the client's last observed
        `version` of the target `ProductionLine`. If the line's current `version`
        has advanced since the client last read it — because another writer
        scheduled a run, started a run, or toggled line status — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from
        scheduling against a stale view of the line."
        Run A advanced the line version by one (PRD §3.5: "and increments the
        line's `version` by one"); reusing the stale snapshot fails.

        Design: Corner/cross_cutting_layers/cc_occ_stale_line_version_returns_412
        """
        product = _corn_product(sku_code="C-OCC1")
        line = create_line(line_code="L-OCC1")
        stale_v = line["version"]
        create_run(
            product["id"], line["id"], expected_line_version=stale_v,
            planned_cases=50,
            start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
        )
        validate_error(
            api.create_run(
                create_run_payload(
                    product["id"], line["id"], stale_v, planned_cases=50,
                    start_at="2026-08-02T14:00:00Z", end_at="2026-08-02T16:00:00Z",
                ),
                SCHED,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        after = get_line(line["id"])
        assert after["version"] == stale_v + 1, (
            "only run A's creation bumped the line version"
        )
        runs, meta = validate_paginated(api.list_line_runs(line["id"], SCHED))
        assert meta["total_count"] == 1

    def test_version_increments_by_one_on_every_status_toggle(self, api):
        """PRD §2.4: "`version` (an integer that increments on every mutation of
        that entity)". PRD §3.5: "taking a line down is blocked while any run on
        that line is `IN_PROGRESS` (`ERR_RUN_INVALID_STATE`), and every status
        toggle increments the line's `version` by one."
        create -> DOWN -> ACTIVE: each toggle lands exactly +1 higher.

        Design: Corner/cross_cutting_layers/cc_version_increments_on_every_mutation
        """
        line = create_line(line_code="L-VER")
        assert_production_line(line)
        down = validate_success(api.set_line_status(line["id"], "DOWN", PM))
        assert down["line_status"] == "DOWN"
        assert down["version"] == line["version"] + 1
        back = validate_success(api.set_line_status(line["id"], "ACTIVE", PM))
        assert back["line_status"] == "ACTIVE"
        assert back["version"] == down["version"] + 1
