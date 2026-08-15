"""Sand reclamation ledger: per-event rounding, RECLAIMING re-test, the
quarantine cascade, and the sand-mass invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_sand_mass_invariant,
    book_slot,
    cool_and_shakeout,
    create_mold,
    get_mold,
    get_order,
    get_pour_slot,
    get_sand_batch,
    pour_molds,
    setup_shop,
    validate_error,
    validate_success,
)

LINE = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["qi_1_headers"]


class TestSandMassInvariant:
    def _setup_shaken_out_mold(self, api, mold_sand_kg=120):
        """Batch IN_SERVICE with one poured + shaken-out mold (spent sand)."""
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": mold_sand_kg, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=1000)
        cool_and_shakeout(ctx)
        return ctx

    def test_shakeout_moves_committed_to_spent(self, api):
        """PRD §3.6: "a `LineOperator` shakes out a `COOLED` mold, moving its
        `sand_weight_kg` in the batch ledger from `committed_weight_kg` to
        `spent_weight_kg`" and PRD §2.8: "`virgin_weight_kg` always equals the
        sum of `current_weight_kg`, `committed_weight_kg`, `spent_weight_kg`,
        `pending_reclaim_kg`, and `discarded_weight_kg`."

        Design: Difficulty/compensating_invariant/sand_mass_conserved_across_commit_reclaim_discard
        """
        ctx = self._setup_shaken_out_mold(api)
        batch = get_sand_batch(ctx["batch"]["id"])
        assert batch["current_weight_kg"] == pytest.approx(880.0, abs=1e-9)
        assert batch["committed_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert batch["spent_weight_kg"] == pytest.approx(120.0, abs=1e-9)
        assert_sand_mass_invariant(batch)

    def test_reclaim_and_passing_test_conserve_sand(self, api):
        """PRD §3.8: "A valid reclaim moves the batch `IN_SERVICE → RECLAIMING`,
        sets `pending_reclaim_kg` to the reclaimed figure, adds the loss to
        `discarded_weight_kg`, and zeroes `spent_weight_kg`." and "A passing
        reading returns the pending sand to service: `current_weight_kg` grows
        by `pending_reclaim_kg`, `pending_reclaim_kg` zeroes, `last_loi_pct` is
        recorded, the batch is `IN_SERVICE` again, and `posture` is recomputed."

        Design: Difficulty/compensating_invariant/sand_mass_conserved_across_commit_reclaim_discard
        """
        ctx = self._setup_shaken_out_mold(api)
        batch_id = ctx["batch"]["id"]
        # 110.0 + 10.0 == 120.0 spent: mass balance holds exactly.
        reclaiming = validate_success(api.reclaim_sand_batch(
            batch_id, {"reclaimed_weight_kg": 110.0, "loss_weight_kg": 10.0}, LINE))
        assert reclaiming["status"] == "RECLAIMING"
        assert reclaiming["spent_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert reclaiming["pending_reclaim_kg"] == pytest.approx(110.0, abs=1e-9)
        assert reclaiming["discarded_weight_kg"] == pytest.approx(10.0, abs=1e-9)

        back = validate_success(api.test_sand_batch(batch_id, {"loi_pct": 2.0}, QI))
        assert back["status"] == "IN_SERVICE"
        assert back["current_weight_kg"] == pytest.approx(990.0, abs=1e-9)
        assert back["pending_reclaim_kg"] == pytest.approx(0.0, abs=1e-9)
        # 1000 == 990.0 current + 0 committed + 0 spent + 0 pending + 10.0 discarded
        assert_sand_mass_invariant(back)


class TestReclaimRoundingPinned:
    def test_sand_reclaim_per_event_rounding_pinned(self, api):
        """PRD §3.8: "The two figures must account for the spent sand exactly —
        their sum must equal `spent_weight_kg`, or the attempt is
        `ERR_SAND_MASS_MISMATCH` (HTTP 422) — and each is rounded half-up to a
        tenth of a kilogram before it touches any accumulator. This per-event
        rounding order is pinned and is not sum-then-round: three reclaim events
        of 33.35 kilograms each credit 100.2 kilograms in total (three times
        33.4), not 100.1."

        Design: Corner/calculations/sand_reclaim_per_event_rounding_pinned
        """
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": 66.7, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=1000)
        cool_and_shakeout(ctx)
        batch_id = ctx["batch"]["id"]
        assert get_sand_batch(batch_id)["spent_weight_kg"] == pytest.approx(
            66.7, abs=1e-9)

        # Per-event rounding first: 33.35 -> 33.4 twice, 33.4 + 33.4 = 66.8 != 66.7.
        res = api.reclaim_sand_batch(
            batch_id, {"reclaimed_weight_kg": 33.35, "loss_weight_kg": 33.35}, LINE)
        validate_error(res, "ERR_SAND_MASS_MISMATCH", expected_status=422)

        # 33.3 + 33.4 == 66.7 balances exactly after per-event rounding.
        accepted = validate_success(api.reclaim_sand_batch(
            batch_id, {"reclaimed_weight_kg": 33.3, "loss_weight_kg": 33.4}, LINE))
        assert accepted["status"] == "RECLAIMING"
        assert accepted["pending_reclaim_kg"] == pytest.approx(33.3, abs=1e-9)
        assert accepted["discarded_weight_kg"] == pytest.approx(33.4, abs=1e-9)


class TestQuarantineCascade:
    def _setup_quarantine(self, api):
        """Batch with mold1 poured + shaken out (spent 120) and mold2 ASSEMBLED
        (committed 50) on a future BOOKED slot; batch moved to RECLAIMING."""
        ctx = setup_shop(order_quantity=4)
        pour_molds(ctx, [{"sand_weight_kg": 120, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=1000)
        cool_and_shakeout(ctx)
        mold2 = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                            ctx["order"]["id"], sand_weight_kg=50,
                            metal_weight_kg=200, cooling_hours=2)
        slot2 = book_slot(ctx["line"]["id"], ctx["heat"]["id"], [mold2["id"]],
                          "2026-08-11T09:00:00Z", "2026-08-11T10:00:00Z")
        # 100.0 + 20.0 == 120.0 spent.
        validate_success(api.reclaim_sand_batch(
            ctx["batch"]["id"],
            {"reclaimed_weight_kg": 100.0, "loss_weight_kg": 20.0}, LINE))
        ctx["mold2"] = mold2
        ctx["slot2"] = slot2
        return ctx

    def test_quarantine_discards_batch_and_scraps_assembled_mold(self, api):
        """PRD §3.8: "A failing reading is the foundry's worst sand event: the
        batch is `DISCARDED`, and `current_weight_kg`, `pending_reclaim_kg`, and
        `committed_weight_kg` are all zeroed into `discarded_weight_kg`." and
        "every mold whose `sand_batch_id` is the failed batch and whose status
        is `ASSEMBLED` is scrapped (`ASSEMBLED → SCRAPPED`)".

        Design: Difficulty/transitive_cascade/sand_quarantine_cascade_depth3
        """
        ctx = self._setup_quarantine(api)
        # LOI 5.0 > max 3.0 while RECLAIMING.
        failed = validate_success(api.test_sand_batch(
            ctx["batch"]["id"], {"loi_pct": 5.0}, QI))
        assert failed["status"] == "DISCARDED"
        # 20.0 prior loss + 830.0 current + 100.0 pending + 50.0 committed.
        assert failed["discarded_weight_kg"] == pytest.approx(1000.0, abs=1e-9)
        assert failed["current_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert failed["pending_reclaim_kg"] == pytest.approx(0.0, abs=1e-9)
        assert failed["committed_weight_kg"] == pytest.approx(0.0, abs=1e-9)
        assert_sand_mass_invariant(failed)

        mold2 = get_mold(ctx["mold2"]["id"])
        assert mold2["status"] == "SCRAPPED"
        assert mold2["pour_slot_id"] is None

    def test_quarantine_cancels_booked_slot_and_recomputes_pipeline(self, api):
        """PRD §3.8: "each such mold's `BOOKED` pour slot is cancelled and its
        remaining `ASSEMBLED` molds' `pour_slot_id` links are cleared; and each
        affected order's `pipeline_count` is recomputed with the scrapped molds
        excluded, after which the foundry `posture` is recomputed."

        Design: Difficulty/transitive_cascade/sand_quarantine_cascade_depth3
        """
        ctx = self._setup_quarantine(api)
        validate_success(api.test_sand_batch(
            ctx["batch"]["id"], {"loi_pct": 5.0}, QI))
        # The cascade (not a client cancel) drove the slot to CANCELLED.
        assert get_pour_slot(ctx["slot2"]["id"])["status"] == "CANCELLED"
        # mold1 (impressions 1) still counts; scrapped mold2 is excluded.
        assert get_order(ctx["order"]["id"])["pipeline_count"] == 1
