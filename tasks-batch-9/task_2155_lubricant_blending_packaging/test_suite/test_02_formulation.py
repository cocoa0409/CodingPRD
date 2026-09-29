"""Specifications, the log-log blend prediction and the recipe activation gates."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    CLOCK_BASE_ISO,
    STANDARD_ADDITIVE_TREAT_PCT,
    STANDARD_PREDICTED_KV100,
    ApiErrorId,
    TEST_USERS,
    assert_blend_recipe,
    create_active_recipe,
    create_active_spec,
    create_recipe,
    create_spec,
    make_effective,
    read_recipe,
    read_spec,
    set_clock,
    setup_active_formulation,
    setup_cleared_change_request,
    standard_components,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]


class TestPredictedBlendViscosity:
    def test_predicted_viscosity_follows_the_log_log_blend_relation(self, api):
        """PRD 3.2: "The **predicted blended viscosity**, `predicted_kv100_cst`, follows the
        ASTM D341 log-log blending relation and is non-linear in every input."
        PRD 3.2: "For each component, add a viscosity offset of 0.7 to its
        `nominal_kv100_cst`, take the base-ten logarithm of that sum, and take the base-ten
        logarithm of the result; call that the component's blending index."
        PRD 3.2: "Multiply each component's blending index by its `mass_fraction_pct` divided
        by one hundred, and add those products together, walking the component rows in
        ascending `created_at` order and accumulating at full precision with no intermediate
        rounding."
        PRD 3.2: "Raise ten to the power of that accumulated sum, then raise ten to the power
        of the figure just obtained, and subtract the same 0.7 offset."
        PRD 3.2: "Round that final result half up to three decimal places."

        Design: Difficulty/combinatorial_formula/recipe_predicted_kv100_loglog_three_component_blend
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()

        recipe = validate_success(
            api.create_blend_recipe(
                {
                    "product_spec_id": spec["id"],
                    "total_mass_basis_kg": 1000.0,
                    "components": standard_components(),
                },
                PM,
            ),
            201,
        )
        assert_blend_recipe(recipe)

        assert recipe["predicted_kv100_cst"] == pytest.approx(7.614, abs=0.0005), (
            "the double-logarithm weighting of 5.200, 850.000 and 105.000 cSt at 84 / 6 / 10 "
            f"percent yields 7.614 cSt, got {recipe['predicted_kv100_cst']}"
        )
        assert recipe["predicted_kv100_cst"] != pytest.approx(65.868, abs=0.0005), (
            "a mass-weighted arithmetic mean would give 65.868 cSt, which is not the rule"
        )

    def test_recipe_creation_records_treat_rate_count_and_pinned_revision(self, api):
        """PRD 3.2: "The **additive treat rate**, `additive_treat_pct`, is the sum of
        `mass_fraction_pct` over the components whose `component_type` is `ADDITIVE_PACKAGE`,
        rounded half up to two decimal places."
        PRD 3.2: "The `component_count` is simply the number of component rows on the recipe."
        PRD 3.2: "The recipe is created in `DRAFT` and copies the specification's current
        `revision` into `spec_revision_pinned` at that moment."
        PRD 3.2: "Finally, `predicted_kv100_cst` must sit inside the specification's acceptance
        band — at or above the target multiplied by one minus the tolerance divided by one
        hundred, and at or below the target multiplied by one plus the tolerance divided by one
        hundred, each endpoint rounded half up to three decimal places, both comparisons
        inclusive — or the attempt is refused with `ERR_PREDICTED_VISCOSITY_OUT_OF_SPEC`."

        Design: Difficulty/combinatorial_formula/recipe_predicted_kv100_loglog_three_component_blend
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        recipe = create_recipe(spec["id"])

        assert recipe["additive_treat_pct"] == pytest.approx(
            STANDARD_ADDITIVE_TREAT_PCT, abs=0.005
        )
        assert recipe["component_count"] == 3
        assert recipe["spec_revision_pinned"] == 1
        assert recipe["status"] == "DRAFT"

        # 7.614 sits inside the 7.372 .. 7.828 band derived from 7.600 at 3.0 percent.
        activated = validate_success(api.activate_blend_recipe(recipe["id"], PM))
        assert activated["status"] == "ACTIVE"
        assert activated["predicted_kv100_cst"] == pytest.approx(
            STANDARD_PREDICTED_KV100, abs=0.0005
        )

        rows, meta = validate_paginated(api.list_recipe_components(recipe["id"], PM))
        assert meta["total_count"] == 3 and len(rows) == 3


class TestRecipeActivationGates:
    def test_treat_rate_below_the_specification_minimum_blocks_activation(self, api):
        """PRD 3.2: "The `additive_treat_pct` must be at least the specification's
        `min_additive_treat_pct`, or the attempt is refused with `ERR_TREAT_RATE_BELOW_SPEC`."
        PRD 3.2: "The **additive treat rate**, `additive_treat_pct`, is the sum of
        `mass_fraction_pct` over the components whose `component_type` is `ADDITIVE_PACKAGE`,
        rounded half up to two decimal places."

        Design: Corner/calculations/additive_treat_pct_below_spec_minimum_blocks_recipe_activation
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec(min_additive_treat_pct=15.00)
        recipe = create_recipe(spec["id"])

        assert recipe["additive_treat_pct"] == pytest.approx(10.00, abs=0.005)

        response = api.activate_blend_recipe(recipe["id"], PM)
        validate_error(response, ApiErrorId.ERR_TREAT_RATE_BELOW_SPEC.value, 422)

        assert read_recipe(recipe["id"])["status"] == "DRAFT"

    def test_mass_fractions_that_do_not_total_one_hundred_are_refused_at_creation(self, api):
        """PRD 3.2: "Creation is refused with `ERR_RECIPE_FRACTION_SUM` unless the supplied
        mass fractions total exactly 100.00."

        Design: Corner/calculations/recipe_fraction_sum_not_exactly_100_rejected
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()

        components = standard_components()
        components[2]["mass_fraction_pct"] = 9.00  # totals 99.00, not 100.00

        response = api.create_blend_recipe(
            {
                "product_spec_id": spec["id"],
                "total_mass_basis_kg": 1000.0,
                "components": components,
            },
            PM,
        )
        validate_error(response, ApiErrorId.ERR_RECIPE_FRACTION_SUM.value, 422)

        _, meta = validate_paginated(
            api.list_blend_recipes(PM, {"product_spec_id": spec["id"]})
        )
        assert meta["total_count"] == 0

    def test_prediction_outside_the_acceptance_band_blocks_activation(self, api):
        """PRD 3.2: "Finally, `predicted_kv100_cst` must sit inside the specification's
        acceptance band — at or above the target multiplied by one minus the tolerance divided
        by one hundred, and at or below the target multiplied by one plus the tolerance divided
        by one hundred, each endpoint rounded half up to three decimal places, both comparisons
        inclusive — or the attempt is refused with `ERR_PREDICTED_VISCOSITY_OUT_OF_SPEC`."
        PRD 3.2: "The `additive_treat_pct` must be at least the specification's
        `min_additive_treat_pct`, or the attempt is refused with `ERR_TREAT_RATE_BELOW_SPEC`."

        Design: Corner/calculations/predicted_viscosity_outside_band_blocks_recipe_activation
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec(
            product_code="LUBE-15W40-CK4",
            sae_grade="15W-40",
            target_kv100_cst=12.000,
            kv100_tolerance_pct=3.0,
            min_additive_treat_pct=8.00,
            additive_family="HDEO_API_CK4",
        )
        components = standard_components()
        components[2]["component_code"] = "ADD-CK4"
        components[2]["additive_family"] = "HDEO_API_CK4"
        recipe = create_recipe(spec["id"], components)

        assert recipe["predicted_kv100_cst"] == pytest.approx(
            STANDARD_PREDICTED_KV100, abs=0.0005
        )

        # The band derived from 12.000 at 3.0 percent is 11.640 .. 12.360.
        response = api.activate_blend_recipe(recipe["id"], PM)
        error = validate_error(
            response, ApiErrorId.ERR_PREDICTED_VISCOSITY_OUT_OF_SPEC.value, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_TREAT_RATE_BELOW_SPEC.value

        assert read_recipe(recipe["id"])["status"] == "DRAFT"

    def test_activation_against_a_draft_specification_is_refused(self, api):
        """PRD 3.2: "The governing specification must be `ACTIVE`, or the attempt is refused
        with `ERR_SPEC_NOT_ACTIVE`."
        PRD 3.1: "A new specification is born in `DRAFT` at `revision` 1, with `effective_from`
        still unset."

        Design: Corner/errors/recipe_activation_on_draft_spec_returns_spec_not_active
        """
        set_clock(CLOCK_BASE)
        spec = create_spec()
        recipe = create_recipe(spec["id"])

        response = api.activate_blend_recipe(recipe["id"], PM)
        validate_error(response, ApiErrorId.ERR_SPEC_NOT_ACTIVE.value, 409)

        assert read_recipe(recipe["id"])["status"] == "DRAFT"
        refreshed_spec = read_spec(spec["id"])
        assert refreshed_spec["status"] == "DRAFT"
        assert refreshed_spec["effective_from"] is None

    def test_recipe_left_behind_by_a_revision_advance_cannot_be_activated(self, api):
        """PRD 3.2: "The recipe's `spec_revision_pinned` must still equal the specification's
        current `revision`, or the attempt is refused with `ERR_SPEC_REVISION_STALE` — this is
        how a recipe left behind by cascade A is prevented from being resurrected."
        PRD 3.1: "Independently, every recipe on the specification whose status is `ACTIVE` and
        whose `spec_revision_pinned` is now behind the specification's `revision` moves
        `ACTIVE → RETIRED`."
        PRD 3.1: "The specification undergoes a self-loop `ACTIVE → ACTIVE`: its `revision`
        increases by 1 and the four requested values are written through onto
        `target_kv100_cst`, `kv100_tolerance_pct`, `min_additive_treat_pct` and
        `additive_family`."

        Design: Corner/validations/spec_revision_stale_blocks_recipe_activation_after_a_spec_change
        """
        world = setup_active_formulation(with_lots=False)
        stale_draft = create_recipe(world["spec"]["id"])

        request = setup_cleared_change_request(world["spec"]["id"])
        make_effective(request["id"])

        spec = read_spec(world["spec"]["id"])
        assert spec["revision"] == 2
        assert spec["target_kv100_cst"] == pytest.approx(7.700, abs=0.0005)
        assert read_recipe(world["recipe"]["id"])["status"] == "RETIRED"

        refreshed_draft = read_recipe(stale_draft["id"])
        assert refreshed_draft["status"] == "DRAFT"
        assert refreshed_draft["spec_revision_pinned"] == 1

        response = api.activate_blend_recipe(stale_draft["id"], PM)
        error = validate_error(response, ApiErrorId.ERR_SPEC_REVISION_STALE.value, 409)
        # 7.614 lies inside the new 7.469 .. 7.931 band, so the prediction gate would pass.
        assert error["error_id"] != ApiErrorId.ERR_PREDICTED_VISCOSITY_OUT_OF_SPEC.value

        assert read_recipe(stale_draft["id"])["status"] == "DRAFT"


class TestSpecificationLifecycle:
    def test_activating_an_already_active_specification_is_refused(self, api):
        """PRD 3.1: "Activation moves the specification `DRAFT → ACTIVE`, which is legal only
        while it is `DRAFT`."
        PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."
        PRD 2.4: "Most resources additionally carry `updated_at`, in the same timestamp format,
        and `version`, an integer that begins at 1 when the resource is created and increases by
        exactly 1 on every mutation of that resource."

        Design: Corner/state_machines/product_spec_activate_twice_returns_invalid_state
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        assert spec["version"] == 2, "creation gives version 1 and activation advances it to 2"

        response = api.activate_product_spec(spec["id"], PM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        refreshed = read_spec(spec["id"])
        assert refreshed["status"] == "ACTIVE"
        assert refreshed["version"] == 2, "the refused call must not advance the version"
        assert refreshed["effective_from"] == CLOCK_BASE_ISO

    def test_withdrawing_a_specification_retires_only_its_active_recipes(self, api):
        """PRD 3.1: "Withdrawal moves it `ACTIVE → WITHDRAWN` and carries a `reason`; it is
        legal only while the specification is `ACTIVE` **and** no approval claim on it is
        `ACTIVE`."
        PRD 3.1: "Withdrawal retires every recipe on the specification that is currently
        `ACTIVE`, driving each of them `ACTIVE → RETIRED`."

        Design: Corner/state_machines/product_spec_withdraw_retires_active_recipes
        """
        set_clock(CLOCK_BASE)
        spec = create_active_spec()
        active_recipe = create_active_recipe(spec["id"])
        draft_recipe = create_recipe(spec["id"])

        withdrawn = validate_success(
            api.withdraw_product_spec(spec["id"], {"reason": "PRODUCT_DISCONTINUED"}, PM)
        )
        assert withdrawn["status"] == "WITHDRAWN"

        assert read_recipe(active_recipe["id"])["status"] == "RETIRED"
        assert read_recipe(draft_recipe["id"])["status"] == "DRAFT", (
            "withdrawal retires only the recipes that are currently ACTIVE"
        )

        _, meta = validate_paginated(
            api.list_blend_recipes(PM, {"product_spec_id": spec["id"]})
        )
        assert meta["total_count"] == 2
