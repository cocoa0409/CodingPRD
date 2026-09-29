"""The two screening score bases and the designation threshold they feed.

Both score variants run over the same indicator rows but read different
percentile columns, and only the statewide result drives designation — so the
divergence between them and the exact 65.00 cut are proved separately.
"""

from test_helpers import (
    CATEGORY_DEMOGRAPHIC,
    DATA_STATUS_CURRENT,
    DESIGNATION_OVERBURDENED,
    DESIGNATION_UNDESIGNATED,
    OVERBURDENED_THRESHOLD,
    assert_amount,
    assert_area_components,
    assert_area_scores,
    assert_field,
    file_indicator,
    read_area,
)


class TestStatewideScoringPass:
    """PRD §3.1 writes the statewide means and the score they combine into."""

    def test_statewide_pass_stores_its_three_components_and_designates(self, api, area_a):
        """Four indicators produce 87.50 / 80.00 / 88.00 and a 74.03 score.

        PRD §3.1: "Within that set, a category component is 0.00 when no qualifying
        row belongs to that category, and is otherwise the sum of the qualifying
        rows' percentile values in that category divided by the number of those
        rows, rounded half up to two decimals — an unweighted mean, so no tie-break
        is needed." and "The statewide variant reads each row's
        `statewide_percentile`; the county variant reads each row's
        `county_percentile`." and "The number of qualifying rows is written to
        `active_indicator_count` and is shared by both variants."
        PRD §3.1: "Take the pollution component multiplied by 0.55, add the health
        component multiplied by 0.45, then multiply the result by the demographic
        component divided by 100; round that half up to two decimals to obtain the
        pre-penalty score." and "The statewide pass writes `ej_screen_score_statewide`
        and also stores its three category means in `pollution_component_statewide`,
        `health_component_statewide` and `demographic_component_statewide`; the
        county pass writes `ej_screen_score_county`."
        PRD §3.1: "A score of **at least 80.00** designates the area
        `SEVERELY_OVERBURDENED`; otherwise a score of **at least 65.00** designates
        it `OVERBURDENED`; otherwise it is `UNDESIGNATED`."

        Design: Difficulty/dual_variant_calc/ej_screen_score_basis_divergence_statewide_vs_county
        """
        area = read_area(api, area_a["area_id"])

        # PM25 85.00 and DIESEL_PM 90.00 average to 87.50 on the statewide column.
        assert_area_components(area, pollution=87.50, health=80.00, demographic=88.00)
        assert_amount(
            area.get("ej_screen_score_statewide"), 74.03, "ej_screen_score_statewide"
        )
        assert_field(area, "designation", DESIGNATION_OVERBURDENED)
        assert_field(area, "active_indicator_count", 4)
        assert_field(area, "translation_required", True)
        assert_field(area, "data_status", DATA_STATUS_CURRENT)
        assert_field(area, "enforcement_burden_points", 0)

    def test_county_pass_diverges_from_the_statewide_pass(self, api, area_a):
        """The same rows score 39.68 on the county column, 34.35 points lower.

        PRD §3.1: "The qualifying input set is identical for both: the area's
        indicator rows whose `status` is `ACTIVE` and whose `vintage_year` is at
        least the clock year minus five and at most the clock year, both bounds
        inclusive."
        PRD §3.1: "Because the two passes read different percentile columns from
        identical rows, they generally produce different numbers, and an area can be
        designated on the statewide basis while its complaints score modestly on the
        county basis." and "The statewide score is the only one that drives
        designation, applicability snapshots and cumulative impact; the county score
        is used for nothing but complaint inspection priority."

        Design: Difficulty/dual_variant_calc/ej_screen_score_basis_divergence_statewide_vs_county
        """
        area = read_area(api, area_a["area_id"])

        # County columns: pollution 66.00, health 55.00, demographic 65.00.
        assert_area_scores(area, statewide=74.03, county=39.68)
        divergence = area["ej_screen_score_statewide"] - area["ej_screen_score_county"]
        assert_amount(divergence, 34.35, "statewide minus county divergence")
        # Designation reads the statewide figure only, so the modest county score
        # does not soften it.
        assert_field(area, "designation", DESIGNATION_OVERBURDENED)


class TestDesignationThreshold:
    """PRD §3.1 designates at exactly 65.00 and not one hundredth below."""

    def test_a_statewide_score_of_exactly_65_designates_the_area(
        self, api, area_c_boundary_pair
    ):
        """65.00 sits on the inclusive boundary, so the area is designated.

        PRD §3.1: "Designation follows immediately from the statewide score,
        compared against the stored two-decimal value with no re-rounding." and
        "Both comparisons are inclusive, so a score of exactly 65.00 designates the
        area."

        Design: Difficulty/boundary_precision_check/designation_threshold_exactly_65_designates
        """
        state = area_c_boundary_pair
        filed = file_indicator(
            api,
            state["area_c_id"],
            "POVERTY_RATE",
            raw_value=34.00,
            statewide_percentile=100.00,
            county_percentile=90.00,
            expected_area_version=state["area_c_version"],
        )
        assert_field(filed, "category", CATEGORY_DEMOGRAPHIC)

        area = read_area(api, state["area_c_id"])
        assert_area_components(area, pollution=65.00, health=65.00, demographic=100.00)
        # 65.00 x 0.55 + 65.00 x 0.45 = 65.00, scaled by 100/100.
        assert_area_scores(area, statewide=65.00, county=38.48)
        assert area["ej_screen_score_statewide"] == OVERBURDENED_THRESHOLD, (
            "the statewide score should land exactly on the designation threshold"
        )
        assert_field(area, "designation", DESIGNATION_OVERBURDENED)
        assert_field(area, "active_indicator_count", 3)
        assert_field(area, "translation_required", False)

    def test_a_statewide_score_one_hundredth_lower_does_not_designate(
        self, api, area_c_boundary_pair
    ):
        """64.99 is below the cut, so the area stays undesignated.

        PRD §3.1: "Designation follows immediately from the statewide score,
        compared against the stored two-decimal value with no re-rounding." and "A
        score of **at least 80.00** designates the area `SEVERELY_OVERBURDENED`;
        otherwise a score of **at least 65.00** designates it `OVERBURDENED`;
        otherwise it is `UNDESIGNATED`."

        Design: Difficulty/boundary_precision_check/designation_threshold_exactly_65_designates
        """
        state = area_c_boundary_pair
        filed = file_indicator(
            api,
            state["area_c_low_id"],
            "POVERTY_RATE",
            raw_value=33.90,
            statewide_percentile=100.00,
            county_percentile=90.00,
            expected_area_version=state["area_c_low_version"],
        )
        assert_field(filed, "category", CATEGORY_DEMOGRAPHIC)

        area = read_area(api, state["area_c_low_id"])
        assert_area_scores(area, statewide=64.99, county=27.00)
        assert area["ej_screen_score_statewide"] < OVERBURDENED_THRESHOLD, (
            "the statewide score should sit one hundredth below the threshold"
        )
        assert_field(area, "designation", DESIGNATION_UNDESIGNATED)
        assert_field(area, "active_indicator_count", 3)
