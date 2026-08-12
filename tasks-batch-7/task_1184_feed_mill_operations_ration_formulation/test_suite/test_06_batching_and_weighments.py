"""Weighment recording: per-event rounding, mix tolerance boundary, weighment
domain errors, and immediate consistency (PRD §2.4, §2.7, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_operator_headers,
    assert_weighment,
    setup_batching_batch, setup_confirmed_order, setup_mixed_batch,
    record_weighment, mix_batch, make_ingredient, make_stocked_bin,
    make_employee, make_line, make_batch, start_batch,
)

MM = TEST_USERS["mill_manager_headers"]


class TestPerWeighmentRounding:
    def _rounding_setup(self, api):
        """0.1t order CONFIRMED; batch target 0.1t BATCHING (line targets:
        corn 0.070t, SBM 0.030t); corn spot 30010, SBM 52000."""
        return setup_batching_batch(tons=0.1, target_tons=0.1, corn_price=30010,
                                    corn_stock=5, sbm_stock=5)

    def test_weighment_per_weighment_rounding_values(self, api):
        """PRD §2.7: "Each weighment's `line_cost_cents` is rounded to integer cents at the moment the weighment is recorded — before any summation — and batch and order totals aggregate those already-rounded amounts; summing unrounded products and rounding once at the end is a forbidden alternative."
        PRD §3.6: "The weighment's `line_cost_cents` is `actual_tons` times `unit_price_cents`, rounded half-up to integer cents at the moment of recording — per-weighment rounding, pinned before any summation."

        Design: Difficulty/combinatorial_formula/weighment_per_line_rounding_beats_sum_then_round
        """
        ctx = self._rounding_setup(api)
        w1 = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                              ctx["bin_corn"]["id"], 0.035, ctx["op"]["id"])
        w2 = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                              ctx["bin_corn"]["id"], 0.035, ctx["op"]["id"])
        w3 = record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                              ctx["bin_sbm"]["id"], 0.030, ctx["op"]["id"])
        for w in (w1, w2, w3):
            assert_weighment(w)
        # round_half_up(0.035 * 30010) = round_half_up(1050.35) = 1050 each.
        assert w1["line_cost_cents"] == 1050
        assert w2["line_cost_cents"] == 1050
        assert w3["line_cost_cents"] == 1560  # 0.030 * 52000

    def test_batch_cost_sums_rounded_weighments(self, api):
        """PRD §2.7: "Each weighment's `line_cost_cents` is rounded to integer cents at the moment the weighment is recorded — before any summation — and batch and order totals aggregate those already-rounded amounts; summing unrounded products and rounding once at the end is a forbidden alternative."
        PRD §3.6: "its `ingredient_cost_cents` is the sum of their `line_cost_cents`."

        Design: Difficulty/combinatorial_formula/weighment_per_line_rounding_beats_sum_then_round
        """
        ctx = self._rounding_setup(api)
        record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                         ctx["bin_corn"]["id"], 0.035, ctx["op"]["id"])
        record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                         ctx["bin_corn"]["id"], 0.035, ctx["op"]["id"])
        record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                         ctx["bin_sbm"]["id"], 0.030, ctx["op"]["id"])

        batch = validate_success(api.get_batch(ctx["batch"]["id"], MM), 200)
        # Pinned per-weighment-then-sum: 1050 + 1050 + 1560 = 3660. The
        # forbidden sum-then-round order would yield 3661.
        assert batch["ingredient_cost_cents"] == 3660
        assert batch["ingredient_cost_cents"] != 3661


class TestMixDeviationBoundary:
    def _two_batch_setup(self, api):
        """One 10t CONFIRMED order; two 10t batches on L1 in disjoint windows;
        batch A weighed corn 7.140 (deviation 2.00) and batch B corn 7.141
        (deviation 2.01), SBM 3.000 on both."""
        ctx = setup_confirmed_order(tons=10, credit_limit_cents=1000000)
        op = make_employee("Olly Operator", "OPERATOR")
        line = make_line("L1")
        bin_corn = make_stocked_bin("BIN-C", ctx["corn"]["id"], 30)
        bin_sbm = make_stocked_bin("BIN-S", ctx["sbm"]["id"], 30)
        bat_a = make_batch(ctx["order"]["id"], line["id"], 10,
                           "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        bat_b = make_batch(ctx["order"]["id"], line["id"], 10,
                           "2026-05-02T12:00:00Z", "2026-05-02T13:00:00Z")
        start_batch(bat_a["id"], op["id"])
        record_weighment(bat_a["id"], ctx["corn"]["id"], bin_corn["id"], 7.140, op["id"])
        record_weighment(bat_a["id"], ctx["sbm"]["id"], bin_sbm["id"], 3.000, op["id"])
        start_batch(bat_b["id"], op["id"])
        record_weighment(bat_b["id"], ctx["corn"]["id"], bin_corn["id"], 7.141, op["id"])
        record_weighment(bat_b["id"], ctx["sbm"]["id"], bin_sbm["id"], 3.000, op["id"])
        ctx.update({"op": op, "line": line, "bat_a": bat_a, "bat_b": bat_b})
        return ctx

    def test_mix_deviation_exactly_two_percent_passes(self, api):
        """PRD §3.6: "any line strictly above 2.00 percent rejects the mix with `ERR_WEIGHMENT_OUT_OF_TOLERANCE`, while a deviation of exactly 2.00 percent passes."

        Design: Difficulty/boundary_precision_check/weighment_deviation_exactly_two_pct_passes
        """
        ctx = self._two_batch_setup(api)
        # corn line: round_half_up(|7.140 - 7.000| / 7.000 * 100, 2) == 2.00 -> passes.
        mixed = validate_success(
            api.mix_batch(ctx["bat_a"]["id"], make_operator_headers(ctx["op"]["id"])), 200)
        assert mixed["status"] == "MIXED"

    def test_mix_deviation_above_two_percent_rejected(self, api):
        """PRD §3.6: "any line strictly above 2.00 percent rejects the mix with `ERR_WEIGHMENT_OUT_OF_TOLERANCE`, while a deviation of exactly 2.00 percent passes."

        Design: Difficulty/boundary_precision_check/weighment_deviation_exactly_two_pct_passes
        """
        ctx = self._two_batch_setup(api)
        # corn line: |7.141 - 7.000| / 7.000 * 100 == 2.01 > 2.00 -> rejected.
        resp = api.mix_batch(ctx["bat_b"]["id"], make_operator_headers(ctx["op"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WEIGHMENT_OUT_OF_TOLERANCE)

        after = validate_success(api.get_batch(ctx["bat_b"]["id"], MM), 200)
        assert after["status"] == "BATCHING", "rejected mix must leave the batch BATCHING"


class TestWeighmentDomainErrors:
    def test_weighment_domain_errors(self, api):
        """PRD §3.6: "Five checks guard the record: the ingredient must appear in the order's `pinned_lines` (`ERR_INGREDIENT_NOT_IN_FORMULA`); the bin must be `READY` — a `BLOCKED` bin refuses with `ERR_BIN_BLOCKED`; the bin must be assigned to the weighed ingredient (`ERR_BIN_INGREDIENT_MISMATCH`); the bin's `on_hand_tons` must cover the draw, with equality passing (`ERR_INSUFFICIENT_INVENTORY`); and the ingredient must have an effective spot price at the current clock (`ERR_INVALID_REQUEST`)."

        Design: Corner/errors/weighment_domain_errors
        """
        ctx = setup_batching_batch(tons=10, credit_limit_cents=1000000)
        hulls = make_ingredient("HULLS")
        bin_hulls = make_stocked_bin("BIN-H", hulls["id"], 5)
        op_headers = make_operator_headers(ctx["op"]["id"])
        batch_id = ctx["batch"]["id"]

        # Corn drawn from the SBM bin: bin assigned to a different ingredient.
        r1 = api.record_weighment(batch_id, {
            "ingredient_id": ctx["corn"]["id"], "bin_id": ctx["bin_sbm"]["id"],
            "actual_tons": 1.000}, op_headers)
        validate_error(r1, ApiErrorId.ERR_BIN_INGREDIENT_MISMATCH)

        # 999t exceeds the 20t on hand.
        r2 = api.record_weighment(batch_id, {
            "ingredient_id": ctx["corn"]["id"], "bin_id": ctx["bin_corn"]["id"],
            "actual_tons": 999}, op_headers)
        validate_error(r2, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

        # HULLS is not in the order's pinned lines.
        r3 = api.record_weighment(batch_id, {
            "ingredient_id": hulls["id"], "bin_id": bin_hulls["id"],
            "actual_tons": 1.000}, op_headers)
        validate_error(r3, ApiErrorId.ERR_INGREDIENT_NOT_IN_FORMULA)

        batch = validate_success(api.get_batch(batch_id, MM), 200)
        assert batch["status"] == "BATCHING"
        for bin_id, expected in ((ctx["bin_corn"]["id"], 20),
                                 (ctx["bin_sbm"]["id"], 20),
                                 (bin_hulls["id"], 5)):
            b = validate_success(api.get_bin(bin_id, MM), 200)
            assert b["on_hand_tons"] == pytest.approx(expected, abs=1e-6), (
                "rejected weighments must not move inventory")


class TestImmediateConsistency:
    def test_immediate_consistency_weighment_response_and_bin_read(self, api):
        """PRD §2.4: "Derived fields are always recomputed immediately, inside the request that mutates their inputs; the API never answers a successful write with stale derived values."
        PRD §3.6: "Recording is never free of side effects: the bin's `on_hand_tons` drops by `actual_tons` (a draw to exactly zero flips the bin `READY` → `EMPTY`)"

        Design: Corner/consistency_model/immediate_consistency_weighment_response_and_bin_read
        """
        ctx = setup_batching_batch(tons=10, credit_limit_cents=1000000)

        w = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                             ctx["bin_corn"]["id"], 4.000, ctx["op"]["id"])
        # The 201 creation response already carries the computed pricing fields.
        assert w["unit_price_cents"] == 30000
        assert w["line_cost_cents"] == 120000  # 4.000 * 30000

        # The very next read shows the deduction — no eventual-consistency lag.
        bin_after = validate_success(api.get_bin(ctx["bin_corn"]["id"], MM), 200)
        assert bin_after["on_hand_tons"] == pytest.approx(16, abs=1e-6)
