"""Allocation orders, the waterfall preview, and cut-and-wrap reconciliation
(over-fill guard, negative-gap guard, waste-tolerance boundary)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_allocation_order,
    create_allocation_order,
    create_cut_wrap_run,
    make_released_batch,
    reconcile_run,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

SALES = TEST_USERS["sales_planner_headers"]
CUTTER = TEST_USERS["cut_wrap_operator_headers"]


class TestAllocationPreview:
    def test_allocation_preview_waterfall_priority_then_created_at(self, api):
        """PRD §3.8: "The candidate set is the batch's orders in `OPEN` or
        `PARTIALLY_FILLED`; they are ranked by `priority` ascending, ties
        broken by `created_at` ascending — earliest order first, never by
        identifier."
        PRD §3.8: "The preview returns `order_sequence`, the candidate order
        identifiers in ranking order, and `wheels_allocated`, the wheels each
        would receive; a batch with no candidate orders yields an empty
        preview, not an error."

        Design: Corner/calculations/allocation_preview_waterfall_priority_then_created_at
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
        )
        order_a = create_allocation_order(
            ctx["batch_id"], channel="PRIVATE_LABEL", customer_name="First-Created",
            wheels_requested=3, priority=2,
        )
        order_b = create_allocation_order(
            ctx["batch_id"], channel="BRANDED", customer_name="Second-Created",
            wheels_requested=3, priority=1,
        )
        preview = validate_success(
            api.allocation_preview(ctx["batch_id"], SALES)
        )
        assert preview["order_sequence"] == [order_b["id"], order_a["id"]], (
            f"priority 1 must outrank priority 2 regardless of creation order, "
            f"got {preview['order_sequence']}"
        )
        assert len(preview["wheels_allocated"]) == 2

    def test_computed_read_batch_allocation_preview_empty_pool(self, api):
        """PRD §3.8: "The preview returns `order_sequence`, the candidate order
        identifiers in ranking order, and `wheels_allocated`, the wheels each
        would receive; a batch with no candidate orders yields an empty
        preview, not an error."

        Design: Corner/endpoints/computed_read_batch_allocation_preview_empty_pool
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
        )
        preview = validate_success(api.allocation_preview(ctx["batch_id"], SALES))
        assert preview["order_sequence"] == [], (
            f"an empty candidate pool yields an empty preview, got {preview}"
        )
        assert preview["wheels_allocated"] == []


class TestOrderCancelGuard:
    def test_allocation_order_cancel_blocked_after_cuts(self, api):
        """PRD §3.8: "Cancelling an order is permitted only while nothing has
        been cut against it: a `wheels_cut` above zero fails with
        `ERR_ORDER_HAS_CUTS`, and a clean cancel moves the order `OPEN` →
        terminal `CANCELLED`."

        Design: Corner/state_machines/allocation_order_cancel_blocked_after_cuts
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
        )
        order = create_allocation_order(
            ctx["batch_id"], channel="BRANDED", customer_name="House",
            wheels_requested=2, priority=1,
        )
        run = create_cut_wrap_run(
            order["id"], wheels_in=1, finished_case_weight_kg=2.7, trim_waste_kg=0.25
        )
        reconcile_run(run["id"])
        order_now = validate_success(api.get_allocation_order(order["id"], SALES))
        assert order_now["status"] == "PARTIALLY_FILLED"
        assert order_now["wheels_cut"] == 1
        resp = api.cancel_allocation_order(order["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_CUTS, 409)
        order_after = validate_success(api.get_allocation_order(order["id"], SALES))
        assert order_after["status"] == "PARTIALLY_FILLED", (
            "a blocked cancel leaves the order unchanged"
        )


class TestCutWrapReconcileGates:
    def test_cut_wrap_overfill_guard(self, api):
        """PRD §3.8: "The run must not over-fill its order: `wheels_cut` plus
        `wheels_in` must not exceed `wheels_requested`, failing
        `ERR_ORDER_OVERFILL`, with an exact fill permitted."

        Design: Corner/endpoints/cut_wrap_overfill_guard
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
        )
        order = create_allocation_order(
            ctx["batch_id"], channel="BRANDED", customer_name="House",
            wheels_requested=3, priority=1,
        )
        run1 = create_cut_wrap_run(
            order["id"], wheels_in=2, finished_case_weight_kg=5.4, trim_waste_kg=0.5
        )
        reconcile_run(run1["id"])
        run2 = create_cut_wrap_run(
            order["id"], wheels_in=2, finished_case_weight_kg=5.4, trim_waste_kg=0.5
        )
        resp = api.reconcile_cut_wrap_run(run2["id"], CUTTER)
        validate_error(resp, ApiErrorId.ERR_ORDER_OVERFILL, 422)
        order_now = validate_success(api.get_allocation_order(order["id"], SALES))
        assert order_now["wheels_cut"] == 2, "a rejected reconcile posts nothing"

    def test_waste_gap_exactly_2pct_passes_reconcile(self, api):
        """PRD §3.8: "And the gap must fit the waste tolerance: a gap strictly
        greater than two percent of the run's `input_weight_kg` fails with
        `ERR_WASTE_TOLERANCE`, while a gap exactly equal to two percent of the
        input passes."

        Design: Difficulty/boundary_precision_check/waste_gap_exactly_2pct_passes_reconcile
        """
        ctx = make_released_batch(
            variety="CHEDDAR", wheels_produced=20, green_weight_kg=1000.0,
            volume_liters=10000.0, liters_committed=10000.0,
            age_to="2026-10-01T00:00:00Z",
            grade_readings={
                "moisture_pct": 36.0, "fat_dry_basis_pct": 52.0,
                "body_score": 9, "flavor_score": 9,
            },
        )
        order_ok = create_allocation_order(
            ctx["batch_id"], channel="BRANDED", customer_name="House Brand",
            wheels_requested=10, priority=1,
        )
        order_bad = create_allocation_order(
            ctx["batch_id"], channel="PRIVATE_LABEL", customer_name="Acme",
            wheels_requested=10, priority=2,
        )
        # CHEDDAR wheel weight 18.0: 10 wheels -> input 180.0 kg.
        run_ok = create_cut_wrap_run(
            order_ok["id"], wheels_in=10, finished_case_weight_kg=150.0,
            trim_waste_kg=26.4,
        )
        run_bad = create_cut_wrap_run(
            order_bad["id"], wheels_in=10, finished_case_weight_kg=150.0,
            trim_waste_kg=26.0,
        )
        ok_data = validate_success(api.reconcile_cut_wrap_run(run_ok["id"], CUTTER))
        assert ok_data["status"] == "RECONCILED", (
            "gap 3.6 kg is exactly 2% of the 180.0 kg input and must pass"
        )
        bad_resp = api.reconcile_cut_wrap_run(run_bad["id"], CUTTER)
        validate_error(bad_resp, ApiErrorId.ERR_WASTE_TOLERANCE, 422)

    def test_waste_gap_over_2pct_rejected(self, api):
        """PRD §3.8: "And the gap must fit the waste tolerance: a gap strictly
        greater than two percent of the run's `input_weight_kg` fails with
        `ERR_WASTE_TOLERANCE`, while a gap exactly equal to two percent of the
        input passes. The comparison is made against the tolerance computed
        from the exact, unrounded input weight."

        Design: Difficulty/boundary_precision_check/waste_gap_exactly_2pct_passes_reconcile
        """
        ctx = make_released_batch(
            variety="MUENSTER", wheels_produced=4, green_weight_kg=500.0,
            age_to="2026-08-25T00:00:00Z",
        )
        order = create_allocation_order(
            ctx["batch_id"], channel="PRIVATE_LABEL", customer_name="Acme",
            wheels_requested=4, priority=1,
        )
        # MUENSTER wheel weight 3.0: 4 wheels -> input 12.0 kg; tolerance 0.24.
        run = create_cut_wrap_run(
            order["id"], wheels_in=4, finished_case_weight_kg=11.0, trim_waste_kg=0.75
        )
        resp = api.reconcile_cut_wrap_run(run["id"], CUTTER)
        validate_error(resp, ApiErrorId.ERR_WASTE_TOLERANCE, 422)
        run_now = validate_success(api.get_cut_wrap_run(run["id"], CUTTER))
        assert run_now["status"] == "DRAFT", "a rejected reconcile leaves the run DRAFT"

    def test_waste_negative_gap_rejected(self, api):
        """PRD §3.8: "The gap must not be negative — outputs exceeding inputs
        fail with `ERR_WASTE_NEGATIVE`."

        Design: Corner/validations/waste_negative_gap_rejected
        """
        ctx = make_released_batch(
            variety="CHEDDAR", wheels_produced=10, green_weight_kg=1000.0,
            volume_liters=10000.0, liters_committed=10000.0,
            age_to="2026-10-01T00:00:00Z",
            grade_readings={
                "moisture_pct": 36.0, "fat_dry_basis_pct": 52.0,
                "body_score": 9, "flavor_score": 9,
            },
        )
        order = create_allocation_order(
            ctx["batch_id"], channel="BRANDED", customer_name="House",
            wheels_requested=10, priority=1,
        )
        # input 180.0 - finished 150.0 - trim 31.0 = -1.0: outputs exceed inputs.
        run = create_cut_wrap_run(
            order["id"], wheels_in=10, finished_case_weight_kg=150.0, trim_waste_kg=31.0
        )
        resp = api.reconcile_cut_wrap_run(run["id"], CUTTER)
        validate_error(resp, ApiErrorId.ERR_WASTE_NEGATIVE, 422)
        run_now = validate_success(api.get_cut_wrap_run(run["id"], CUTTER))
        assert run_now["status"] == "DRAFT"
