"""Blend recipe derived block: composition totals, cost, density and indices."""
import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    FOOD_RECIPE_COMPONENTS,
    ApiErrorId,
    build_food_recipe_draft,
    build_non_food_recipe_draft,
    create_component_payload,
    get_success_data,
    hdpe_grade_payload,
    make_blend_engineer_headers,
    pcr_grade_payload,
    setup_food_contact_catalog,
    setup_non_food_catalog,
    validate_error,
    validate_success,
)


def _four_component_food_draft(api):
    """Food-contact draft carrying the first four of its five components."""
    world = setup_food_contact_catalog(api)
    world["recipe"] = build_food_recipe_draft(
        api, world, recipe_code="R-FD-1",
        components=FOOD_RECIPE_COMPONENTS[:4])
    return world


def _append_additive_line(api, world):
    """Append the fifth component: 10.0 pct additive masterbatch on layer 3."""
    get_success_data(api.add_recipe_component(
        world["recipe"]["id"],
        create_component_payload(layer_index=3, component_kind="ADDITIVE",
                                 weight_pct=10.0,
                                 resin_grade_id=world["g_ad"]["id"]),
        ENGINEER))
    return get_success_data(api.get_blend_recipe(world["recipe"]["id"], ENGINEER))


class TestStrengthIndexPenaltyFactors:
    """The binding penalty is the smaller of the family and regrind factors."""

    def test_strength_index_when_neither_penalty_binds(self, api):
        """A blend with no HDPE and no regrind takes both factors at 1.000.

        PRD: "only the smaller, more binding of the two is applied." With
        hdpe_pct at 0.000 the family factor is exactly 1.000, and with
        regrind_pct at 0.000 the regrind factor is 1.000, so only the additive
        boost moves the dart base.

        Design: Difficulty/combinatorial_formula/strength_index_min_of_family_and_regrind_factors_neither_binds
        """
        world = _four_component_food_draft(api)
        recipe = _append_additive_line(api, world)

        assert recipe["strength_index"] == pytest.approx(37.64, abs=0.01)
        assert recipe["hdpe_pct"] == pytest.approx(0.000, abs=0.01)
        assert recipe["regrind_pct"] == pytest.approx(0.000, abs=0.01)
        assert recipe["additive_pct"] == pytest.approx(10.000, abs=0.01)

    def test_composition_totals_and_dominant_family_after_final_append(self, api):
        """The append recomputes the whole derived block.

        PRD: "the server totals `weight_pct` per polymer family across the
        virgin lines and selects the family with the greatest total". The
        virgin lines total 80.0 LLDPE against 2.5 EVOH and 7.5 TIE, so LLDPE
        dominates, and the EVOH line makes barrier_layer_present true.

        Design: Difficulty/combinatorial_formula/strength_index_min_of_family_and_regrind_factors_neither_binds
        """
        world = _four_component_food_draft(api)
        recipe = _append_additive_line(api, world)

        assert recipe["total_weight_pct"] == pytest.approx(100.000, abs=0.01)
        assert recipe["dominant_polymer_family"] == "LLDPE"
        assert recipe["barrier_layer_present"] is True
        assert recipe["status"] == "DRAFT"

    def test_clarity_and_slip_indices_read_off_the_same_component_list(self, api):
        """Clarity and slip are independent of the strength penalties.

        PRD: "only the smaller, more binding of the two is applied." governs
        the strength index alone; clarity and slip are separate readings over
        the same five components and are reported to two decimals.

        Design: Difficulty/combinatorial_formula/strength_index_min_of_family_and_regrind_factors_neither_binds
        """
        world = _four_component_food_draft(api)
        recipe = _append_additive_line(api, world)

        assert recipe["clarity_index"] == pytest.approx(79.81, abs=0.01)
        assert recipe["slip_index"] == pytest.approx(34.92, abs=0.01)


class TestStrengthIndexRegrindFloor:
    """When both penalties apply only the more binding one is taken."""

    @staticmethod
    def _draft(api):
        world = setup_non_food_catalog(api)
        world["g_hd"] = get_success_data(
            api.create_resin_grade(hdpe_grade_payload(), ADMIN))
        recipe = build_non_food_recipe_draft(
            api, world, recipe_code="R-NF-13",
            components=((1, "VIRGIN", 60.0, "g_hd"), (1, "VIRGIN", 5.0, "g_ll")))
        get_success_data(api.add_recipe_component(
            recipe["id"],
            create_component_payload(layer_index=1, component_kind="REGRIND",
                                     weight_pct=35.0),
            ENGINEER))
        world["recipe"] = get_success_data(
            api.get_blend_recipe(recipe["id"], ENGINEER))
        return world

    def test_regrind_floor_binds_over_the_family_factor(self, api):
        """With 60.0 HDPE and 35.0 regrind the regrind floor 0.800 is smaller.

        PRD: "The regrind factor is the larger of 0.800 and the quantity one
        minus 0.006 multiplied by `regrind_pct`." The family factor at 60.0
        HDPE is 0.880 while the regrind factor floors at 0.800, and
        "only the smaller, more binding of the two is applied."

        Design: Difficulty/combinatorial_formula/strength_index_regrind_floor_binds_over_family_factor
        """
        recipe = self._draft(api)["recipe"]

        assert recipe["total_weight_pct"] == pytest.approx(100.000, abs=0.01)
        assert recipe["hdpe_pct"] == pytest.approx(60.000, abs=0.01)
        assert recipe["regrind_pct"] == pytest.approx(35.000, abs=0.01)
        assert recipe["regrind_cap_pct"] == pytest.approx(35.000, abs=0.01)
        assert recipe["strength_index"] == pytest.approx(19.84, abs=0.01)

    def test_submit_refused_when_strength_index_below_product_minimum(self, api):
        """A weak blend cannot leave DRAFT.

        PRD: "And `strength_index` must be at least the product's
        `min_strength_index`, or `ERR_STRENGTH_INDEX_BELOW_MIN`." The non-food
        product requires 25.0 and this blend reaches only 19.84.

        Design: Difficulty/combinatorial_formula/strength_index_regrind_floor_binds_over_family_factor
        """
        world = self._draft(api)
        validate_error(
            api.submit_blend_recipe(world["recipe"]["id"],
                                    make_blend_engineer_headers("u-be-1")),
            ApiErrorId.ERR_STRENGTH_INDEX_BELOW_MIN, 422)

        recipe = get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))
        assert recipe["status"] == "DRAFT"
        assert recipe["submitted_by_user_id"] is None


