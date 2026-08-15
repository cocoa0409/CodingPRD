"""Run completion: cut plan, regrind spawn, close-out invoicing (PRD §3.7, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_quality_inspector_headers,
    running_scene, closed_order_scene, cascade_scene,
    complete_run, get_run, get_order, get_die, get_lot, get_batch,
    get_assignment, get_line, assert_amortization_invariant,
)

LO = TEST_USERS["line_operator_headers"]
PM = TEST_USERS["plant_manager_headers"]
SE = TEST_USERS["sales_engineer_headers"]
QI = TEST_USERS["quality_inspector_headers"]


class TestBundleCutPlan:
    def test_exact_piece_boundary_single_loose_bundle(self, api):
        """PRD §3.7: "the piece count is the floor of `good_length_mm` divided by
        the order's `cut_length_mm`; the full-bundle count is the floor of the
        piece count divided by `pieces_per_bundle`; the loose pieces are what
        remain after the full bundles; and `remnant_mm`, the uncut remainder, is
        `good_length_mm` minus the piece count times `cut_length_mm`."
        PRD §3.7: "One **cut bundle** row is written per full bundle,
        `bundle_seq` counting upward from one, each row carrying `pieces` equal
        to the order's `pieces_per_bundle` and `partial` false; when loose pieces
        remain, one further row with the next `bundle_seq` carries the loose
        count with `partial` true."

        Design: Difficulty/boundary_precision_check/bundle_exact_piece_boundary
        """
        scene = running_scene()
        # floor(2000 / 2000) = 1 piece -> 0 full bundles + 1 loose-piece row.
        completed = complete_run(scene["run"]["id"], 2000, 1.5, 0)
        assert completed["remnant_mm"] == 0
        bundles, meta = validate_paginated(api.list_bundles(scene["run"]["id"], LO))
        assert meta["total_count"] == 1
        assert bundles[0]["pieces"] == 1
        assert bundles[0]["partial"] is True
        assert bundles[0]["bundle_seq"] == 1
        assert bundles[0]["total_length_mm"] == 2000

    def test_below_one_piece_yields_empty_bundle_set(self, api):
        """PRD §3.7: "the piece count is the floor of `good_length_mm` divided by
        the order's `cut_length_mm`; the full-bundle count is the floor of the
        piece count divided by `pieces_per_bundle`; the loose pieces are what
        remain after the full bundles; and `remnant_mm`, the uncut remainder, is
        `good_length_mm` minus the piece count times `cut_length_mm`."
        PRD §3.7: "One **cut bundle** row is written per full bundle,
        `bundle_seq` counting upward from one, each row carrying `pieces` equal
        to the order's `pieces_per_bundle` and `partial` false; when loose pieces
        remain, one further row with the next `bundle_seq` carries the loose
        count with `partial` true."

        Design: Difficulty/boundary_precision_check/bundle_exact_piece_boundary
        """
        scene = running_scene()
        # floor(1999 / 2000) = 0 pieces -> no rows at all (loose_pieces == 0).
        completed = complete_run(scene["run"]["id"], 1999, 1.4, 0)
        assert completed["remnant_mm"] == 1999
        bundles, meta = validate_paginated(api.list_bundles(scene["run"]["id"], LO))
        assert meta["total_count"] == 0
        assert bundles == []

    def test_full_bundles_without_partial_row(self, api):
        """PRD §3.7: "the piece count is the floor of `good_length_mm` divided by
        the order's `cut_length_mm`; the full-bundle count is the floor of the
        piece count divided by `pieces_per_bundle`; the loose pieces are what
        remain after the full bundles; and `remnant_mm`, the uncut remainder, is
        `good_length_mm` minus the piece count times `cut_length_mm`."
        PRD §3.7: "One **cut bundle** row is written per full bundle,
        `bundle_seq` counting upward from one, each row carrying `pieces` equal
        to the order's `pieces_per_bundle` and `partial` false; when loose pieces
        remain, one further row with the next `bundle_seq` carries the loose
        count with `partial` true."

        Design: Corner/calculations/bundle_remnant_and_full_bundles
        """
        scene = running_scene(samples=2, order_over={"ordered_length_m": 6000})
        # quota floor(4500.5 / 2000) = 2 samples (already posted)
        completed = complete_run(scene["run"]["id"], 4500500, 3400, 0)
        # pieces = floor(4500500/2000) = 2250; bundles = floor(2250/25) = 90; loose 0.
        assert completed["remnant_mm"] == 500
        bundles, meta = validate_paginated(
            api.list_bundles(scene["run"]["id"], LO, params={"limit": 100}))
        assert meta["total_count"] == 90
        assert all(b["pieces"] == 25 and b["partial"] is False for b in bundles)
        seqs = [b["bundle_seq"] for b in bundles]
        assert seqs == sorted(seqs), "bundle listing must be ordered by bundle_seq ascending"
        assert bundles[-1]["bundle_seq"] == 90
        for b in bundles:
            assert b["total_length_mm"] == 25 * 2000
        wo = get_order(scene["wo"]["id"])
        assert wo["produced_good_length_m"] == pytest.approx(4500.5, abs=0.001)
        assert wo["status"] == "IN_PRODUCTION", "4500.5 m < 6000 m ordered: not yet closed"


class TestRegrindSpawn:
    def test_trim_scrap_spawns_inhouse_regrind_lot(self, api):
        """PRD §3.7: "when `trim_scrap_kg` is greater than zero, the system
        spawns a new resin lot — `lot_kind` `REGRIND`, its `resin_type` and
        `color_family` taken from the work order's formulation, `received_kg`
        equal to `trim_scrap_kg`, a `supplier_lot_ref` of `INHOUSE-` followed by
        the run's identifier, and status `QC_PASSED`, ready to feed future
        blends — and stores the new lot's identifier on the run's
        `regrind_lot_id`; when `trim_scrap_kg` is zero, `regrind_lot_id` stays
        unset."

        Design: Corner/cross_cutting_complexity_layers/regrind_lot_spawned_on_complete
        """
        scene = running_scene(samples=2)
        completed = complete_run(scene["run"]["id"], 4000000, 3000, 50)
        regrind_lot_id = completed.get("regrind_lot_id")
        assert regrind_lot_id, "trim_scrap_kg 50 > 0 must spawn a regrind lot"
        lot = get_lot(regrind_lot_id)
        assert lot["lot_kind"] == "REGRIND"
        assert lot["resin_type"] == "PVC"
        assert lot["color_family"] == "RED"
        assert lot["received_kg"] == pytest.approx(50, abs=0.001)
        assert lot["status"] == "QC_PASSED"
        assert lot["supplier_lot_ref"] == f"INHOUSE-{scene['run']['id']}"


class TestBatchQuarantineCascade:
    def test_consumed_batch_quarantine_holds_run_and_downs_line(self, api):
        """PRD §3.3: "Against a `CONSUMED` batch it is lawful only while the
        production run consuming the batch is `RUNNING` or `HOLD` — otherwise
        `ERR_INVALID_STATE` — and because the material is already in the extruder
        there is no lot credit-back; instead the quarantine fires a four-link
        cascade: the batch's `pre_quarantine_status` becomes `CONSUMED`, the
        consuming run is moved from `RUNNING` to `HOLD` with `hold_origin`
        `SYSTEM`, that run's line drops from `RUNNING` to `DOWN`, and every
        assignment still `SCHEDULED` on that line is `CANCELLED`, with each
        affected order reverted from `SCHEDULED` to `CONFIRMED` wherever the
        order has no remaining `SCHEDULED` or `ACTIVE` assignments and no
        `COMPLETED` runs."

        Design: Difficulty/transitive_cascade/batch_quarantine_cascade
        """
        scene = cascade_scene()
        insp1 = make_quality_inspector_headers("insp-1")
        batch = validate_success(
            api.qc_blend_batch(scene["batch"]["id"], {"action": "QUARANTINE"}, insp1), 200)
        assert batch["status"] == "QUARANTINED"
        assert batch["pre_quarantine_status"] == "CONSUMED"
        run = get_run(scene["run1"]["id"])
        assert run["status"] == "HOLD"
        assert run["hold_origin"] == "SYSTEM"
        assert get_line(scene["line"]["id"])["status"] == "DOWN"

    def test_consumed_batch_quarantine_cancels_assignments_without_credit_back(self, api):
        """PRD §3.3: "Against a `CONSUMED` batch it is lawful only while the
        production run consuming the batch is `RUNNING` or `HOLD` — otherwise
        `ERR_INVALID_STATE` — and because the material is already in the extruder
        there is no lot credit-back; instead the quarantine fires a four-link
        cascade: the batch's `pre_quarantine_status` becomes `CONSUMED`, the
        consuming run is moved from `RUNNING` to `HOLD` with `hold_origin`
        `SYSTEM`, that run's line drops from `RUNNING` to `DOWN`, and every
        assignment still `SCHEDULED` on that line is `CANCELLED`, with each
        affected order reverted from `SCHEDULED` to `CONFIRMED` wherever the
        order has no remaining `SCHEDULED` or `ACTIVE` assignments and no
        `COMPLETED` runs."

        Design: Difficulty/transitive_cascade/batch_quarantine_cascade
        """
        scene = cascade_scene()
        insp1 = make_quality_inspector_headers("insp-1")
        validate_success(
            api.qc_blend_batch(scene["batch"]["id"], {"action": "QUARANTINE"}, insp1), 200)
        assert get_assignment(scene["asg2"]["id"])["status"] == "CANCELLED"
        assert get_order(scene["wo2"]["id"])["status"] == "CONFIRMED"
        # No lot credit-back for a CONSUMED quarantine: virgin draw 961.5 stays.
        # cascade_scene blends without a regrind lot: colorant 38.5 kg,
        # regrind 0 (no lot supplied), so virgin = 1000 - 38.5 = 961.5 kg.
        assert get_lot(scene["lot_v"]["id"])["consumed_kg"] == pytest.approx(961.5, abs=0.001)


class TestCloseoutInvoicing:
    def test_invoice_bills_actual_metres_plus_capped_surcharge(self, api):
        """PRD §3.8: "First, `billed_length_m` is fixed as the sum of
        `good_length_mm` divided by one thousand across all `COMPLETED` runs of
        the order's assignments, whatever status those assignments ended in."
        PRD §3.8: "Fourth, the tooling surcharge is the smaller of the die's
        current `remaining_balance_cents` and ten percent of the product charge
        rounded half-up to whole cents — so the surcharge can finish off a die's
        balance but can never overrun it."
        PRD §3.8: "Fifth, `invoice_total_cents` is the product charge plus the
        surcharge."

        Design: Difficulty/combinatorial_formula/invoice_pinned_evaluation_order
        """
        scene = closed_order_scene()
        resp = api.invoice_work_order(scene["wo"]["id"], PM)
        invoiced = validate_success(resp, 200)
        assert invoiced["billed_length_m"] == pytest.approx(8000, abs=0.001), (
            "Two completed runs x 4000 m are billed, not the 5000 m ordered")
        # product = 8000 x 1000.00 = 8,000,000; surcharge = min(100000, 800000) = 100000.
        assert invoiced["invoice_total_cents"] == 8100000
        assert invoiced["billing_status"] == "INVOICED"
        assert invoiced["status"] == "CLOSED"

    def test_invoice_surcharge_completes_die_amortization(self, api):
        """PRD §3.8: "Finally, the surcharge is credited to the die — added to
        `amortized_cents`, subtracted from `remaining_balance_cents` —
        preserving the amortization invariant of §2.9, the order's
        `billing_status` moves to `INVOICED`, and the order's `version`
        increments by one."

        Design: Difficulty/combinatorial_formula/invoice_pinned_evaluation_order
        """
        scene = closed_order_scene()
        die_before = get_die(scene["die"]["id"])
        assert die_before["amortized_cents"] == 400000  # two run credits of 200000
        assert die_before["remaining_balance_cents"] == 100000

        validate_success(api.invoice_work_order(scene["wo"]["id"], PM), 200)
        die_after = get_die(scene["die"]["id"])
        assert die_after["amortized_cents"] == 500000
        assert die_after["remaining_balance_cents"] == 0, (
            "Surcharge capped at remaining balance: min(100000, 800000)")
        assert_amortization_invariant(die_after)


class TestParallelStatusDimensions:
    def test_cancel_on_closed_order_rejected(self, api):
        """PRD §3.4: "Cancellation, also by a `SalesEngineer`, is available from
        `QUOTED`, `CONFIRMED`, `SCHEDULED`, or `IN_PRODUCTION` — from anywhere
        else, `ERR_INVALID_STATE` — but is blocked whenever any production run
        under the order's assignments is `RUNNING` or `HOLD`, surfacing
        `ERR_RUN_IN_PROGRESS`."
        PRD §3.8: "The order carries two independent status dimensions from
        creation onward: the production `status` narrated so far, and a
        `billing_status` that moves exactly once, from `UNBILLED` to `INVOICED`."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions
        """
        scene = closed_order_scene()
        assert scene["wo"]["status"] == "CLOSED"
        assert scene["wo"]["billing_status"] == "UNBILLED"
        resp = api.cancel_work_order(scene["wo"]["id"], SE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(scene["wo"]["id"])["status"] == "CLOSED"

    def test_invoice_advances_billing_on_closed_order(self, api):
        """PRD §3.8: "The order carries two independent status dimensions from
        creation onward: the production `status` narrated so far, and a
        `billing_status` that moves exactly once, from `UNBILLED` to `INVOICED`."
        PRD §3.8: "Invoicing is a `PlantManager` act, lawful only when production
        has ended — the order's `status` is `CLOSED` — and the order is still
        `UNBILLED`; an invoice attempt in any other combination is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions
        """
        scene = closed_order_scene()
        validate_error(api.cancel_work_order(scene["wo"]["id"], SE), ApiErrorId.ERR_INVALID_STATE)
        invoiced = validate_success(api.invoice_work_order(scene["wo"]["id"], PM), 200)
        assert invoiced["billing_status"] == "INVOICED"
        assert invoiced["status"] == "CLOSED", "Invoicing must not touch the production dimension"
        assert invoiced["invoice_total_cents"] == 8100000
