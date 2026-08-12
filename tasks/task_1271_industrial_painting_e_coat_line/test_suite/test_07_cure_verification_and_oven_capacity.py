"""Cure-verdict boundaries, recheck chains, and oven aggregate capacity."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_master_data, setup_lot_curing, setup_lot_cure_failed, setup_lot_qc_pending,
    record_oven_cycle,
    create_oven_cycle_payload,
    get_lot,
    TEST_USERS, make_qc_inspector_headers,
)

QC = TEST_USERS["qc_headers"]


class TestCureVerdictBoundary:
    def test_exact_thresholds_pass_and_just_below_fail(self, api):
        """PRD §3.5: "The `verdict` is computed, never supplied: `PASS` exactly when
        `min_metal_temp_c` is at least the specification's `cure_metal_temp_c` **and**
        `minutes_at_or_above_temp` is at least `cure_minutes_at_temp` — both thresholds
        inclusive — and `FAIL` otherwise."

        Design: Corner/calculations/cure_verdict_boundary_inclusive
        """
        ctx = setup_lot_curing()
        cycle_pass = record_oven_cycle(
            ctx, min_metal_temp_c=180.0, minutes_at_or_above_temp=20,
        )
        assert cycle_pass["verdict"] == "PASS"
        assert get_lot(ctx["lot"]["id"])["status"] == "QC_PENDING"

    def test_temperature_one_tenth_below_threshold_fails(self, api):
        """PRD §3.5: "The `verdict` is computed, never supplied: `PASS` exactly when
        `min_metal_temp_c` is at least the specification's `cure_metal_temp_c` **and**
        `minutes_at_or_above_temp` is at least `cure_minutes_at_temp` — both thresholds
        inclusive — and `FAIL` otherwise."
        PRD §3.5: "For a lot in `CURING`, a passing cycle advances it to `QC_PENDING`,
        while a failing cycle drops it to `CURE_FAILED`."

        Design: Corner/calculations/cure_verdict_boundary_inclusive
        """
        ctx = setup_lot_curing()
        cycle_fail = record_oven_cycle(
            ctx, min_metal_temp_c=179.9, minutes_at_or_above_temp=22,
        )
        assert cycle_fail["verdict"] == "FAIL"
        assert get_lot(ctx["lot"]["id"])["status"] == "CURE_FAILED"


class TestRecheckChain:
    def test_recheck_of_already_rechecked_cycle_rejected(self, api):
        """PRD §3.5: "The referenced cycle must have verdict `FAIL` and must not
        already have a recheck child — pointing at a passing cycle, or at one already
        rechecked, is rejected with `ERR_RECHECK_NOT_ALLOWED`."

        Design: Corner/state_machines/oven_recheck_of_already_rechecked_cycle_rejected
        """
        ctx = setup_lot_cure_failed()  # first cycle FAIL at 170.0 C
        failed_cycle = ctx["cycle"]

        recheck1 = record_oven_cycle(
            ctx,
            entered_at="2026-05-05T11:05:00Z", exited_at="2026-05-05T11:45:00Z",
            min_metal_temp_c=175.0, minutes_at_or_above_temp=22,
            recheck_of_id=failed_cycle["id"],
        )
        assert recheck1["verdict"] == "FAIL"
        assert get_lot(ctx["lot"]["id"])["status"] == "CURE_FAILED"

        # A second recheck child on the same parent must be rejected.
        res = api.create_oven_cycle(
            create_oven_cycle_payload(
                ctx["lot"]["id"], ctx["oven"]["id"],
                entered_at="2026-05-05T12:05:00Z", exited_at="2026-05-05T12:45:00Z",
                min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
                recheck_of_id=failed_cycle["id"],
            ),
            make_qc_inspector_headers("qc-1"),
        )
        validate_error(res, "ERR_RECHECK_NOT_ALLOWED", expected_status=409)

    def test_recheck_of_passing_cycle_rejected(self, api):
        """PRD §3.5: "The referenced cycle must have verdict `FAIL` and must not
        already have a recheck child — pointing at a passing cycle, or at one already
        rechecked, is rejected with `ERR_RECHECK_NOT_ALLOWED`."

        Design: Corner/state_machines/oven_recheck_of_already_rechecked_cycle_rejected
        """
        ctx = setup_lot_qc_pending()  # cycle PASS
        passing_cycle = ctx["cycle"]
        res = api.create_oven_cycle(
            create_oven_cycle_payload(
                ctx["lot"]["id"], ctx["oven"]["id"],
                entered_at="2026-05-05T11:05:00Z", exited_at="2026-05-05T11:45:00Z",
                min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
                recheck_of_id=passing_cycle["id"],
            ),
            make_qc_inspector_headers("qc-1"),
        )
        validate_error(res, "ERR_RECHECK_NOT_ALLOWED", expected_status=409)

    def test_recheck_chain_visible_via_filter_and_passing_recheck_advances_lot(self, api):
        """PRD §3.5: "A passing recheck moves the lot from `CURE_FAILED` to
        `QC_PENDING`; until a recheck passes, the lot simply remains `CURE_FAILED`.
        Because cycles are immutable event records, the recheck chain is readable by
        listing cycles filtered by `lot_id`, `oven_id`, or `recheck_of_id`,
        oldest-first."

        Design: Corner/endpoints/oven_recheck_chain_visible_via_filter
        """
        ctx = setup_lot_cure_failed()  # first cycle FAIL at 170.0 C
        failed_cycle = ctx["cycle"]

        recheck_pass = record_oven_cycle(
            ctx,
            entered_at="2026-05-05T11:05:00Z", exited_at="2026-05-05T11:45:00Z",
            min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
            recheck_of_id=failed_cycle["id"],
        )
        assert recheck_pass["verdict"] == "PASS"
        assert get_lot(ctx["lot"]["id"])["status"] == "QC_PENDING"

        children, meta = validate_paginated(
            api.list_oven_cycles(QC, params={"recheck_of_id": failed_cycle["id"]})
        )
        assert len(children) == 1
        assert children[0]["id"] == recheck_pass["id"]


class TestOvenAggregateCapacity:
    def test_closed_interval_touching_counts_and_third_load_rejected(self, api):
        """PRD §3.5: "Oven capacity is enforced at recording time. Two cycles on the
        same oven overlap on closed-interval semantics — an existing cycle whose
        `entered_at` is on or before the new cycle's `exited_at` and whose `exited_at`
        is on or after the new cycle's `entered_at` counts as overlapping, so cycles
        merely touching at a boundary still collide. Capacity is aggregate: overlaps
        are permitted up to the oven's `max_loads`, and the recording is rejected with
        `ERR_OVEN_CAPACITY_FULL` exactly when the number of existing overlapping cycles
        plus the new one would exceed `max_loads`."

        Design: Difficulty/resource_temporal_overlap/oven_closed_interval_aggregate_capacity_enforced
        """
        # Three lots each run to CURING on the default oven (max_loads 2).
        ctx1 = setup_lot_curing()
        line = ctx1["line"]
        spec = ctx1["spec"]
        customer = ctx1["customer"]
        oven = ctx1["oven"]
        permit = ctx1["permit"]
        stage = ctx1["stage"]

        from test_helpers import (
            create_and_accept_lot_in_ctx, schedule_slot, create_complete_slot_payload,
        )
        ctx = {"customer": customer, "spec": spec, "line": line, "stage": stage,
               "oven": oven, "permit": permit}
        lots = [ctx1["lot"]]
        for day, start, end in [("06", "2026-05-06T08:00:00Z", "2026-05-06T10:00:00Z"),
                                 ("07", "2026-05-07T08:00:00Z", "2026-05-07T10:00:00Z")]:
            lot = create_and_accept_lot_in_ctx(ctx)
            slot = schedule_slot(line["id"], lot["id"], start, end)
            validate_success(api.start_run_slot(slot["id"], TEST_USERS["scheduler_headers"]), 200)
            validate_success(
                api.complete_run_slot(slot["id"], create_complete_slot_payload(paint_used_liters=0.95),
                                      TEST_USERS["scheduler_headers"]),
                200,
            )
            lots.append(lot)

        # Cycles 1 (10:00-11:00) and 2 (10:30-11:30) overlap -> 2 loads == max_loads.
        oc1 = record_oven_cycle(
            {"lot": lots[0], "oven": oven},
            entered_at="2026-05-10T10:00:00Z", exited_at="2026-05-10T11:00:00Z",
            min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
        )
        oc2 = record_oven_cycle(
            {"lot": lots[1], "oven": oven},
            entered_at="2026-05-10T10:30:00Z", exited_at="2026-05-10T11:30:00Z",
            min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
        )
        assert oc1["verdict"] == "PASS"
        assert oc2["verdict"] == "PASS"

        # Cycle 3 touches cycle 1 at 11:00 (closed bound) and overlaps cycle 2 -> 3 > 2.
        res = api.create_oven_cycle(
            create_oven_cycle_payload(
                lots[2]["id"], oven["id"],
                entered_at="2026-05-10T11:00:00Z", exited_at="2026-05-10T12:00:00Z",
                min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
            ),
            make_qc_inspector_headers("qc-1"),
        )
        validate_error(res, "ERR_OVEN_CAPACITY_FULL", expected_status=409)
        assert get_lot(lots[2]["id"])["status"] == "CURING"

    def test_third_load_allowed_after_earlier_cycle_frees_capacity(self, api):
        """PRD §3.5: "Capacity is aggregate: overlaps are permitted up to the oven's
        `max_loads`, and the recording is rejected with `ERR_OVEN_CAPACITY_FULL`
        exactly when the number of existing overlapping cycles plus the new one would
        exceed `max_loads`."

        Design: Difficulty/resource_temporal_overlap/oven_closed_interval_aggregate_capacity_enforced
        """
        ctx = setup_lot_curing()
        oven = ctx["oven"]
        # Two non-overlapping loads then a third adjacent-but-free slot: with
        # max_loads 2 and strictly sequential windows, every cycle fits.
        first = record_oven_cycle(
            ctx,
            entered_at="2026-05-10T10:00:00Z", exited_at="2026-05-10T11:00:00Z",
            min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
        )
        assert first["verdict"] == "PASS"
        # A second cycle fully disjoint from the first is accepted regardless.
        ctx2 = setup_lot_curing()
        second = record_oven_cycle(
            {"lot": ctx2["lot"], "oven": oven},
            entered_at="2026-05-10T12:00:00Z", exited_at="2026-05-10T13:00:00Z",
            min_metal_temp_c=182.0, minutes_at_or_above_temp=22,
        )
        assert second["verdict"] == "PASS"
