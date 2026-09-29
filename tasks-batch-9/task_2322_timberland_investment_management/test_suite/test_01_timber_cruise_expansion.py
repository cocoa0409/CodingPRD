"""Timber cruise expansion: per-plot netting, the stand mean, and sample-size confidence."""

from test_helpers import (
    ApiErrorId,
    assert_stand_partition,
    assert_tons,
    assert_tons_per_acre,
    validate_error,
    validate_success,
)
from test_helpers.factories import CANONICAL_CRUISE_PLOTS
from test_helpers.fixtures import (
    close_cruise,
    create_fund,
    create_property,
    create_stand,
    cruised_stand,
    open_cruise_stand,
    read_investor_report,
    read_stand,
    record_cruise_plot,
)
from test_helpers.test_users import make_forest_manager_headers


class TestCruiseExpansionRoundingOrder:
    """The three chained rounding steps of the cruise expansion."""

    def test_each_plot_is_netted_and_rounded_to_three_decimals_before_the_mean(self, api):
        """Per-plot net tons per acre are rounded first, and the mean is taken over those rounded figures.

        PRD: "The rounding order is part of the contract and is not negotiable: each plot's `net_tons_per_acre` is already rounded to three decimals; `mean_net_tons_per_acre` is the sum of those rounded per-plot figures divided by `plot_count`, rounded half-up to three decimals"

        Design: Difficulty/combinatorial_formula/cruise_expansion_pins_per_plot_rounding_before_the_mean
        """
        ctx = cruised_stand(api)

        expected_per_plot = [38.681, 37.285, 39.764, 38.127, 39.771]
        for plot, expected in zip(ctx.plots, expected_per_plot):
            assert_tons_per_acre(
                plot["net_tons_per_acre"],
                expected,
                f"plot {plot['plot_number']} net_tons_per_acre",
            )

        assert_tons_per_acre(
            ctx.stand["mean_net_tons_per_acre"], 38.726, "mean_net_tons_per_acre"
        )

    def test_the_rounded_mean_expands_across_stand_acres_to_gross_merchantable_tons(self, api):
        """Expanding the rounded mean over 120.00 acres gives 4647.12 tons, not the 4652.16 a raw-average order would give.

        PRD: "`gross_merch_tons` is that rounded mean multiplied by the stand's `acres`, rounded half-up to two decimals. Averaging raw measurements, or expanding each plot to tons before averaging, produces a different and incorrect result."

        Design: Difficulty/combinatorial_formula/cruise_expansion_pins_per_plot_rounding_before_the_mean
        """
        ctx = cruised_stand(api)
        stand = ctx.stand

        assert_tons(stand["gross_merch_tons"], 4647.12, "gross_merch_tons")
        assert abs(float(stand["gross_merch_tons"]) - 4652.16) > 0.01, (
            "gross_merch_tons must not reflect an averaging order that nets after the mean"
        )
        assert stand["cruise_confidence"] == "NORMAL"
        assert stand["status"] == "INVENTORIED"
        assert stand["plot_count"] == 5

    def test_closing_the_cruise_leaves_every_claim_bucket_empty(self, api):
        """No claim has yet been made against the stand, so available tons equal net merchantable tons.

        PRD: "Because no claim has yet been made against the stand, `available_tons` is set equal to `net_merch_tons` and all four claim buckets remain 0.00."

        Design: Difficulty/combinatorial_formula/cruise_expansion_pins_per_plot_rounding_before_the_mean
        """
        ctx = cruised_stand(api)

        assert_stand_partition(
            ctx.stand,
            net_merch_tons=4647.12,
            reserved_tons=0.00,
            committed_tons=0.00,
            dedicated_tons=0.00,
            hbu_withdrawn_tons=0.00,
            available_tons=4647.12,
        )


