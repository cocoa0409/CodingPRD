"""Packing-run gates and lifecycle: scheduling windows, weight splits, the color
minimum, spec supersession, cancellation, and completion visibility."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate_bins,
    complete_run,
    create_active_spec,
    create_grower_with_block,
    create_open_pool,
    create_packing_run_payload,
    create_room,
    create_spec_payload,
    get_success_data,
    open_room,
    receive_lot,
    release_allocation,
    schedule_run,
    seal_room,
    setup_packable_lot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["packing_supervisor_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]


class TestRunSchedulingGates:
    def test_run_window_invalid_rejected(self, api):
        """PRD §3.4: "the window must be strictly positive — `scheduled_end`
        strictly after `scheduled_start` — else `ERR_RUN_WINDOW_INVALID`"

        Design: Corner/validations/c_run_window_invalid_rejected
        """
        ctx = setup_packable_lot()
        resp = api.create_packing_run(
            create_packing_run_payload(
                ctx["lot"]["id"], ctx["spec"]["id"], ctx["pool"]["id"],
                scheduled_start="2026-08-02T08:00:00Z",
                scheduled_end="2026-08-02T08:00:00Z", input_weight_lbs=500),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_INVALID)

    def test_run_input_exceeds_balance_rejected(self, api):
        """PRD §3.4: "the `input_weight_lbs` must be strictly positive and no more
        than the lot's current `weight_balance_lbs`, else
        `ERR_WEIGHT_BALANCE_EXCEEDED`"

        Design: Corner/validations/c_run_input_exceeds_balance_rejected
        """
        ctx = setup_packable_lot(received_bin_count=20, received_weight_lbs=19000)
        resp = api.create_packing_run(
            create_packing_run_payload(ctx["lot"]["id"], ctx["spec"]["id"],
                                       ctx["pool"]["id"], input_weight_lbs=20000),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_WEIGHT_BALANCE_EXCEEDED)

    def test_color_boundary_exactly_at_min_passes(self, api):
        """PRD §3.4: "the lot's `avg_color_pct` must be at least the spec's
        `color_min_pct` — equality passes and a strictly lower value is rejected
        with `ERR_COLOR_BELOW_SPEC`"

        Design: Corner/validations/c_color_boundary_exactly_at_min_passes
        """
        grower, block = create_grower_with_block()
        lot_ok = receive_lot(grower["id"], block["id"], 2, 1000, 66)
        lot_low = receive_lot(grower["id"], block["id"], 2, 1000, 65)
        room = create_room()
        alloc_ok = allocate_bins(room["id"], lot_ok["id"], 2)
        alloc_low = allocate_bins(room["id"], lot_low["id"], 2)
        seal_room(room)
        open_room(room["id"])
        release_allocation(alloc_ok["id"])
        release_allocation(alloc_low["id"])
        spec = create_active_spec(color_min_pct=66)
        pool = create_open_pool()

        run_ok = validate_success(api.create_packing_run(
            create_packing_run_payload(
                lot_ok["id"], spec["id"], pool["id"], input_weight_lbs=500,
                scheduled_start="2026-08-02T08:00:00Z",
                scheduled_end="2026-08-02T12:00:00Z"),
            SUPERVISOR), 201)
        assert run_ok["status"] == "SCHEDULED", "66 >= 66 passes the color gate"

        resp = api.create_packing_run(
            create_packing_run_payload(
                lot_low["id"], spec["id"], pool["id"], input_weight_lbs=500,
                scheduled_start="2026-08-02T12:00:00Z",
                scheduled_end="2026-08-02T16:00:00Z"),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_COLOR_BELOW_SPEC)


class TestSpecSupersession:
    def test_superseded_spec_rejects_new_run(self, api):
        """PRD §3.4: "creating a new `ACTIVE` spec in the same scope — same
        `customer_name`, `size_class`, and `pack_style` — automatically supersedes
        the previously `ACTIVE` spec, which transitions `ACTIVE → SUPERSEDED`. A
        `SUPERSEDED` spec refuses new work: scheduling a run against it is
        rejected with `ERR_SPEC_INVALID_STATE`."

        Design: Corner/state_machines/c_superseded_spec_rejects_new_run
        """
        ctx = setup_packable_lot()
        spec1 = ctx["spec"]

        spec2 = validate_success(api.create_spec(
            create_spec_payload(label_code="RC-TRAY-V2", grade_min="FANCY",
                                color_min_pct=60),
            POOL_MGR), 201)
        old = validate_success(api.get_spec(spec1["id"], ADMIN))
        assert old["status"] == "SUPERSEDED", "same scope supersedes the prior spec"

        resp = api.create_packing_run(
            create_packing_run_payload(ctx["lot"]["id"], spec1["id"],
                                       ctx["pool"]["id"], input_weight_lbs=1000),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_SPEC_INVALID_STATE)

        run2 = validate_success(api.create_packing_run(
            create_packing_run_payload(ctx["lot"]["id"], spec2["id"],
                                       ctx["pool"]["id"], input_weight_lbs=1000),
            SUPERVISOR), 201)
        assert run2["status"] == "SCHEDULED", "the replacement spec accepts runs"


class TestRunCompletionAndCancellation:
    def test_run_weight_mismatch_rejected(self, api):
        """PRD §3.4: "The three weights must sum exactly to the run's
        `input_weight_lbs`; any mismatch is rejected with
        `ERR_RUN_WEIGHT_MISMATCH`."

        Design: Corner/validations/c_run_weight_mismatch_rejected
        """
        ctx = setup_packable_lot()
        run = schedule_run(ctx, input_weight_lbs=4000)

        # 3400 + 400 + 100 = 3900 != 4000.
        resp = api.complete_packing_run(
            run["id"],
            {"cartons_produced": 20, "packed_weight_lbs": 3400,
             "cull_weight_lbs": 400, "juice_weight_lbs": 100},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_RUN_WEIGHT_MISMATCH)
        after = validate_success(api.get_packing_run(run["id"], ADMIN))
        assert after["status"] == "SCHEDULED", "no partial completion"

    def test_run_cancel_then_complete_rejected(self, api):
        """PRD §3.4: "a `SCHEDULED` run (else `ERR_RUN_INVALID_STATE`) moves to
        `CANCELLED`, freeing its line window with no weight or pool effects, since
        nothing was consumed."
        PRD §3.4: "The run must be `SCHEDULED` (else `ERR_RUN_INVALID_STATE`)"

        Design: Corner/state_machines/c_run_cancel_then_complete_rejected
        """
        ctx = setup_packable_lot()
        run = schedule_run(ctx, input_weight_lbs=1000)

        cancelled = validate_success(api.cancel_packing_run(run["id"], SUPERVISOR))
        assert cancelled["status"] == "CANCELLED"

        resp = api.complete_packing_run(
            run["id"],
            {"cartons_produced": 5, "packed_weight_lbs": 1000,
             "cull_weight_lbs": 0, "juice_weight_lbs": 0},
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_RUN_INVALID_STATE)

    def test_immediate_consistency_on_complete(self, api):
        """PRD §3.4: "A successful completion moves the run `SCHEDULED →
        COMPLETED` and sets its `packout_pct` — one hundred times
        `packed_weight_lbs` divided by the sum of the three output weights,
        rounded half-up to one decimal place — then cascades outward. The lot's
        `weight_balance_lbs` falls by `input_weight_lbs`, and its
        `actual_packout_pct` is recomputed as a chronological aggregate over the
        lot's `COMPLETED`, non-`VOIDED` runs"

        Design: Corner/consistency_model/c_immediate_consistency_on_complete
        """
        ctx = setup_packable_lot(received_bin_count=20, received_weight_lbs=19000)
        run = schedule_run(ctx, input_weight_lbs=4000)

        completed = complete_run(run["id"], cartons_produced=20,
                                 packed_weight_lbs=3400, cull_weight_lbs=400,
                                 juice_weight_lbs=200)
        assert completed["status"] == "COMPLETED", "same-response visibility"
        assert completed["packout_pct"] == pytest.approx(85.0, abs=1e-6)

        lot = get_success_data(api.get_lot(ctx["lot"]["id"], ADMIN))
        assert lot["weight_balance_lbs"] == pytest.approx(15000)
        assert lot["actual_packout_pct"] == pytest.approx(85.0, abs=1e-6), (
            "immediately consistent follow-up read"
        )


class TestLineWindowOverlap:
    def _released_ctx_with_run_a(self, api):
        ctx = setup_packable_lot(received_bin_count=20, received_weight_lbs=19000)
        run_a = schedule_run(ctx, input_weight_lbs=5000,
                             scheduled_start="2026-08-02T08:00:00Z",
                             scheduled_end="2026-08-02T12:00:00Z",
                             line_code="LINE_1")
        return ctx, run_a

    def test_overlapping_window_rejected(self, api):
        """PRD §3.4: "the window must not overlap any other `SCHEDULED` run on the
        same `line_code`, where windows are half-open intervals so back-to-back
        adjacency is permitted, else `ERR_LINE_SCHEDULE_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/line_window_overlap_half_open
        """
        ctx, run_a = self._released_ctx_with_run_a(api)
        assert run_a["status"] == "SCHEDULED"

        # 10:00-13:00 collides with the 08:00-12:00 window on the same line.
        resp = api.create_packing_run(
            create_packing_run_payload(
                ctx["lot"]["id"], ctx["spec"]["id"], ctx["pool"]["id"],
                line_code="LINE_1", scheduled_start="2026-08-02T10:00:00Z",
                scheduled_end="2026-08-02T13:00:00Z", input_weight_lbs=5000),
            SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_LINE_SCHEDULE_OVERLAP)

    def test_adjacent_and_other_line_windows_allowed(self, api):
        """PRD §3.4: "the window must not overlap any other `SCHEDULED` run on the
        same `line_code`, where windows are half-open intervals so back-to-back
        adjacency is permitted, else `ERR_LINE_SCHEDULE_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/line_window_overlap_half_open
        """
        ctx, run_a = self._released_ctx_with_run_a(api)

        # Half-open adjacency at exactly 12:00 is permitted.
        run_b = validate_success(api.create_packing_run(
            create_packing_run_payload(
                ctx["lot"]["id"], ctx["spec"]["id"], ctx["pool"]["id"],
                line_code="LINE_1", scheduled_start="2026-08-02T12:00:00Z",
                scheduled_end="2026-08-02T14:00:00Z", input_weight_lbs=5000),
            SUPERVISOR), 201)
        assert run_b["status"] == "SCHEDULED"

        # The very window that collided on LINE_1 is free on LINE_2.
        run_c = validate_success(api.create_packing_run(
            create_packing_run_payload(
                ctx["lot"]["id"], ctx["spec"]["id"], ctx["pool"]["id"],
                line_code="LINE_2", scheduled_start="2026-08-02T10:00:00Z",
                scheduled_end="2026-08-02T13:00:00Z", input_weight_lbs=5000),
            SUPERVISOR), 201)
        assert run_c["status"] == "SCHEDULED"
