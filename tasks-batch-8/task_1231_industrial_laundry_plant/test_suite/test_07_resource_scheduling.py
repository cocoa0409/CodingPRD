"""Machine and line scheduling: half-open wash-machine intervals, buffered
closed finish-line intervals, and tally-time throughput/loss accounting."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_finish_run,
    setup_stop_received, create_batch_locked, create_batch_posted,
    stage_wash_load, drive_load_to_finished, get_wash_load,
)

OPERATOR = TEST_USERS["plant_operator_headers"]

DAY = "2026-05-02"


def _ctx_with_posted_batch(pieces=30):
    ctx = setup_stop_received(
        stop_overrides={"declared_soiled_weight_lb": 15.0},
        carts=[{"cart_tag": "CART-1", "scale_weight_lb": 15.0}],
    )
    ctx["batch"] = create_batch_posted(
        ctx["stop"]["id"],
        [{"category_id": ctx["category"]["id"], "pieces": pieces}],
    )
    return ctx


def _finished_load(ctx, machine_id, start, end):
    load = stage_wash_load(
        ctx["batch"]["id"], ctx["category"]["id"],
        machine_id=machine_id,
        scheduled_start=start, scheduled_end=end,
    )
    return drive_load_to_finished(load["id"], hygienic_test_required=False)


class TestWashMachineOverlap:
    def test_adjacent_load_allowed_overlapping_load_rejected(self, api):
        """PRD §2.8: "A wash load occupies its `machine_id` over the half-open interval from `scheduled_start` (inclusive) to `scheduled_end` (exclusive). A conflict exists when another wash load on the same `machine_id`, in any of the states `STAGED`, `RUNNING`, `AWAITING_TEST`, or `REWASH_PENDING`, has an interval satisfying: the other load's start is strictly before this load's end, and this load's start is strictly before the other load's end. Under half-open semantics, adjacent loads — where one load's `scheduled_end` equals the other's `scheduled_start` — are allowed. A conflicting start is rejected with `ERR_MACHINE_TIME_OVERLAP` (HTTP 409)."
        PRD §2.9: "Temporal integrity: the wash-machine half-open overlap guard, the finish-line buffered closed-interval overlap guard, and the strictly-increasing time-range requirement — surfaced as `ERR_MACHINE_TIME_OVERLAP`, `ERR_LINE_TIME_OVERLAP`, or `ERR_INVALID_TIME_RANGE` (HTTP 409 for the two overlap codes, 422 for the time range). Applies across wash-load staging, wash-load starting, finish-run queuing, and finish-run tallying."

        Design: Difficulty/resource_temporal_overlap/wash_machine_half_open_adjacency_allowed
        """
        ctx = _ctx_with_posted_batch(pieces=30)
        load_a = stage_wash_load(
            ctx["batch"]["id"], ctx["category"]["id"], machine_id="M1",
            scheduled_start=f"{DAY}T08:00:00Z", scheduled_end=f"{DAY}T09:00:00Z",
        )
        validate_success(api.start_wash_load(load_a["id"], OPERATOR), 200)

        # Adjacent: B starts exactly when A ends -> allowed under half-open.
        load_b = stage_wash_load(
            ctx["batch"]["id"], ctx["category"]["id"], machine_id="M1",
            scheduled_start=f"{DAY}T09:00:00Z", scheduled_end=f"{DAY}T10:00:00Z",
        )
        started_b = validate_success(api.start_wash_load(load_b["id"], OPERATOR), 200)
        assert started_b["status"] == "RUNNING", (
            "adjacent load starting at the other's scheduled_end must be allowed"
        )

        # Overlapping: C starts one second before A ends -> the overlap guard
        # of §2.8 applies at staging (PRD §2.9 item 9), so staging C is
        # rejected outright against the RUNNING load A.
        resp = api.create_wash_load(
            {
                "batch_id": ctx["batch"]["id"],
                "category_id": ctx["category"]["id"],
                "machine_id": "M1",
                "scheduled_start": f"{DAY}T08:59:59Z",
                "scheduled_end": f"{DAY}T10:00:00Z",
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_TIME_OVERLAP)

    def test_same_window_on_different_machine_allowed(self, api):
        """PRD §2.8: "A conflict exists when another wash load on the same `machine_id`, in any of the states `STAGED`, `RUNNING`, `AWAITING_TEST`, or `REWASH_PENDING`, has an interval satisfying: the other load's start is strictly before this load's end, and this load's start is strictly before the other load's end."

        Design: Difficulty/resource_temporal_overlap/wash_machine_half_open_adjacency_allowed
        """
        ctx = _ctx_with_posted_batch(pieces=30)
        load_a = stage_wash_load(
            ctx["batch"]["id"], ctx["category"]["id"], machine_id="M1",
            scheduled_start=f"{DAY}T08:00:00Z", scheduled_end=f"{DAY}T09:00:00Z",
        )
        validate_success(api.start_wash_load(load_a["id"], OPERATOR), 200)
        load_d = stage_wash_load(
            ctx["batch"]["id"], ctx["category"]["id"], machine_id="M2",
            scheduled_start=f"{DAY}T08:00:00Z", scheduled_end=f"{DAY}T09:00:00Z",
        )
        started_d = validate_success(api.start_wash_load(load_d["id"], OPERATOR), 200)
        assert started_d["status"] == "RUNNING", (
            "the overlap guard is per machine_id; a different machine must not conflict"
        )


class TestFinishLineBufferedOverlap:
    def _ctx_with_two_finished_loads(self):
        ctx = _ctx_with_posted_batch(pieces=30)
        ctx["l1"] = _finished_load(ctx, "M1", f"{DAY}T07:00:00Z", f"{DAY}T08:00:00Z")
        ctx["l2"] = _finished_load(ctx, "M2", f"{DAY}T07:00:00Z", f"{DAY}T08:00:00Z")
        return ctx

    def test_buffered_overlap_rejected_and_clear_run_tallied(self, api):
        """PRD §2.8: "A finish run occupies its `line_id` over a buffered closed interval: from ten minutes before `scheduled_start` through ten minutes after `scheduled_end`, both endpoints inclusive. A conflict exists when another finish run on the same `line_id`, in state `QUEUED` or `TALLIED`, has its own buffered closed interval intersecting this one; two closed intervals intersect when the first interval's start is less than or equal to the second interval's end, and the second interval's start is less than or equal to the first interval's end. A conflicting tally is rejected with `ERR_LINE_TIME_OVERLAP` (HTTP 409)."
        PRD §2.9: "Temporal integrity: the wash-machine half-open overlap guard, the finish-line buffered closed-interval overlap guard, and the strictly-increasing time-range requirement — surfaced as `ERR_MACHINE_TIME_OVERLAP`, `ERR_LINE_TIME_OVERLAP`, or `ERR_INVALID_TIME_RANGE` (HTTP 409 for the two overlap codes, 422 for the time range). Applies across wash-load staging, wash-load starting, finish-run queuing, and finish-run tallying."

        Design: Difficulty/resource_temporal_overlap/finish_line_buffered_closed_interval_blocks
        """
        ctx = self._ctx_with_two_finished_loads()
        run_a = validate_success(api.create_finish_run(
            {
                "wash_load_id": ctx["l1"]["id"], "line_id": "F1",
                "scheduled_start": f"{DAY}T09:00:00Z",
                "scheduled_end": f"{DAY}T10:00:00Z",
            }, OPERATOR), 201)
        tallied_a = validate_success(
            api.tally_finish_run(run_a["id"], {"pieces_out": 28}, OPERATOR), 200)
        assert tallied_a["status"] == "TALLIED"

        # B [10:05, 10:30] buffered [09:55, 10:40] intersects A's [08:50, 10:10];
        # the guard applies at queuing (PRD §2.9 item 9), so B never exists.
        err_b = api.create_finish_run(
            {
                "wash_load_id": ctx["l2"]["id"], "line_id": "F1",
                "scheduled_start": f"{DAY}T10:05:00Z",
                "scheduled_end": f"{DAY}T10:30:00Z",
            }, OPERATOR)
        validate_error(err_b, ApiErrorId.ERR_LINE_TIME_OVERLAP)

        # D [10:21, 10:30] buffered [10:11, 10:40] clears A's [08:50, 10:10].
        run_d = validate_success(api.create_finish_run(
            {
                "wash_load_id": ctx["l2"]["id"], "line_id": "F1",
                "scheduled_start": f"{DAY}T10:21:00Z",
                "scheduled_end": f"{DAY}T10:30:00Z",
            }, OPERATOR), 201)
        tallied_d = validate_success(
            api.tally_finish_run(run_d["id"], {"pieces_out": 29}, OPERATOR), 200)
        assert tallied_d["status"] == "TALLIED", (
            "a run whose buffered interval starts after the other's buffered "
            "end must tally cleanly"
        )

    def test_buffered_edges_touching_is_a_conflict(self, api):
        """PRD §2.8: "Because the buffer is closed, two runs whose buffered edges merely touch are in conflict, unlike wash machines where touching is permitted."
        PRD §2.9: "Temporal integrity: the wash-machine half-open overlap guard, the finish-line buffered closed-interval overlap guard, and the strictly-increasing time-range requirement — surfaced as `ERR_MACHINE_TIME_OVERLAP`, `ERR_LINE_TIME_OVERLAP`, or `ERR_INVALID_TIME_RANGE` (HTTP 409 for the two overlap codes, 422 for the time range). Applies across wash-load staging, wash-load starting, finish-run queuing, and finish-run tallying."

        Design: Difficulty/resource_temporal_overlap/finish_line_buffered_closed_interval_blocks
        """
        ctx = self._ctx_with_two_finished_loads()
        run_a = validate_success(api.create_finish_run(
            {
                "wash_load_id": ctx["l1"]["id"], "line_id": "F1",
                "scheduled_start": f"{DAY}T09:00:00Z",
                "scheduled_end": f"{DAY}T10:00:00Z",
            }, OPERATOR), 201)
        validate_success(api.tally_finish_run(run_a["id"], {"pieces_out": 28}, OPERATOR), 200)

        # E [10:20, 10:30] buffered [10:10, 10:40] touches A's buffered end
        # 10:10; the guard applies at queuing (PRD §2.9 item 9).
        resp = api.create_finish_run(
            {
                "wash_load_id": ctx["l2"]["id"], "line_id": "F1",
                "scheduled_start": f"{DAY}T10:20:00Z",
                "scheduled_end": f"{DAY}T10:30:00Z",
            }, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_LINE_TIME_OVERLAP)


class TestTallyAccounting:
    def _ctx_with_queued_run(self, api, pieces=30):
        ctx = _ctx_with_posted_batch(pieces=pieces)
        load = _finished_load(ctx, "M1", f"{DAY}T07:00:00Z", f"{DAY}T08:00:00Z")
        run = validate_success(api.create_finish_run(
            {
                "wash_load_id": load["id"], "line_id": "F1",
                "scheduled_start": f"{DAY}T09:00:00Z",
                "scheduled_end": f"{DAY}T10:00:00Z",
            }, OPERATOR), 201)
        return ctx, run

    def test_tally_computes_loss_and_throughput(self, api):
        """PRD §3.5: "The run's `linen_loss_pieces` is `pieces_in` minus `pieces_out`, and is never negative by construction of the guard. The run's `throughput_pieces_per_hour` is `pieces_out` divided by the occupancy duration in hours — the difference between `scheduled_end` and `scheduled_start` measured in seconds and divided by 3600 — rounded half-up to 2 decimal places, and zero when the duration is not positive."

        Design: Corner/calculations/finish_throughput_and_loss_computed_at_tally
        """
        _, run = self._ctx_with_queued_run(api, pieces=30)
        data = validate_success(
            api.tally_finish_run(run["id"], {"pieces_out": 28}, OPERATOR), 200)
        assert_finish_run(data)
        assert data["status"] == "TALLIED"
        assert data["pieces_in"] == 30
        assert data["linen_loss_pieces"] == 2, (
            f"loss must be 30 - 28 = 2, got {data['linen_loss_pieces']}"
        )
        assert data["throughput_pieces_per_hour"] == 28.0, (
            f"28 pieces over 1 hour must give 28.0, "
            f"got {data['throughput_pieces_per_hour']}"
        )

    def test_tally_pieces_out_above_pieces_in_rejected(self, api):
        """PRD §3.5: "Tallying moves the run from `QUEUED` to `TALLIED` under two guards: `pieces_out` may not exceed `pieces_in` — an over-tally fails with `ERR_TALLY_EXCEEDS_INPUT` — and the line's buffered closed-interval guard of §2.8 must pass against other `QUEUED` or `TALLIED` runs on the same line, with conflicts rejected as `ERR_LINE_TIME_OVERLAP`."

        Design: Corner/calculations/finish_tally_pieces_out_exceeds_input_rejected
        """
        _, run = self._ctx_with_queued_run(api, pieces=30)
        resp = api.tally_finish_run(run["id"], {"pieces_out": 31}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_TALLY_EXCEEDS_INPUT)
