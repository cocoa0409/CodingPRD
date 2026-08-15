"""Cascading holds and compensating invariants: the supplier-suspend
three-link cascade, the batch hold/rework loop, and leaf-mass
conservation across allocation, auto-depletion, and cancellation.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    allocate,
    blend_batch,
    cancel_batch,
    create_active_recipe,
    create_batch,
    create_leaf_lot,
    create_packaging_line,
    create_released_lot,
    create_run,
    create_supplier,
    finalize_allocation,
    get_batch,
    get_lot,
    grade_lot,
    lock_recipe,
    release_batch,
    release_lot,
    single_component,
    submit_qc,
    submit_residue_test,
    validate_error,
    validate_paginated,
    validate_success,
)

PL = TEST_USERS["procurement_lead_headers"]
QA = TEST_USERS["qa_manager_headers"]
BM = TEST_USERS["blend_master_headers"]
PP = TEST_USERS["production_planner_headers"]


def _depth3_scenario():
    """Supplier with two RELEASED BLACK lots (100.0 + 50.0 kg); a
    CONVENTIONAL TEA_BAG batch (target 40.0, allocations 28.0 + 12.0)
    fully released; one SCHEDULED run on a TEA_BAG line."""
    supplier = create_supplier(name="Cascade Co", origin_region="Dibrugarh")
    lot1 = create_released_lot(supplier["id"], leaf_type="BLACK",
                               harvest_date="2026-01-15", weight_kg=100.0,
                               cost_per_kg_cents=1000, moisture_pct=5.0,
                               aroma_score=90, briskness_score=88,
                               appearance_score=92, measured_residue_ppm=0.30)
    lot2 = create_released_lot(supplier["id"], leaf_type="BLACK",
                               harvest_date="2026-01-16", weight_kg=50.0,
                               cost_per_kg_cents=1000, moisture_pct=5.0,
                               aroma_score=90, briskness_score=88,
                               appearance_score=92, measured_residue_ppm=0.30)
    recipe = create_active_recipe(
        name="R7", pack_format="TEA_BAG",
        components=[single_component("BLACK", "B", 100.0)])
    batch = create_batch(recipe["id"], 40.0)
    lock_recipe(batch["id"])
    allocate(batch["id"], lot1["id"], 28.0)
    allocate(batch["id"], lot2["id"], 12.0)
    finalize_allocation(batch["id"])
    blend_batch(batch["id"], measured_moisture_pct=5.5)
    submit_qc(batch["id"])
    release_batch(batch["id"])
    line = create_packaging_line(name="TB-1", line_type="TEA_BAG")
    run = create_run(line["id"], batch["id"], "2026-08-05T08:00:00Z",
                     "2026-08-05T10:00:00Z", 1000)
    return supplier, lot1, lot2, batch, line, run


class TestSupplierSuspendDepth3:
    def test_three_link_cascade_statuses(self, api):
        """PRD §2.8: "Link 1 is the lot hold: suspending a supplier moves
        every one of its lots in `GRADED`, `LAB_SUBMITTED`, or `RELEASED`
        to `ON_HOLD`, while lots in `REGISTERED`, `REJECTED`, or
        `DEPLETED` are left untouched."
        PRD §2.8: "Link 2 is the batch hold: every blend batch that holds
        an `ACTIVE` allocation from a lot that has just gone `ON_HOLD`,
        and that itself sits in `RECIPE_LOCKED`, `ALLOCATED`, `BLENDED`,
        `FLAVORED`, `QC_REVIEW`, or `RELEASED`, transitions to
        `ON_HOLD`."
        PRD §2.8: "Link 3 is the run cancellation: every production run
        still `SCHEDULED` that references a batch which has just gone
        `ON_HOLD` transitions to `CANCELLED`."

        Design: Difficulty/transitive_cascade/supplier_suspend_depth3_cascade
        """
        supplier, lot1, lot2, batch, _, run = _depth3_scenario()

        suspended = validate_success(api.suspend_supplier(supplier["id"], PL),
                                     200)
        assert suspended["status"] == "SUSPENDED"

        assert get_lot(lot1["id"])["status"] == "ON_HOLD", "link 1"
        assert get_lot(lot2["id"])["status"] == "ON_HOLD", "link 1"
        assert get_batch(batch["id"])["status"] == "ON_HOLD", (
            "link 2: held because its allocated lots were held")
        run_after = validate_success(api.get_run(run["id"], PP), 200)
        assert run_after["status"] == "CANCELLED", (
            "link 3: cancelled because its batch was held")

    def test_cascade_touches_increment_versions(self, api):
        """PRD §2.8: "Every entity touched by a cascade is genuinely
        mutated: its `updated_at` refreshes and its `version`
        increments."
        PRD §2.4: "`version` (integer): a system-managed counter that
        increments by one on every mutation — including mutations caused
        by the cascades of §2.8, which touch each affected entity in its
        own right."

        Design: Difficulty/transitive_cascade/supplier_suspend_depth3_cascade
        """
        supplier, lot1, lot2, batch, _, run = _depth3_scenario()
        before = {
            "supplier": validate_success(
                api.get_supplier(supplier["id"], PL), 200)["version"],
            "lot1": get_lot(lot1["id"])["version"],
            "lot2": get_lot(lot2["id"])["version"],
            "batch": get_batch(batch["id"])["version"],
            "run": validate_success(api.get_run(run["id"], PP), 200)["version"],
        }

        validate_success(api.suspend_supplier(supplier["id"], PL), 200)

        after = {
            "supplier": validate_success(
                api.get_supplier(supplier["id"], PL), 200)["version"],
            "lot1": get_lot(lot1["id"])["version"],
            "lot2": get_lot(lot2["id"])["version"],
            "batch": get_batch(batch["id"])["version"],
            "run": validate_success(api.get_run(run["id"], PP), 200)["version"],
        }
        for key in before:
            assert after[key] == before[key] + 1, (
                f"{key}: cascade mutation must increment version exactly once "
                f"({before[key]} -> {after[key]})")


def test_supplier_suspend_skips_terminal_lots(api):
    """PRD §2.8: "Link 1 is the lot hold: suspending a supplier moves
    every one of its lots in `GRADED`, `LAB_SUBMITTED`, or `RELEASED` to
    `ON_HOLD`, while lots in `REGISTERED`, `REJECTED`, or `DEPLETED` are
    left untouched."

    A REJECTED lot of the same supplier stays REJECTED; the RELEASED lot
    is held.

    Design: Corner/state_machines/supplier_suspend_skips_terminal_lots
    """
    supplier = create_supplier(name="Cond Co")
    lot_rejected = create_leaf_lot(supplier["id"], leaf_type="BLACK",
                                   harvest_date="2026-02-01")
    grade_lot(lot_rejected["id"], 50, 50, 50)  # composite 50.0 -> REJECT
    assert get_lot(lot_rejected["id"])["status"] == "REJECTED"
    lot_released = create_released_lot(supplier["id"], leaf_type="BLACK",
                                       harvest_date="2026-02-02")

    validate_success(api.suspend_supplier(supplier["id"], PL), 200)

    assert get_lot(lot_rejected["id"])["status"] == "REJECTED", (
        "terminal lots are untouched by the cascade")
    assert get_lot(lot_released["id"])["status"] == "ON_HOLD"


class TestBatchHoldReworkCycle:
    def _qc_scenario(self):
        """Supplier; GREEN lot 30.0 kg grade A RELEASED; CONVENTIONAL
        TEA_BAG recipe [{GREEN,C,100}]; batch target 20.0 in QC_REVIEW."""
        supplier = create_supplier(name="Ruhuna Co")
        lot = create_released_lot(supplier["id"], leaf_type="GREEN",
                                  harvest_date="2026-01-10", weight_kg=30.0,
                                  cost_per_kg_cents=700, moisture_pct=5.0,
                                  aroma_score=90, briskness_score=88,
                                  appearance_score=92)
        recipe = create_active_recipe(
            name="R6", pack_format="TEA_BAG",
            components=[single_component("GREEN", "C", 100.0)])
        batch = create_batch(recipe["id"], 20.0)
        lock_recipe(batch["id"])
        allocate(batch["id"], lot["id"], 20.0)
        finalize_allocation(batch["id"])
        blend_batch(batch["id"], measured_moisture_pct=6.0)
        in_qc = submit_qc(batch["id"])
        assert in_qc["status"] == "QC_REVIEW"
        return supplier, lot, recipe, batch

    def test_hold_rework_release_full_cycle(self, api):
        """PRD §3.5: "A held batch re-enters from `ON_HOLD` through the
        rework loop, which requires every lot referenced by the batch's
        `ACTIVE` allocations to be back in `RELEASED` or `DEPLETED`"
        PRD §3.2: "Should a problem surface after release, a `QAManager`
        recall moves a `RELEASED` lot back to `ON_HOLD` and again fires
        cascade links 2 and 3."
        PRD §2.8: "Reinstatement is never a bulk undo. Reinstating a
        supplier or a certificate performs no automatic un-hold: a held
        lot leaves `ON_HOLD` only through a fresh residue test that
        passes, and a held batch re-enters quality review only through
        the rework submission path described in §3.5."

        QC_REVIEW -> ON_HOLD (lot recall cascade) -> QC_REVIEW (rework
        re-submission after the lot re-clears) -> RELEASED.

        Design: Difficulty/non_linear_state_machine/blend_batch_hold_rework_cycle
        """
        _, lot, _, batch = self._qc_scenario()

        validate_success(api.recall_lot(lot["id"], QA), 200)
        assert get_batch(batch["id"])["status"] == "ON_HOLD", (
            "lot recall cascades the batch to ON_HOLD")

        submit_residue_test(lot["id"], measured_residue_ppm=0.25,
                            lab_name="LabB", test_method="HPLC")
        release_lot(lot["id"])
        assert get_lot(lot["id"])["status"] == "RELEASED"

        reworked = submit_qc(batch["id"])
        assert reworked["status"] == "QC_REVIEW", (
            "rework submit-qc re-enters QC_REVIEW once lots are RELEASED")
        released = release_batch(batch["id"])
        assert released["status"] == "RELEASED", "second release succeeds"

    def test_rework_rejected_while_lot_still_held(self, api):
        """PRD §3.5: "A held batch re-enters from `ON_HOLD` through the
        rework loop, which requires every lot referenced by the batch's
        `ACTIVE` allocations to be back in `RELEASED` or `DEPLETED`"
        PRD §2.10: "and otherwise with the generic `ERR_INVALID_STATE`."

        With the lot still ON_HOLD the rework door is closed.

        Design: Difficulty/non_linear_state_machine/blend_batch_hold_rework_cycle
        """
        _, lot, _, batch = self._qc_scenario()
        validate_success(api.recall_lot(lot["id"], QA), 200)
        assert get_batch(batch["id"])["status"] == "ON_HOLD"

        res = api.submit_qc(batch["id"], BM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_batch(batch["id"])["status"] == "ON_HOLD"


class TestLotMassConservation:
    def _mass_stage1(self):
        """Lots L1 60.0 kg and L2 40.0 kg BLACK RELEASED; CONVENTIONAL
        TEA_BAG recipe; batch1 target 20.0 allocated 20.0 from L1."""
        supplier = create_supplier(name="Mass Co", origin_region="Jorhat")
        lot1 = create_released_lot(supplier["id"], leaf_type="BLACK",
                                   harvest_date="2026-01-15", weight_kg=60.0,
                                   cost_per_kg_cents=1000)
        lot2 = create_released_lot(supplier["id"], leaf_type="BLACK",
                                   harvest_date="2026-01-16", weight_kg=40.0,
                                   cost_per_kg_cents=1000)
        recipe = create_active_recipe(
            name="R15", pack_format="TEA_BAG",
            components=[single_component("BLACK", "C", 100.0)])
        batch1 = create_batch(recipe["id"], 20.0)
        lock_recipe(batch1["id"])
        allocate(batch1["id"], lot1["id"], 20.0)
        return lot1, lot2, batch1

    def _mass_stage2(self, lot1, lot2, batch1):
        """batch2 target 80.0 allocated 40.0 (L1) + 40.0 (L2), draining
        both lots to exactly zero."""
        batch2 = create_batch(get_batch(batch1["id"])["recipe_id"], 80.0)
        lock_recipe(batch2["id"])
        allocate(batch2["id"], lot1["id"], 40.0)
        allocate(batch2["id"], lot2["id"], 40.0)
        return batch2

    def test_drain_deplete_and_cancel_restores(self, api):
        """PRD §3.1: "From then on `remaining_weight_kg` is a derived
        figure: the gross weight minus the kilograms committed across the
        lot's `ACTIVE` allocations."
        PRD §3.2: "Two lot transitions belong to the system alone: a
        `RELEASED` lot whose `remaining_weight_kg` reaches exactly zero
        after an allocation becomes `DEPLETED`, and a `DEPLETED` lot
        whose remaining weight climbs back above zero when a cancellation
        releases allocations returns to `RELEASED`."
        PRD §3.5: "From `RECIPE_LOCKED` onward the cancellation releases
        the batch's sourcing: every `ACTIVE` allocation flips to
        `RELEASED`, each lot's `remaining_weight_kg` is credited back by
        the drawn `allocated_kg`, and a `DEPLETED` lot whose restored
        weight exceeds zero returns to `RELEASED`."

        L1 drains 60 -> 40 -> 0 (auto-DEPLETED), then the batch1 cancel
        restores it to 20.0 and RELEASED — zero drift.

        Design: Difficulty/compensating_invariant/lot_mass_conservation_on_batch_cancel
        """
        lot1, lot2, batch1 = self._mass_stage1()

        after_first = get_lot(lot1["id"])
        assert after_first["remaining_weight_kg"] == pytest.approx(40.0), (
            "60.0 - 20.0")
        assert after_first["status"] == "RELEASED"

        self._mass_stage2(lot1, lot2, batch1)
        drained = get_lot(lot1["id"])
        assert drained["remaining_weight_kg"] == pytest.approx(0.0)
        assert drained["status"] == "DEPLETED", (
            "remaining hits exactly zero after the second allocation")

        cancelled = cancel_batch(batch1["id"])
        assert cancelled["status"] == "CANCELLED"

        restored = get_lot(lot1["id"])
        assert restored["remaining_weight_kg"] == pytest.approx(20.0)
        assert restored["status"] == "RELEASED", (
            "restored above zero, the lot returns to RELEASED")
        assert get_lot(lot2["id"])["status"] == "DEPLETED", (
            "batch2 and its allocations are untouched")

    def test_cancel_flips_only_own_allocations(self, api):
        """PRD §3.5: "every `ACTIVE` allocation flips to `RELEASED`"
        PRD §3.1: "the gross weight minus the kilograms committed across
        the lot's `ACTIVE` allocations"

        After batch1's cancel, its allocation reads RELEASED while
        batch2's allocation from the same lot stays ACTIVE, and the
        derived remainder equals 60.0 - 40.0 = 20.0.

        Design: Difficulty/compensating_invariant/lot_mass_conservation_on_batch_cancel
        """
        lot1, lot2, batch1 = self._mass_stage1()
        batch2 = self._mass_stage2(lot1, lot2, batch1)
        cancel_batch(batch1["id"])

        allocations, meta = validate_paginated(
            api.list_lot_allocations(lot1["id"], BM))
        assert meta["total_count"] == 2
        by_batch = {a["batch_id"]: a for a in allocations}
        assert by_batch[batch1["id"]]["status"] == "RELEASED"
        assert by_batch[batch2["id"]]["status"] == "ACTIVE"
        assert get_lot(lot1["id"])["remaining_weight_kg"] == pytest.approx(
            20.0), "invariant: remaining == weight - sum(ACTIVE allocations)"