class TestBlendCostAndDensityLineRounding:
    """Cost and density round at each line before the sum is taken."""

    def test_blend_cost_rounds_each_component_line_before_summing(self, api):
        """Rounding per line yields 2.07, not the 2.06 of a single final round.

        PRD: "`blend_cost_per_kg` is then the sum of the rounded cost lines,
        rounded again to two decimals".

        Design: Difficulty/combinatorial_formula/blend_cost_rounds_each_component_line_before_summing
        """
        world = _four_component_food_draft(api)
        recipe = _append_additive_line(api, world)

        assert recipe["blend_cost_per_kg"] == pytest.approx(2.07, abs=0.01)
        assert round(recipe["blend_cost_per_kg"], 2) != 2.06

    def test_blended_density_rounds_each_component_line_before_summing(self, api):
        """Density accumulates the same way as cost.

        PRD: "Each line's contribution is its `weight_pct` divided by one
        hundred, multiplied by the relevant unit value, and **rounded to two
        decimals at the line**."

        Design: Difficulty/combinatorial_formula/blend_cost_rounds_each_component_line_before_summing
        """
        world = _four_component_food_draft(api)
        recipe = _append_additive_line(api, world)

        assert recipe["blended_density_kg_m3"] == pytest.approx(927.40, abs=0.01)
        assert recipe["total_weight_pct"] == pytest.approx(100.000, abs=0.01)


class TestRegrindCapBandDerivation:
    """The PCR band comes from virgin_pcr_pct, never from the nominal figure."""

    @staticmethod
    def _draft(api):
        world = setup_non_food_catalog(api)
        world["g_pc"] = get_success_data(
            api.create_resin_grade(pcr_grade_payload(), ADMIN))
        recipe = build_non_food_recipe_draft(
            api, world, recipe_code="R-NF-3",
            components=((1, "VIRGIN", 50.0, "g_ll"), (1, "VIRGIN", 18.0, "g_pc")))
        get_success_data(api.add_recipe_component(
            recipe["id"],
            create_component_payload(layer_index=1, component_kind="REGRIND",
                                     weight_pct=32.0),
            ENGINEER))
        world["recipe"] = get_success_data(
            api.get_blend_recipe(recipe["id"], ENGINEER))
        return world

    def test_pcr_band_and_cap_derive_from_virgin_pcr_pct(self, api):
        """18.000 virgin PCR bands MID and shifts the 35.0 base cap to 33.000.

        PRD: "Deriving the band from the step-five nominal figure instead of
        from `virgin_pcr_pct` yields a different and incorrect result." The
        nominal figure here is 26.000, which would band HIGH and give 30.000.

        Design: Difficulty/combinatorial_formula/regrind_cap_band_derives_from_virgin_pcr_not_from_nominal_content
        """
        recipe = self._draft(api)["recipe"]

        assert recipe["regrind_pct"] == pytest.approx(32.000, abs=0.01)
        assert recipe["virgin_pcr_pct"] == pytest.approx(18.000, abs=0.01)
        assert recipe["pcr_band"] == "MID"
        assert recipe["regrind_cap_pct"] == pytest.approx(33.000, abs=0.01)
        assert round(recipe["regrind_cap_pct"], 3) != 30.000
        assert recipe["nominal_recycled_content_pct"] == pytest.approx(26.000, abs=0.01)

    def test_submit_accepted_because_the_mid_band_cap_admits_the_regrind(self, api):
        """32.000 regrind sits under the 33.000 MID-band cap.

        PRD: "`regrind_pct` must be no greater than `regrind_cap_pct`, or
        `ERR_REGRIND_CAP_EXCEEDED` — equality at the cap passes."

        Design: Difficulty/combinatorial_formula/regrind_cap_band_derives_from_virgin_pcr_not_from_nominal_content
        """
        world = self._draft(api)
        submitted = validate_success(
            api.submit_blend_recipe(world["recipe"]["id"],
                                    make_blend_engineer_headers("u-be-1")), 200)

        assert submitted["status"] == "SUBMITTED"
        assert submitted["strength_index"] == pytest.approx(30.12, abs=0.01)
        assert submitted["blended_density_kg_m3"] == pytest.approx(919.64, abs=0.01)