class TestCruiseSampleSizeBoundary:
    """Five plots earn NORMAL confidence; four take the eight percent haircut; none is refused."""

    def test_five_plots_close_at_normal_confidence_without_a_haircut(self, api):
        """At exactly five plots the sample is NORMAL and net merchantable tons equal gross merchantable tons.

        PRD: "`cruise_confidence` becomes `NORMAL` when `plot_count` is at least 5 at the moment of closure, and `LOW` otherwise. Under `NORMAL` confidence, `net_merch_tons` equals `gross_merch_tons` exactly."

        Design: Difficulty/boundary_precision_check/cruise_plot_count_boundary_five_normal_four_low_zero_rejected
        """
        ctx = cruised_stand(api, stand_overrides={"stand_code": "PC-A"})

        assert ctx.stand["cruise_confidence"] == "NORMAL"
        assert_tons_per_acre(ctx.stand["mean_net_tons_per_acre"], 38.726, "mean")
        assert_tons(ctx.stand["gross_merch_tons"], 4647.12, "gross_merch_tons")
        assert_tons(ctx.stand["net_merch_tons"], 4647.12, "net_merch_tons")
        assert ctx.stand["status"] == "INVENTORIED"

    def test_four_plots_close_at_low_confidence_and_thin_the_inventory_by_eight_percent(self, api):
        """One plot short of the threshold the sample is LOW and the expansion is thinned by eight percent.

        PRD: "Under `LOW` confidence, `net_merch_tons` is `gross_merch_tons` multiplied by the quantity one minus eight divided by one hundred"

        Design: Difficulty/boundary_precision_check/cruise_plot_count_boundary_five_normal_four_low_zero_rejected
        """
        ctx = cruised_stand(
            api,
            plots=CANONICAL_CRUISE_PLOTS[:4],
            stand_overrides={"stand_code": "PC-B"},
        )

        assert ctx.stand["cruise_confidence"] == "LOW"
        assert_tons_per_acre(ctx.stand["mean_net_tons_per_acre"], 38.464, "mean")
        assert_tons(ctx.stand["gross_merch_tons"], 4615.68, "gross_merch_tons")
        assert_tons(ctx.stand["net_merch_tons"], 4246.43, "net_merch_tons")
        assert abs(float(ctx.stand["net_merch_tons"]) - 4615.68) > 0.01, (
            "the LOW-confidence haircut must actually be applied"
        )

    def test_a_cruise_with_no_recorded_plots_cannot_close(self, api):
        """A stand with nothing measured on it is refused, and stays open for cruise.

        PRD: "it must have at least one recorded plot, or the request fails with `ERR_NO_CRUISE_PLOTS`"

        Design: Difficulty/boundary_precision_check/cruise_plot_count_boundary_five_normal_four_low_zero_rejected
        """
        ctx = open_cruise_stand(api, stand_overrides={"stand_code": "PC-C"})

        response = api.close_cruise(ctx.stand_id, None, make_forest_manager_headers())
        validate_error(response, ApiErrorId.NO_CRUISE_PLOTS.value, 422)

        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "CRUISE_OPEN"
        assert_tons(stand["net_merch_tons"], 0.00, "net_merch_tons")
        assert stand["cruise_confidence"] == "NONE"
        assert stand["plot_count"] == 0

    def test_standing_inventory_sums_the_closed_and_the_uncruised_stands_alike(self, api):
        """Standing inventory tons sum net merchantable tons over every stand that is not DISPOSED.

        PRD: "it is the sum of `net_merch_tons` over every stand of every property of the fund whose stand `status` is anything other than `DISPOSED`, rounded half-up to two decimals"

        Design: Difficulty/boundary_precision_check/cruise_plot_count_boundary_five_normal_four_low_zero_rejected
        """
        fund = create_fund(api)
        tract = create_property(api, fund["id"])

        stand_a = create_stand(api, tract["id"], stand_code="PC-A")
        for plot in CANONICAL_CRUISE_PLOTS:
            record_cruise_plot(api, stand_a["id"], **plot)
        close_cruise(api, stand_a["id"])

        stand_b = create_stand(api, tract["id"], stand_code="PC-B")
        for plot in CANONICAL_CRUISE_PLOTS[:4]:
            record_cruise_plot(api, stand_b["id"], **plot)
        close_cruise(api, stand_b["id"])

        create_stand(api, tract["id"], stand_code="PC-C")

        report = read_investor_report(api, fund["id"])
        assert_tons(report["standing_inventory_tons"], 8893.55, "standing_inventory_tons")

    def test_recording_a_plot_computes_its_net_tons_per_acre_from_the_defect_deduction(self, api):
        """Each plot's own net tons per acre is the gross measurement less its defect percentage.

        PRD: "computes the plot's own `net_tons_per_acre` as `tons_per_acre` multiplied by the quantity one minus `defect_pct` divided by one hundred"

        Design: Difficulty/combinatorial_formula/cruise_expansion_pins_per_plot_rounding_before_the_mean
        """
        ctx = open_cruise_stand(api)

        response = api.create_cruise_plot(
            {
                "stand_id": ctx.stand_id,
                "plot_number": 1,
                "tons_per_acre": 44.06,
                "defect_pct": 9.75,
                "measured_at": "2026-07-15T00:00:00Z",
            },
            make_forest_manager_headers(),
        )
        plot = validate_success(response, 201)
        assert_tons_per_acre(plot["net_tons_per_acre"], 39.764, "net_tons_per_acre")
