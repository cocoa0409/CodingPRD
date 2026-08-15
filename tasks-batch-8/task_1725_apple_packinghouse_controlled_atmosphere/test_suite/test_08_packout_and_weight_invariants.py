"""Packout percentage variants (estimated vs actual) and the complete/void
weight-balance conservation invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    allocate_bins,
    complete_run,
    create_active_spec,
    create_grower_with_block,
    create_open_pool,
    create_room,
    open_room,
    presize_lot,
    receive_lot,
    refresh_lot,
    refresh_pool,
    release_allocation,
    schedule_run,
    seal_room,
    setup_packable_lot,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["packing_supervisor_headers"]


class TestPackoutEstimatedVsActual:
    def _setup_presized_released_lot(self, api):
        """Lot of 11000 lbs presized 2000/5000/3000 + 1000 cull (est 90.9),
        then stored, released, and packable with spec + pool."""
        # Presize must run while the lot is RECEIVED, i.e. before allocation.
        grower, block = create_grower_with_block()
        lot = receive_lot(grower["id"], block["id"], 12, 11000, 80)
        lot = presize_lot(lot["id"], 2000, 5000, 3000, 1000)
        room = create_room()
        allocation = allocate_bins(room["id"], lot["id"], 12)
        seal_room(room)
        open_room(room["id"])
        release_allocation(allocation["id"])
        return {"grower": grower, "block": block, "lot": lot, "room": room,
                "allocation": allocation, "spec": create_active_spec(),
                "pool": create_open_pool()}

    def test_estimated_then_actual_packout(self, api):
        """PRD §3.1: "On success the profile is stored, the lot transitions
        `RECEIVED → PRESIZED`, and its forward-looking `est_packout_pct` is
        computed: one hundred times the combined graded weight — small plus medium
        plus large — divided by the total presize throughput including culls (the
        three size classes plus `presize_cull_lbs`), rounded half-up to one
        decimal place."
        PRD §3.4: "its `actual_packout_pct` is recomputed as a chronological
        aggregate over the lot's `COMPLETED`, non-`VOIDED` runs: one hundred times
        the summed `packed_weight_lbs` divided by the summed packed, cull, and
        juice weights across those runs, rounded half-up to one decimal place."
        PRD §3.4: "A `RELEASED` lot whose balance reaches zero transitions
        `RELEASED → PACKED`."

        Design: Difficulty/dual_variant_calc/lot_packout_estimated_vs_actual
        """
        ctx = self._setup_presized_released_lot(api)
        assert ctx["lot"]["est_packout_pct"] == pytest.approx(90.9, abs=1e-6), (
            "100 * 10000 / 11000 rounded half-up to one decimal"
        )
        assert ctx["lot"]["actual_packout_pct"] is None, (
            "null until the lot's first completion"
        )

        run = schedule_run(ctx, input_weight_lbs=11000)
        completed = complete_run(run["id"], cartons_produced=50,
                                 packed_weight_lbs=9350, cull_weight_lbs=1100,
                                 juice_weight_lbs=550)
        assert completed["packout_pct"] == pytest.approx(85.0, abs=1e-6)

        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["est_packout_pct"] == pytest.approx(90.9, abs=1e-6)
        assert lot["actual_packout_pct"] == pytest.approx(85.0, abs=1e-6), (
            "9350 / 11000 realized at the line"
        )
        assert lot["weight_balance_lbs"] == pytest.approx(0)
        assert lot["status"] == "PACKED", "full balance consumed"

    def test_estimate_diverges_from_actual_on_line_cull_difference(self, api):
        """PRD §3.1: "Because it is derived from the presize profile rather than
        realized line results, the estimate can diverge from the eventual
        `actual_packout_pct` whenever line-level cull and juice differ from the
        presize cull estimate."

        Design: Difficulty/dual_variant_calc/lot_packout_estimated_vs_actual
        """
        ctx = self._setup_presized_released_lot(api)
        est = ctx["lot"]["est_packout_pct"]

        run = schedule_run(ctx, input_weight_lbs=11000)
        complete_run(run["id"], cartons_produced=50, packed_weight_lbs=9350,
                     cull_weight_lbs=1100, juice_weight_lbs=550)

        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["est_packout_pct"] == pytest.approx(est, abs=1e-6), (
            "the presize-derived estimate is untouched by completions"
        )
        assert lot["actual_packout_pct"] == pytest.approx(85.0, abs=1e-6)
        assert abs(lot["est_packout_pct"] - lot["actual_packout_pct"]) > 1.0, (
            "variants diverge: presize estimated 1000 cull lbs, the line "
            "realized 1650 cull+juice lbs"
        )


class TestCompleteVoidInvariant:
    def test_complete_then_void_restores_weight_balance(self, api):
        """PRD §2.10: "Completing a run and later voiding it forms a compensating
        pair that leaves the balance exactly unchanged."
        PRD §3.4: "Runs in `SCHEDULED`, `CANCELLED`, or `VOIDED` status never
        enter the aggregate, which remains null until the lot's first
        completion."

        Design: Difficulty/compensating_invariant/run_complete_void_weight_balance_restored
        """
        ctx = setup_packable_lot(received_bin_count=20, received_weight_lbs=19000)
        run = schedule_run(ctx, input_weight_lbs=4000)
        complete_run(run["id"], cartons_produced=20, packed_weight_lbs=3400,
                     cull_weight_lbs=400, juice_weight_lbs=200)

        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["weight_balance_lbs"] == pytest.approx(15000)
        assert lot["actual_packout_pct"] == pytest.approx(85.0, abs=1e-6)
        pool = refresh_pool(ctx["pool"]["id"])
        assert pool["total_packed_cartons"] == 20

        voided = validate_success(api.void_packing_run(run["id"], SUPERVISOR))
        assert voided["status"] == "VOIDED"
        assert voided.get("packout_pct") is None, "void clears the run's packout"

        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["weight_balance_lbs"] == pytest.approx(19000), (
            "complete + void conserves lbs exactly"
        )
        assert lot["actual_packout_pct"] is None, (
            "no COMPLETED non-VOIDED runs remain"
        )
        assert lot["status"] == "RELEASED", "still packable"
        pool = refresh_pool(ctx["pool"]["id"])
        assert pool["total_packed_cartons"] == 0, "carton attribution compensated"

    def test_void_of_full_pack_reverts_lot_to_released(self, api):
        """PRD §3.4: "A `PACKED` lot whose balance is positive again reverts
        `PACKED → RELEASED`, reopening it for further packing — the deliberate
        revision loop of the lot lifecycle."
        PRD §3.4: "The void moves the run `COMPLETED → VOIDED`, clears its
        `packout_pct`, credits the lot's `weight_balance_lbs` back by
        `input_weight_lbs`, and recomputes `actual_packout_pct` excluding the
        voided run."

        Design: Difficulty/compensating_invariant/run_complete_void_weight_balance_restored
        """
        ctx = setup_packable_lot(received_bin_count=20, received_weight_lbs=19000)
        run = schedule_run(ctx, input_weight_lbs=19000)
        complete_run(run["id"], cartons_produced=100, packed_weight_lbs=16150,
                     cull_weight_lbs=1900, juice_weight_lbs=950)
        assert refresh_lot(ctx["lot"]["id"])["status"] == "PACKED"

        validate_success(api.void_packing_run(run["id"], SUPERVISOR))
        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["status"] == "RELEASED", "positive balance reopens the lot"
        assert lot["weight_balance_lbs"] == pytest.approx(19000)
        assert lot["actual_packout_pct"] is None


class TestActualPackoutInputSet:
    def test_actual_packout_excludes_voided_runs(self, api):
        """PRD §3.4: "its `actual_packout_pct` is recomputed as a chronological
        aggregate over the lot's `COMPLETED`, non-`VOIDED` runs: one hundred times
        the summed `packed_weight_lbs` divided by the summed packed, cull, and
        juice weights across those runs, rounded half-up to one decimal place."
        PRD §3.4: "Runs in `SCHEDULED`, `CANCELLED`, or `VOIDED` status never
        enter the aggregate, which remains null until the lot's first
        completion."

        Design: Corner/calculations/c_actual_packout_excludes_voided_runs
        """
        ctx = setup_packable_lot(received_bin_count=20, received_weight_lbs=19000)
        run1 = schedule_run(ctx, input_weight_lbs=4000,
                            scheduled_start="2026-08-02T08:00:00Z",
                            scheduled_end="2026-08-02T12:00:00Z")
        complete_run(run1["id"], 20, 3400, 400, 200)
        run2 = schedule_run(ctx, input_weight_lbs=5000,
                            scheduled_start="2026-08-02T12:00:00Z",
                            scheduled_end="2026-08-02T16:00:00Z")
        complete_run(run2["id"], 25, 4000, 500, 500)

        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["actual_packout_pct"] == pytest.approx(82.2, abs=1e-6), (
            "7400 packed over 9000 total across both completions"
        )

        validate_success(api.void_packing_run(run2["id"], SUPERVISOR))
        lot = refresh_lot(ctx["lot"]["id"])
        assert lot["actual_packout_pct"] == pytest.approx(85.0, abs=1e-6), (
            "3400 / 4000 — the voided run leaves the input set"
        )
        assert lot["weight_balance_lbs"] == pytest.approx(15000)
