"""Thresholds tested on both sides of the edge: the synthetic moisture ceiling at
12.00 against 12.01, the specimen minimum at two against three, and the trailer
weight ceiling at thirteen bundles against fourteen.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    LoadOrderStatus,
    LotStatus,
    QualityState,
    QuarantineReason,
    RunStatus,
    SaleableGrade,
    assert_gypsum_lot,
    assert_load_order,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
)


class TestSyntheticMoistureCeiling:
    """The default ceiling of 12.0 percent is compared strictly, so the edge value
    passes and one hundredth above it does not."""

    @staticmethod
    def _plant_and_lot(api: ApiClient) -> tuple[dict, dict]:
        plant = fixtures.create_plant(api)
        lot = fixtures.create_lot(
            api,
            factories.synthetic_lot_payload(
                plant["id"], received_tons=100.0, declared_free_moisture_pct=11.9
            ),
        )
        return plant, lot

    def test_a_lot_assayed_exactly_at_the_ceiling_is_approved(self, api: ApiClient) -> None:
        """12.00 percent against a 12.0 ceiling clears the check and approves the lot.

        PRD: "Check one applies only to a `SYNTHETIC` lot: if its laboratory `free_moisture_pct` is strictly greater than the plant's `synthetic_free_moisture_ceiling_pct`, the reason is `MOISTURE_CEILING` — a value exactly equal to the ceiling passes."

        Design: Difficulty/boundary_precision_check/synthetic_moisture_ceiling_exact_vs_one_hundredth_over
        """
        plant, lot = self._plant_and_lot(api)
        assert plant["synthetic_free_moisture_ceiling_pct"] == pytest.approx(12.0, abs=0.005), (
            "the plant was registered without an override, so the default applies"
        )

        assayed = fixtures.assay_lot(api, lot["id"], 12.00, 94.0, 120)

        assert_gypsum_lot(assayed)
        assert assayed["status"] == LotStatus.APPROVED.value
        assert assayed["quarantine_reason"] is None
        assert assayed["free_moisture_pct"] == pytest.approx(12.00, abs=0.005)
        assert assayed["assay_count"] == 1
        assert assayed["version"] == 2, "the assay is one mutation of the lot"
        assert assayed["remaining_tons"] == pytest.approx(100.000, abs=0.0005)

    def test_a_lot_one_hundredth_above_the_ceiling_is_quarantined(self, api: ApiClient) -> None:
        """12.01 percent is strictly greater and is not rounded down to the ceiling.

        PRD: "Comparisons use the values as supplied, at two decimal places, with no rounding applied."

        Design: Difficulty/boundary_precision_check/synthetic_moisture_ceiling_exact_vs_one_hundredth_over
        """
        _, lot = self._plant_and_lot(api)

        assayed = fixtures.assay_lot(api, lot["id"], 12.01, 94.0, 120)

        assert assayed["status"] == LotStatus.QUARANTINED.value
        assert assayed["quarantine_reason"] == QuarantineReason.MOISTURE_CEILING.value
        assert assayed["free_moisture_pct"] == pytest.approx(12.01, abs=0.005)
        assert assayed["assay_count"] == 1
        assert assayed["version"] == 2
        assert assayed["remaining_tons"] == pytest.approx(100.000, abs=0.0005), (
            "a quarantine does not consume or write off tonnage"
        )


class TestSpecimenMinimumAtEvaluation:
    """Two specimens are one short of the evaluation minimum; the third makes the
    identical call succeed."""

    def test_two_specimens_are_refused_and_leave_the_run_in_test(self, api: ApiClient) -> None:
        """A run with two passing specimens cannot be evaluated and stays IN_TEST.

        PRD: "Second, the run must have at least three specimens; one or two yields `ERR_INSUFFICIENT_SPECIMENS`."

        Design: Difficulty/boundary_precision_check/specimen_count_two_vs_three_at_quality_evaluation
        """
        world = fixtures.completed_run(api)
        fixtures.record_passing_specimens(api, world.run_id, 2)

        before = world.read_run()
        assert before["quality_state"] == QualityState.IN_TEST.value
        assert before["specimen_count"] == 2

        validate_error(
            api.evaluate_quality(world.run_id, {}, test_users.QUALITY_INSPECTOR),
            ApiErrorId.INSUFFICIENT_SPECIMENS.value,
            422,
        )

        after = world.read_run()
        assert after["quality_state"] == QualityState.IN_TEST.value, (
            "the refused evaluation did not branch the quality dimension"
        )
        assert after["specimen_count"] == 2
        assert after["saleable_grade"] == SaleableGrade.UNGRADED.value

    def test_the_third_specimen_makes_the_same_evaluation_release(self, api: ApiClient) -> None:
        """Three passing specimens evaluate to RELEASED at a fail rate of 0.0000.

        PRD: "Otherwise, if `fail_rate` is exactly `0.0000`, the outcome is `RELEASED`."

        Design: Difficulty/boundary_precision_check/specimen_count_two_vs_three_at_quality_evaluation
        """
        world = fixtures.completed_run(api)
        fixtures.record_passing_specimens(api, world.run_id, 2)
        validate_error(
            api.evaluate_quality(world.run_id, {}, test_users.QUALITY_INSPECTOR),
            ApiErrorId.INSUFFICIENT_SPECIMENS.value,
            422,
        )

        fixtures.record_specimen(api, world.run_id, factories.PASSING_SPECIMENS[2])
        assert world.read_run()["specimen_count"] == 3

        evaluated = fixtures.evaluate(api, world.run_id)

        assert evaluated["quality_state"] == QualityState.RELEASED.value
        assert evaluated["fail_rate"] == pytest.approx(0.0000, abs=0.00005)
        assert evaluated["failing_specimen_count"] == 0
        assert evaluated["saleable_grade"] == SaleableGrade.FIRST_QUALITY.value
        assert evaluated["status"] == RunStatus.COMPLETED.value, (
            "the lifecycle dimension is untouched by the evaluation"
        )
        assert evaluated["available_msf"] == pytest.approx(290.000, abs=0.0005)


class TestTrailerWeightCeiling:
    """3686.40 pounds a bundle puts thirteen bundles inside the 48000-pound ceiling
    and fourteen outside it."""

    def test_fourteen_bundles_are_refused_and_no_load_order_is_created(
        self, api: ApiClient
    ) -> None:
        """51609.60 pounds breaches the ceiling and the staging attempt writes nothing.

        PRD: "`trailer_weight_lb` may not exceed 48000 pounds — the comparison is inclusive, so a trailer at exactly 48000 pounds is legal — and a breach is `ERR_TRAILER_WEIGHT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/trailer_weight_thirteen_vs_fourteen_bundles
        """
        world = fixtures.completed_run(api)

        validate_error(
            api.create_load_order(
                factories.load_order_payload(
                    world.run_id, world.market_id, bundles_count=14, boards_per_bundle=48
                ),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.TRAILER_WEIGHT_EXCEEDED.value,
            422,
        )

        _, meta = validate_paginated(
            api.list_load_orders(
                test_users.PRODUCTION_SCHEDULER, params={"run_id": world.run_id}
            )
        )
        assert meta["total_count"] == 0, "the refused staging created no order"
        assert world.read_run()["available_msf"] == pytest.approx(290.000, abs=0.0005), (
            "nothing was committed against the run"
        )

    def test_thirteen_bundles_stage_just_under_the_ceiling(self, api: ApiClient) -> None:
        """47923.20 pounds is legal and the load stages with its volume committed.

        PRD: "`trailer_weight_lb` is the billable bundle count multiplied by `bundle_weight_lb`, rounded half-up to two decimals."

        Design: Difficulty/boundary_precision_check/trailer_weight_thirteen_vs_fourteen_bundles
        """
        world = fixtures.completed_run(api)
        load = fixtures.stage_load(api, world, bundles_count=13, boards_per_bundle=48)

        assert_load_order(load)
        assert load["bundles_count"] == 13
        assert load["bundle_weight_lb"] == pytest.approx(3686.40, abs=0.005)
        assert load["trailer_weight_lb"] == pytest.approx(47923.20, abs=0.005)
        assert load["total_msf"] == pytest.approx(29.952, abs=0.0005)
        assert load["quoted_freight_usd"] == pytest.approx(819.85, abs=0.005)
        assert load["status"] == LoadOrderStatus.STAGED.value

        _, meta = validate_paginated(
            api.list_load_orders(
                test_users.PRODUCTION_SCHEDULER, params={"run_id": world.run_id}
            )
        )
        assert meta["total_count"] == 1

        assert world.read_run()["available_msf"] == pytest.approx(260.048, abs=0.0005), (
            "290.000 net good less the 29.952 now committed to the trailer"
        )
