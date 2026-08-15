"""Run start gates, quarantine cascade (release -> demote -> changeover cancel),
and the parallel QC dimension gating pack sealing."""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_masa,
    api_client,
    create_line,
    create_pack_order,
    create_product,
    create_run,
    get_line,
    make_quality_inspector_headers,
    make_sanitation_tech_headers,
    pack_order_pass_weight_check,
    schedule_run,
    setup_in_progress_run,
    setup_milled_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

SCHED = TEST_USERS["line_scheduler_headers"]
QI = TEST_USERS["quality_inspector_headers"]
PACK = TEST_USERS["packaging_lead_headers"]
MILLER = TEST_USERS["miller_operator_headers"]


def _soy_corn_line_with_two_runs():
    """Line with run A (SOY_BLENDED 08:00-10:00) and run B (CORN_ONLY
    12:00-14:00, exactly the 120-minute FULL_SANITATION buffer). Run B carries
    an auto-created gating changeover from the product switch."""
    ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-X1"})
    soy = create_product(sku_code="SOY-6-X1", unit_weight_g=32,
                         allergen_class="SOY_BLENDED")
    corn = create_product(sku_code="CORN-6-X1")
    line = create_line(line_code="L-X1")
    run_a = create_run(soy["id"], line["id"], planned_cases=100,
                       start_at="2026-08-02T08:00:00Z", end_at="2026-08-02T10:00:00Z")
    run_b = create_run(corn["id"], line["id"], planned_cases=100,
                       start_at="2026-08-02T12:00:00Z", end_at="2026-08-02T14:00:00Z")
    changeovers, meta = validate_paginated(api_client.list_run_changeovers(run_b["id"], SCHED))
    assert meta["total_count"] == 1, "product switch auto-creates one changeover"
    ctx.update({"soy": soy, "corn": corn, "line": line, "run_a": run_a,
                "run_b": run_b, "changeover": changeovers[0]})
    return ctx


class TestRunStartChangeoverGate:
    def test_start_blocked_while_changeover_not_verified(self, api):
        """PRD §3.5: "Starting the run requires the run to be in `SCHEDULED`,
        requires any gating `ChangeoverRecord` to be `VERIFIED` (otherwise
        `ERR_CHANGEOVER_NOT_VERIFIED`), and requires full masa coverage — the sum
        of `allocated_kg` over the run's `RESERVED` allocations must be at least
        `masa_required_kg` (otherwise `ERR_MASA_INSUFFICIENT`)."
        The gating changeover is still REQUIRED, so start fails.

        Design: Difficulty/cross_entity_state_dependency/run_start_blocked_until_changeover_verified
        """
        ctx = _soy_corn_line_with_two_runs()
        schedule_run(ctx["run_b"]["id"])
        allocate_masa(ctx["batch"]["id"], ctx["run_b"]["id"], 388.8)
        validate_error(
            api.start_run(ctx["run_b"]["id"], SCHED),
            ApiErrorId.ERR_CHANGEOVER_NOT_VERIFIED,
        )

    def test_start_succeeds_after_changeover_verified(self, api):
        """PRD §3.5: "A successful start flips every `RESERVED` allocation of the
        run to `CONSUMED`, sets the line's `current_product_id` to this run's
        product, increments the line's `version` by one, recomputes `line_posture`
        to `RUNNING`, and advances the run to `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/run_start_blocked_until_changeover_verified
        """
        ctx = _soy_corn_line_with_two_runs()
        schedule_run(ctx["run_b"]["id"])
        allocate_masa(ctx["batch"]["id"], ctx["run_b"]["id"], 388.8)
        co_id = ctx["changeover"]["id"]
        validate_success(
            api.begin_changeover(co_id, make_sanitation_tech_headers("san-01"))
        )
        validate_success(
            api.verify_changeover(co_id, make_quality_inspector_headers("qi-01"))
        )
        started = validate_success(api.start_run(ctx["run_b"]["id"], SCHED))
        assert started["production_status"] == "IN_PROGRESS"
        line = get_line(ctx["line"]["id"])
        assert line["current_product_id"] == ctx["corn"]["id"]


