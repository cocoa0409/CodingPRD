"""Seed-lot quarantine, the inclusive germination threshold, sow-time seed
accounting, DEPLETED on exact depletion, and the supplier-recall failure
cascade (lot -> batch -> order line)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_germination_test,
    assert_seed_lot,
    create_approved_food_safety_plan,
    create_crop_plan,
    create_customer,
    create_listed_variety,
    create_released_seed_lot,
    create_seed_lot,
    create_standing_order,
    add_order_line,
    confirm_standing_order,
    expected_germination_rate,
    get_seed_lot,
    record_germination,
    setup_sown_batch,
    sow_crop_plan,
    start_germination_test,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import GROWER, OPS


class TestGerminationThreshold:
    def test_germination_rate_exactly_at_threshold_passes(self, api):
        """PRD §3.2: "the system computes `germination_rate` as the germinated
        count divided by the seeds sown, carried to four decimal places rounded
        half-up. A rate of at least 0.85 — the boundary is inclusive — sets the
        test's `result` to `PASS`; anything below 0.85 sets it to `FAIL`."
        PRD §3.2: "A `PASS` moves a `QUARANTINE` lot to `RELEASED`"

        Design: Difficulty/boundary_precision_check/germination_rate_inclusive_threshold
        """
        variety = create_listed_variety(name="Cilantro Edge")
        lot = create_seed_lot(variety["id"], seeds_on_hand_grams=300)
        test = start_germination_test(lot["id"], seeds_sown_count=100)
        recorded = validate_success(
            api.record_germination_result(test["id"], 85, GROWER))
        assert_germination_test(recorded)
        assert recorded["result"] == "PASS", "0.85 exactly is at least 0.85 (inclusive)"
        assert recorded["germination_rate"] == pytest.approx(
            expected_germination_rate(85, 100), abs=1e-9)
        assert recorded["germination_rate"] == pytest.approx(0.85, abs=1e-9)

        lot_after = validate_success(api.get_seed_lot(lot["id"], GROWER))
        assert lot_after["status"] == "RELEASED", "PASS moves QUARANTINE -> RELEASED"

    def test_germination_rate_above_and_below_threshold(self, api):
        """PRD §3.2: "A rate of at least 0.85 — the boundary is inclusive —
        sets the test's `result` to `PASS`; anything below 0.85 sets it to
        `FAIL`."
        PRD §3.2: "A `PASS` moves a `QUARANTINE` lot to `RELEASED`, and a
        re-test that passes on an already-`RELEASED` lot simply leaves it
        `RELEASED`. A `FAIL` moves a `QUARANTINE` lot to `BLOCKED`."

        Design: Difficulty/boundary_precision_check/germination_rate_inclusive_threshold
        """
        variety = create_listed_variety(name="Cilantro Pair")
        lot_pass = create_seed_lot(variety["id"], seeds_on_hand_grams=300)
        lot_fail = create_seed_lot(variety["id"], seeds_on_hand_grams=300)

        test_pass = start_germination_test(lot_pass["id"], seeds_sown_count=96)
        recorded_pass = validate_success(
            api.record_germination_result(test_pass["id"], 84, GROWER))
        assert recorded_pass["result"] == "PASS", "0.875 >= 0.85"
        assert recorded_pass["germination_rate"] == pytest.approx(0.875, abs=1e-9)
        assert get_seed_lot(lot_pass["id"])["status"] == "RELEASED"

        test_fail = start_germination_test(lot_fail["id"], seeds_sown_count=96)
        recorded_fail = validate_success(
            api.record_germination_result(test_fail["id"], 81, GROWER))
        assert recorded_fail["result"] == "FAIL", "0.8438 < 0.85"
        assert recorded_fail["germination_rate"] == pytest.approx(
            expected_germination_rate(81, 96), abs=1e-9)
        assert get_seed_lot(lot_fail["id"])["status"] == "BLOCKED", (
            "FAIL moves QUARANTINE -> BLOCKED")


class TestSowSeedConstraints:
    def test_sow_from_quarantine_lot_rejected(self, api):
        """PRD §3.3: "the named lot must be `RELEASED` — a lot in `QUARANTINE`,
        `BLOCKED`, or `DEPLETED` yields `ERR_SEED_LOT_NOT_RELEASED`"

        Design: Corner/errors/germination_result_fail_blocks_lot
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Celery")
        lot = create_seed_lot(variety["id"], seeds_on_hand_grams=500)
        assert lot["status"] == "QUARANTINE"
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=10)

        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"]},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_SEED_LOT_NOT_RELEASED)

    def test_sow_with_insufficient_seed_rejected(self, api):
        """PRD §3.3: "the plan's `seed_grams_required` must not exceed the
        lot's remaining `seeds_on_hand_grams`, else `ERR_INSUFFICIENT_SEED`"

        Design: Corner/errors/insufficient_seed_returns_error
        """
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Anise")
        lot = create_seed_lot(variety["id"], seeds_on_hand_grams=5)
        record_germination(lot["id"], 100, 95)  # RELEASED
        plan = create_crop_plan(variety["id"], planned_tray_count=2,
                                seed_grams_required=20)

        resp = api.sow_crop_plan(
            plan["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan["version"]},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SEED)


class TestSeedDepletion:
    def _setup_30g_lot(self):
        create_approved_food_safety_plan()
        variety = create_listed_variety(name="Beet")
        lot = create_released_seed_lot(variety["id"], seeds_on_hand_grams=30)
        plan1 = create_crop_plan(variety["id"], planned_tray_count=2,
                                 seed_grams_required=15)
        plan2 = create_crop_plan(variety["id"], planned_tray_count=2,
                                 seed_grams_required=15,
                                 planned_sow_date="2026-08-04")
        return variety, lot, plan1, plan2

    def test_sow_decrements_seed_and_zero_tips_lot_to_depleted(self, api):
        """PRD §3.3: "The lot's `seeds_on_hand_grams` is decremented by the
        plan's `seed_grams_required` (which may, as noted in §3.2, tip the lot
        into `DEPLETED`)."
        PRD §3.2: "`BLOCKED` is terminal, as is `DEPLETED`, which the system
        applies automatically when a sow draws a lot's `seeds_on_hand_grams`
        down to exactly zero."

        Design: Difficulty/compensating_invariant/sow_depletes_seed_and_lot_depletion_conserves_count
        """
        _, lot, plan1, plan2 = self._setup_30g_lot()

        sow_crop_plan(plan1["id"], plan1["version"], lot["id"])
        mid = get_seed_lot(lot["id"])
        assert_seed_lot(mid)
        assert mid["seeds_on_hand_grams"] == 15, (
            "30g minus a 15g sow leaves 15g; drawn seed is conserved")
        assert mid["status"] == "RELEASED"

        sow_crop_plan(plan2["id"], plan2["version"], lot["id"])
        final = get_seed_lot(lot["id"])
        assert final["seeds_on_hand_grams"] == 0, (
            "0 + (15 + 15) == 30: on-hand plus sown seed equals the received mass")
        assert final["status"] == "DEPLETED", (
            "A sow drawing seeds_on_hand_grams to exactly zero tips the lot to DEPLETED")

    def test_sow_from_depleted_lot_rejected_as_not_released(self, api):
        """PRD §3.3: "the named lot must be `RELEASED` — a lot in `QUARANTINE`,
        `BLOCKED`, or `DEPLETED` yields `ERR_SEED_LOT_NOT_RELEASED`"

        Design: Difficulty/compensating_invariant/sow_depletes_seed_and_lot_depletion_conserves_count
        """
        variety, lot, plan1, plan2 = self._setup_30g_lot()
        sow_crop_plan(plan1["id"], plan1["version"], lot["id"])
        sow_crop_plan(plan2["id"], plan2["version"], lot["id"])
        assert get_seed_lot(lot["id"])["status"] == "DEPLETED"

        plan3 = create_crop_plan(variety["id"], planned_tray_count=1,
                                 seed_grams_required=1,
                                 planned_sow_date="2026-08-05")
        resp = api.sow_crop_plan(
            plan3["id"],
            {"seed_lot_id": lot["id"],
             "expected_crop_plan_version": plan3["version"]},
            GROWER,
        )
        validate_error(resp, ApiErrorId.ERR_SEED_LOT_NOT_RELEASED)


class TestSeedLotBlockCascade:
    def _setup_growing_batch_with_order(self, api):
        """RELEASED lot with a GROWING batch, plus a CONFIRMED order holding a
        PLANNED line for the variety."""
        ws = setup_sown_batch(name="Radish", expected_yield_grams_per_tray=15000,
                              listed_price_cents_per_kg=700, planned_tray_count=4,
                              seed_grams_required=20)
        batch = ws["tray_batch"]
        validate_success(api.advance_tray_batch(batch["id"], GROWER))
        batch = validate_success(api.advance_tray_batch(batch["id"], GROWER))
        assert batch["status"] == "GROWING"
        ws["tray_batch"] = batch

        customer = create_customer(business_name="Catering")
        order = create_standing_order(customer)
        item = add_order_line(order["id"], customer, ws["variety"]["id"], 2.0)
        order = confirm_standing_order(order["id"], customer)
        ws.update({"customer": customer, "standing_order": order,
                   "order_item": item})
        return ws

    def _trigger_recall_fail(self, api, lot_id):
        """A re-test of the already-RELEASED lot that comes back FAIL."""
        test = start_germination_test(lot_id, seeds_sown_count=96)
        return api.record_germination_result(test["id"], 70, GROWER)

    def test_released_lot_retest_fail_blocks_lot_and_fails_batch(self, api):
        """PRD §3.2: "a `FAIL` recorded on a re-test of a lot that was already
        `RELEASED` — the supplier-recall case — also moves it to `BLOCKED`, and
        blocking a live lot triggers the failure cascade: every tray batch
        drawing from that lot whose status is `SOWN`, `GERMINATING`, or
        `GROWING` is transitioned to `FAILED`."

        Design: Difficulty/transitive_cascade/seed_lot_block_cascade_batch_plan_order_stop
        """
        ws = self._setup_growing_batch_with_order(api)
        assert ws["seed_lot"]["status"] == "RELEASED"

        resp = self._trigger_recall_fail(api, ws["seed_lot"]["id"])
        recorded = validate_success(resp)
        assert recorded["result"] == "FAIL"

        lot_after = validate_success(api.get_seed_lot(ws["seed_lot"]["id"], GROWER))
        assert lot_after["status"] == "BLOCKED", "RELEASED -> BLOCKED on recall FAIL"

        batch_after = validate_success(
            api.get_tray_batch(ws["tray_batch"]["id"], GROWER))
        assert batch_after["status"] == "FAILED", (
            "Cascade hop 1: the GROWING batch drawing from the blocked lot fails")

    def test_lot_block_cascade_marks_planned_order_line_shorted(self, api):
        """PRD §3.2: "For each failed batch, its crop plan recomputes the
        projected shortfall as the plan's `base_harvest_kg` minus the summed
        `harvested_kg` of its surviving batches, and that shortfall marks
        matching `PLANNED` order lines `SHORTED` through a fresh allocation
        pass of the kind described in §3.4."

        Design: Difficulty/transitive_cascade/seed_lot_block_cascade_batch_plan_order_stop
        """
        ws = self._setup_growing_batch_with_order(api)
        assert ws["order_item"]["fulfillment"] == "PLANNED"

        resp = self._trigger_recall_fail(api, ws["seed_lot"]["id"])
        validate_success(resp)

        item_after = validate_success(
            api.get_order_item(ws["order_item"]["id"], OPS))
        assert item_after["fulfillment"] == "SHORTED", (
            "Cascade hop 2: with no surviving supply, the PLANNED line is SHORTED")
