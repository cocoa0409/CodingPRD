"""Demold weight acceptance: dual-variant tolerance and boundary precision."""
import pytest

from test_helpers import (
    ApiErrorId,
    demold,
    setup_work_order_cured,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

LAM = TEST_USERS["laminator_headers"]
SM = TEST_USERS["shop_manager_headers"]


class TestPrototypeVsProduction:
    def _cured(self, api, phase: str, mold_code: str, wo_no: str):
        return setup_work_order_cured(
            mold_overrides={"mold_code": mold_code, "tooling_phase": phase},
            work_order_overrides={"work_order_no": wo_no},
            batch_overrides={"batch_code": f"{wo_no}-B"},
        )

    def test_prototype_tolerance_admits_deviation_0_08(self, api):
        """PRD §3.6: "The tolerance applied depends on the mold's `tooling_phase` at
        this moment: a `PRODUCTION` tool applies the pinned ply book's
        `tolerance_pct`, while a `PROTOTYPE` or `TRANSITION` tool applies a fixed
        prototype tolerance of 0.08" and "A deviation no greater than the tolerance
        passes, with equality passing, and the work order moves from `CURED` to
        `IN_INSPECTION`". 2160.0 g vs the 2000.0 g target is a deviation of exactly
        0.0800, admitted on the prototype tool.

        Design: Difficulty/dual_variant_calc/part_weight_acceptance_prototype_vs_production
        """
        ctx = self._cured(api, "PROTOTYPE", "MOLD-PR1", "WO-PROTO")
        demolded = demold(ctx, 2160.0)
        assert demolded["weight_deviation_pct"] == pytest.approx(0.08, abs=1e-9)
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], SM), 200)
        assert order["status"] == "IN_INSPECTION"

    def test_production_tolerance_scraps_deviation_0_08(self, api):
        """PRD §3.6: "a `PRODUCTION` tool applies the pinned ply book's
        `tolerance_pct`" (0.05 for the pinned book) and "a strictly greater
        deviation scraps the order on the spot with `scrap_reason` set to
        `WEIGHT_OUT_OF_TOLERANCE`" — "so one and the same measured weight can pass
        on a prototype tool and scrap on a production tool."

        Design: Difficulty/dual_variant_calc/part_weight_acceptance_prototype_vs_production
        """
        ctx = self._cured(api, "PRODUCTION", "MOLD-PD1", "WO-PROD")
        demolded = demold(ctx, 2160.0)
        assert demolded["weight_deviation_pct"] == pytest.approx(0.08, abs=1e-9)
        order = validate_success(api.get_work_order(ctx["work_order"]["id"], SM), 200)
        assert order["status"] == "SCRAPPED"
        assert order["scrap_reason"] == "WEIGHT_OUT_OF_TOLERANCE"


class TestDeviationBoundary:
    def _cured_production(self, api):
        return setup_work_order_cured(
            mold_overrides={"mold_code": "MOLD-B1", "tooling_phase": "PRODUCTION"},
            work_order_overrides={"work_order_no": "WO-B1"},
            batch_overrides={"batch_code": "BATCH-B1"},
        )

    def test_weight_deviation_exactly_at_tolerance_passes(self, api):
        """PRD §3.6: "The deviation is the absolute difference between
        `actual_part_weight_g` and `target_part_weight_g`, divided by
        `target_part_weight_g`, rounded half-up to four decimal places and stored as
        `weight_deviation_pct`." and "A deviation no greater than the tolerance
        passes, with equality passing". 2100.0 g vs 2000.0 g -> deviation exactly
        0.0500 == tolerance 0.05.

        Design: Difficulty/boundary_precision_check/weight_deviation_exactly_at_tolerance_passes
        """
        ctx = self._cured_production(api)
        demolded = demold(ctx, 2100.0)
        assert demolded["weight_deviation_pct"] == pytest.approx(0.05, abs=1e-9)
        assert demolded["status"] == "IN_INSPECTION"

    def test_weight_deviation_one_tick_over_tolerance_scraps(self, api):
        """PRD §3.6: "a strictly greater deviation scraps the order on the spot
        with `scrap_reason` set to `WEIGHT_OUT_OF_TOLERANCE`." 2101.0 g vs 2000.0 g
        -> deviation 0.0505 > 0.05.

        Design: Difficulty/boundary_precision_check/weight_deviation_exactly_at_tolerance_passes
        """
        ctx = self._cured_production(api)
        demolded = demold(ctx, 2101.0)
        assert demolded["weight_deviation_pct"] == pytest.approx(0.0505, abs=1e-9)
        assert demolded["status"] == "SCRAPPED"
        assert demolded["scrap_reason"] == "WEIGHT_OUT_OF_TOLERANCE"
