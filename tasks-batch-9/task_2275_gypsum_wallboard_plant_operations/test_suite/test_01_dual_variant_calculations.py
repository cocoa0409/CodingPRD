"""Two calculations that each run twice on the same row and are meant to disagree:
the calcination yield on a laboratory basis versus a belt-scale basis, and freight
quoted at staging versus settled at shipment.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    BatchStatus,
    LoadOrderStatus,
    StuccoQualityFlag,
    assert_calciner_batch,
    assert_load_order,
    find_by,
    fixtures,
    test_users,
    validate_paginated,
)


class TestBatchYieldBothBases:
    """Batch B1 draws 120 t, 80 t and 60 t whose laboratory and belt-scale
    moistures differ, so both blend metrics and both yields diverge."""

    def test_plan_basis_rounds_once_and_as_fed_basis_rounds_after_every_feed(
        self, api: ApiClient
    ) -> None:
        """The two blend metrics read the same three feeds and land on different numbers.

        PRD: "`feed_moisture_plan_pct` is the sum over all feeds of `tons_fed` multiplied by `assay_free_moisture_pct`, divided by the sum of `tons_fed` over all feeds, with the single final quotient rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/batch_yield_plan_vs_as_fed_basis_diverge
        """
        world = fixtures.baseline_with_stucco(api)
        batch = world.read_batch()

        assert_calciner_batch(batch)
        assert batch["feed_tons_total"] == pytest.approx(260.000, abs=0.0005), (
            "three feeds of 120, 80 and 60 tonnes total 260.000"
        )
        assert batch["feed_moisture_plan_pct"] == pytest.approx(7.31, abs=0.005), (
            "the plan basis weights the laboratory moistures once: 1900/260 rounds to 7.31"
        )
        assert batch["feed_moisture_as_fed_pct"] == pytest.approx(7.92, abs=0.005), (
            "the as-fed basis re-rounds its running average after every feed, reaching 7.92"
        )
        assert batch["feed_moisture_plan_pct"] != batch["feed_moisture_as_fed_pct"], (
            "the two bases are computed to disagree on the same feed rows"
        )
        assert batch["feed_purity_plan_pct"] == pytest.approx(93.23, abs=0.005), (
            "the purity plan basis weights 94.0, 91.5 and 94.0 by tonnage: 93.23"
        )

    def test_planned_yield_stamps_at_close_and_actual_yield_stamps_at_completion(
        self, api: ApiClient
    ) -> None:
        """The planned yield is 205.896 tons and the actual yield only 204.530.

        PRD: "The **planned yield** variant uses each feed's `assay_free_moisture_pct` as its moisture basis and is stamped on `stucco_yield_plan_tons` when the feed side closes."

        Design: Difficulty/dual_variant_calc/batch_yield_plan_vs_as_fed_basis_diverge
        """
        world = fixtures.baseline_with_lots(api)
        closed = fixtures.fed_batch(api, world)

        assert closed["status"] == BatchStatus.CALCINING.value
        assert closed["stucco_yield_plan_tons"] == pytest.approx(205.896, abs=0.0005), (
            "the laboratory basis yields 205.896 tons of stucco"
        )
        assert closed["stucco_yield_actual_tons"] == pytest.approx(0.000, abs=0.0005), (
            "the actual yield is not stamped until the batch completes"
        )

        fixtures.record_stucco_test(api, closed["id"])
        completed = fixtures.read_batch(api, closed["id"])

        assert completed["status"] == BatchStatus.COMPLETED.value
        assert completed["stucco_quality_flag"] == StuccoQualityFlag.PASS.value
        assert completed["stucco_yield_plan_tons"] == pytest.approx(205.896, abs=0.0005), (
            "completion does not disturb the planned figure"
        )
        assert completed["stucco_yield_actual_tons"] == pytest.approx(204.530, abs=0.0005), (
            "the belt-scale basis yields 204.530 tons, 1.366 tons short of the plan"
        )

    def test_only_the_actual_yield_moves_silo_tonnage(self, api: ApiClient) -> None:
        """The silo is credited with 204.530, the measured figure, not the planned 205.896.

        PRD: "The **actual yield** variant uses each feed's `measured_free_moisture_pct` instead and is stamped on `stucco_yield_actual_tons` when the batch reaches `COMPLETED`; only this second variant ever moves silo tonnage."

        Design: Difficulty/dual_variant_calc/batch_yield_plan_vs_as_fed_basis_diverge
        """
        world = fixtures.baseline_with_lots(api)
        closed = fixtures.fed_batch(api, world)

        before = world.read_plant()
        assert before["stucco_on_hand_tons"] == pytest.approx(0.000, abs=0.0005), (
            "closing the feed side credits nothing"
        )

        fixtures.record_stucco_test(api, closed["id"])
        after = world.read_plant()

        assert after["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005), (
            "the silo receives the actual yield of 204.530 tons"
        )
        assert after["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005), (
            "nothing is committed yet, so all of it is available"
        )
        assert after["production_posture"] == "OPEN", (
            "204.530 available tons with no held runs is OPEN"
        )

    def test_both_dry_tonnage_bases_are_persisted_on_every_feed(self, api: ApiClient) -> None:
        """Each feed row keeps the laboratory dry tonnage next to the belt-scale one.

        PRD: "It also persists two dry-tonnage intermediates at six decimals: `dry_tons_plan`, which is `tons_fed` multiplied by one minus `assay_free_moisture_pct` divided by 100, and `dry_tons_as_fed`, which is `tons_fed` multiplied by one minus `measured_free_moisture_pct` divided by 100."

        Design: Difficulty/dual_variant_calc/batch_yield_plan_vs_as_fed_basis_diverge
        """
        world = fixtures.baseline_with_lots(api)
        closed = fixtures.fed_batch(api, world)

        feeds, meta = validate_paginated(
            api.list_batch_feeds(
                headers=test_users.MATERIALS_CONTROLLER, params={"batch_id": closed["id"]}
            )
        )
        assert meta["total_count"] == 3, "the batch drew three increments"

        first = find_by(feeds, feed_seq=1)
        assert first is not None, "the first feed must be listed"
        assert first["dry_tons_plan"] == pytest.approx(108.720000, abs=0.0000005), (
            "120.000 tonnes at a laboratory moisture of 9.40 percent is 108.720000 dry tonnes"
        )
        assert first["dry_tons_as_fed"] == pytest.approx(107.760000, abs=0.0000005), (
            "the belt scale saw 10.20 percent, giving 107.760000 dry tonnes"
        )

        second = find_by(feeds, feed_seq=2)
        assert second is not None
        assert second["dry_tons_plan"] == pytest.approx(77.920000, abs=0.0000005)
        assert second["dry_tons_as_fed"] == pytest.approx(77.520000, abs=0.0000005)


class TestFreightBothVariants:
    """A twelve-bundle load quotes at staging and settles at shipment, and the two
    figures differ by the overweight accessorial."""

    def test_quote_bills_the_planned_bundles_with_neither_accessorial(
        self, api: ApiClient
    ) -> None:
        """Twelve bundles of 48 boards quote 756.79 dollars with no overweight fee.

        PRD: "The **quoted** variant runs at staging and is stamped on `quoted_freight_usd`. It bills the planned `bundles_count`, and it applies neither the overweight accessorial nor the backhaul credit — both of those terms are zero in a quote."

        Design: Difficulty/dual_variant_calc/freight_quoted_vs_settled_diverge_on_load
        """
        world = fixtures.released_run_with_load(api)
        load = world.read_load()

        assert_load_order(load)
        assert load["status"] == LoadOrderStatus.STAGED.value
        assert load["board_msf_each"] == pytest.approx(0.048000, abs=0.0000005)
        assert load["bundle_msf"] == pytest.approx(2.3040, abs=0.00005)
        assert load["total_msf"] == pytest.approx(27.648, abs=0.0005)
        assert load["trailer_weight_lb"] == pytest.approx(44236.80, abs=0.005)
        assert load["quoted_freight_usd"] == pytest.approx(756.79, abs=0.005), (
            "53.22 per bundle across twelve bundles plus 118.15 of fuel is 756.79"
        )
        assert load["settled_freight_usd"] is None, "nothing settles until the load ships"
        assert load["freight_variance_usd"] is None, "the variance stays null until shipment"

    def test_settlement_adds_the_overweight_accessorial_and_records_the_variance(
        self, api: ApiClient
    ) -> None:
        """The same twelve bundles settle at 761.53, a variance of 4.74 dollars.

        PRD: "The accessorial actually charged is recorded on `overweight_fee_usd`, and `freight_variance_usd` is `settled_freight_usd` less `quoted_freight_usd`, rounded half-up to two decimals; it stays null until the load has shipped."

        Design: Difficulty/dual_variant_calc/freight_quoted_vs_settled_diverge_on_load
        """
        world = fixtures.released_run_with_load(api)
        fixtures.record_load(api, world.load_id, 12)
        shipped = fixtures.ship_load(api, world.load_id)

        assert shipped["status"] == LoadOrderStatus.SHIPPED.value
        assert shipped["loaded_bundles_count"] == 12
        assert shipped["trailer_weight_lb"] == pytest.approx(44236.80, abs=0.005)
        assert shipped["overweight_fee_usd"] == pytest.approx(4.74, abs=0.005), (
            "236.80 pounds above the 44000-pound target at two cents a pound is 4.74"
        )
        assert shipped["settled_freight_usd"] == pytest.approx(761.53, abs=0.005), (
            "the settled charge is the quote plus the overweight accessorial"
        )
        assert shipped["freight_variance_usd"] == pytest.approx(4.74, abs=0.005), (
            "settled less quoted is 761.53 - 756.79 = 4.74"
        )
        assert shipped["quoted_freight_usd"] == pytest.approx(756.79, abs=0.005), (
            "shipment does not rewrite the quote"
        )

    def test_the_minimum_charge_floor_is_applied_after_the_rounding(
        self, api: ApiClient
    ) -> None:
        """Five bundles compute 315.33 dollars of freight and bill the 425.00 floor.

        PRD: "The floor is applied last and the floored value is never rounded again."

        Design: Difficulty/dual_variant_calc/freight_quoted_vs_settled_diverge_on_load
        """
        world = fixtures.released_run(api)
        load = fixtures.stage_load(api, world, bundles_count=5, boards_per_bundle=48)

        assert load["total_msf"] == pytest.approx(11.520, abs=0.0005)
        assert load["trailer_weight_lb"] == pytest.approx(18432.00, abs=0.005)
        assert load["quoted_freight_usd"] == pytest.approx(425.00, abs=0.005), (
            "266.10 of line haul plus 49.23 of fuel is 315.33, which the 425.00 floor replaces"
        )

        fixtures.record_load(api, load["id"], 5)
        shipped = fixtures.ship_load(api, load["id"])

        assert shipped["overweight_fee_usd"] == pytest.approx(0.00, abs=0.005), (
            "18432.00 pounds is far below the 44000-pound target"
        )
        assert shipped["settled_freight_usd"] == pytest.approx(425.00, abs=0.005), (
            "the settled charge is floored to the same 425.00 minimum"
        )
        assert shipped["freight_variance_usd"] == pytest.approx(0.00, abs=0.005), (
            "a load that quotes and settles at the floor has no variance"
        )