class TestQuarantineCascade:
    def test_quarantine_releases_reserved_allocations(self, api):
        """PRD §2.7: "When a batch is quarantined, three cascades fire in order:
        every `BatchAllocation` of that batch in `RESERVED` flips to `RELEASED`
        and the batch's `masa_available_kg` is restored per release".
        Quarantine returns the reserved 388.8 kg to the batch.

        Design: Difficulty/transitive_cascade/batch_quarantine_cascades_release_demote_changeover_cancel
        """
        ctx = _soy_corn_line_with_two_runs()
        schedule_run(ctx["run_b"]["id"])
        allocation = allocate_masa(ctx["batch"]["id"], ctx["run_b"]["id"], 388.8)
        batch = validate_success(api.quarantine_batch(ctx["batch"]["id"], QI))
        assert batch["batch_status"] == "QUARANTINED"
        assert batch["masa_available_kg"] == pytest.approx(1552.0), (
            "the released reservation is restored to the batch"
        )
        alloc = validate_success(api.get_allocation(allocation["id"], SCHED))
        assert alloc["allocation_status"] == "RELEASED"

    def test_quarantine_demotes_run_and_cancels_changeover(self, api):
        """PRD §2.7: "each affected run has its `masa_reserved_kg` recomputed, and
        any run in `SCHEDULED` whose recomputed `masa_reserved_kg` now falls below
        its `masa_required_kg` demotes from `SCHEDULED` to `PLANNED`; and each
        demoted run's gating `ChangeoverRecord`, if still in `REQUIRED`,
        `IN_PROGRESS`, or `FAILED`, flips to `CANCELLED`, and the owning line's
        `line_posture` is recomputed."

        Design: Difficulty/transitive_cascade/batch_quarantine_cascades_release_demote_changeover_cancel
        """
        ctx = _soy_corn_line_with_two_runs()
        schedule_run(ctx["run_b"]["id"])
        allocate_masa(ctx["batch"]["id"], ctx["run_b"]["id"], 388.8)
        validate_success(api.quarantine_batch(ctx["batch"]["id"], QI))
        run_b = validate_success(api.get_run(ctx["run_b"]["id"], SCHED))
        assert run_b["production_status"] == "PLANNED", "demoted by coverage loss"
        changeover = validate_success(api.get_changeover(ctx["changeover"]["id"], SCHED))
        assert changeover["changeover_status"] == "CANCELLED"
        line = get_line(ctx["line"]["id"])
        assert line["line_posture"] == "AVAILABLE", (
            "nothing running and no open changeovers remain"
        )


class TestParallelQcDimension:
    def test_qc_hold_blocks_seal_without_touching_production(self, api):
        """PRD §3.5: "In parallel to `production_status`, every run carries an
        independent `qc_status` dimension." and "The two dimensions advance
        independently — a run may be `IN_PROGRESS` and `ON_HOLD` simultaneously".
        PRD §3.7: "Sealing requires the pack order to be in `PASSED` and the
        parent run's `qc_status` to be anything other than `ON_HOLD` — sealing
        against an active QC hold is rejected with `ERR_QC_HOLD_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/production_run_parallel_qc_dimension
        """
        ctx = setup_in_progress_run(
            planned_cases=100, allocated_kg=388.8,
            product_overrides={"sku_code": "CORN-6-12C"},
            line_overrides={"line_code": "L-QC"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=50)
        pack_order_pass_weight_check(pack_order["id"], 50, [360.0, 361.0, 359.0])
        held = validate_success(api.qc_hold_run(ctx["run"]["id"], QI))
        assert held["qc_status"] == "ON_HOLD"
        assert held["production_status"] == "IN_PROGRESS", (
            "the production dimension is untouched by the QC hold"
        )
        validate_error(
            api.seal_pack_order(pack_order["id"], PACK), ApiErrorId.ERR_QC_HOLD_ACTIVE
        )

    def test_qc_release_allows_seal(self, api):
        """PRD §3.5: "Releasing the hold moves `qc_status` from `ON_HOLD` to
        `PASSED`." PRD §3.7: "A successful seal stamps `sealed_at` with the
        logical clock, computes `expires_on` as the ISO date `sealed_at` plus the
        product's `shelf_life_days`, initializes `cases_available` to
        `cases_packed`, and advances the pack order to terminal `SEALED`."

        Design: Difficulty/non_linear_state_machine/production_run_parallel_qc_dimension
        """
        ctx = setup_in_progress_run(
            planned_cases=100, allocated_kg=388.8,
            product_overrides={"sku_code": "CORN-6-12C"},
            line_overrides={"line_code": "L-QC"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=50)
        pack_order_pass_weight_check(pack_order["id"], 50, [360.0, 361.0, 359.0])
        validate_success(api.qc_hold_run(ctx["run"]["id"], QI))
        released = validate_success(api.qc_release_run(ctx["run"]["id"], QI))
        assert released["qc_status"] == "PASSED"
        assert released["production_status"] == "IN_PROGRESS"
        sealed = validate_success(api.seal_pack_order(pack_order["id"], PACK))
        assert sealed["pack_status"] == "SEALED"
