"""Nutrient panel computation: DATABASE aggregation with yield adjustment,
LAB adoption, input-set filtering, and the two-method divergence."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_nutrient_panel,
    compute_panel,
    create_and_lock_recipe,
    create_client,
    create_ingredient,
    create_ingredient_payload,
    create_product,
    create_recipe,
    get_recipe,
    make_client_rep_headers,
    review_lab_analysis,
    submit_lab_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]

FLOUR = dict(
    name="Wheat Flour", allergen_tags=["WHEAT"],
    kcal_per_100g=360, fat_g_per_100g=2.0, satfat_g_per_100g=0.3,
    chol_mg_per_100g=0, sodium_mg_per_100g=5, carb_g_per_100g=75,
    fiber_g_per_100g=3.0, sugar_g_per_100g=1.0, protein_g_per_100g=10,
)
SUGAR = dict(
    name="Sugar",
    kcal_per_100g=387, fat_g_per_100g=0, satfat_g_per_100g=0,
    chol_mg_per_100g=0, sodium_mg_per_100g=0, carb_g_per_100g=100,
    fiber_g_per_100g=0, sugar_g_per_100g=100, protein_g_per_100g=0,
)


def _cookie_recipe(client, product, yield_factor=1.0):
    """LOCKED 120g flour / 40g sugar recipe. Raw kcal total 586.8."""
    flour = create_ingredient(client, **FLOUR)
    sugar = create_ingredient(client, **SUGAR)
    return create_and_lock_recipe(
        product["id"], client["id"],
        [{"ingredient_id": flour["id"], "quantity_g": 120},
         {"ingredient_id": sugar["id"], "quantity_g": 40}],
        yield_factor=yield_factor)


class TestDatabaseComputation:
    def test_panel_database_yield_adjustment(self, api):
        """PRD §3.4: "Under the database method, the computation walks every
        line of the recipe: each nutrient's contribution from a line is the
        ingredient's per-100-gram value for that nutrient multiplied by the
        line's `quantity_g` and divided by 100; the contributions are summed
        across lines into a raw total per nutrient; the finished mass is the
        sum of all line quantities multiplied by the recipe's `yield_factor`;
        and each raw per-100-gram value is the nutrient's raw total divided by
        the finished mass and multiplied by 100."
        PRD §3.4: "Whichever the method, the panel's declared per-100-gram
        fields — `kcal_per_100g`, `fat_g_per_100g`, `satfat_g_per_100g`,
        `chol_mg_per_100g`, `sodium_mg_per_100g`, `carb_g_per_100g`,
        `fiber_g_per_100g`, `sugar_g_per_100g`, `protein_g_per_100g` — are the
        raw values rounded half-up to two decimal places, while the unrounded
        vector remains the basis for everything downstream, per the pinned
        rounding discipline of §2.5."

        Design: Corner/calculations/calc_panel_database_yield_adjustment
        """
        client = create_client()
        product = create_product(client)
        recipe = _cookie_recipe(client, product, yield_factor=0.8)

        panel = compute_panel(recipe["id"], method="DATABASE")
        assert_nutrient_panel(panel)
        # finished mass = 160 * 0.8 = 128 g; raw kcal total = 586.8
        assert panel["kcal_per_100g"] == pytest.approx(458.44, abs=0.005), (
            "58680 / 128 = 458.4375, rounded half-up to 2dp"
        )
        assert panel["fat_g_per_100g"] == pytest.approx(1.88, abs=0.005), (
            "240 / 128 = 1.875, round_half_up 2dp"
        )
        assert panel["sodium_mg_per_100g"] == pytest.approx(4.69, abs=0.005), (
            "600 / 128 = 4.6875"
        )
        assert panel["protein_g_per_100g"] == pytest.approx(9.38, abs=0.005), (
            "1200 / 128 = 9.375"
        )

    def test_profile_incomplete_rejected(self, api):
        """PRD §3.4: "This path demands complete data — if any line ingredient
        has even one of its nine nutrient fields null, the computation is
        rejected with `ERR_NUTRIENT_PROFILE_INCOMPLETE`."

        Design: Corner/calculations/calc_profile_incomplete_rejected
        """
        client = create_client()
        product = create_product(client)
        payload = create_ingredient_payload(name="Mystery Mix")
        del payload["sodium_mg_per_100g"]
        mix = validate_success(
            api.create_ingredient(client["id"], payload,
                                  make_client_rep_headers(client["id"])),
            201,
        )
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": mix["id"], "quantity_g": 100}])

        resp = api.create_nutrient_panel(recipe["id"], {"method": "DATABASE"},
                                         TEST_USERS["label_analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_NUTRIENT_PROFILE_INCOMPLETE,
                       expected_status=422)

        data, meta = validate_paginated(api.list_nutrient_panels(recipe["id"], ADMIN))
        assert data == [] and meta["total_count"] == 0, (
            "a rejected computation must not persist a panel"
        )

    def test_lab_panel_requires_validated_analysis(self, api):
        """PRD §3.4: "Under the laboratory method, the panel adopts the
        recipe's most recently validated analysis exactly as measured,
        decimals and all; when the recipe has no validated analysis —
        `latest_validated_lab_analysis_id` empty — the request is rejected
        with `ERR_NO_VALIDATED_LAB_ANALYSIS`, and when one exists the panel
        records it in `basis_lab_analysis_id`."

        Design: Corner/calculations/calc_lab_panel_requires_validated_analysis
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": wafer["id"], "quantity_g": 100}])
        submit_lab_analysis(recipe["id"], client["id"], lab_report_ref="LR-1")

        resp = api.create_nutrient_panel(recipe["id"], {"method": "LAB"},
                                         TEST_USERS["label_analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_VALIDATED_LAB_ANALYSIS,
                       expected_status=422)

    def test_recipe_not_locked_on_panel_compute(self, api):
        """PRD §3.4: "A `LabelAnalyst` computes a **NutrientPanel** for a
        `LOCKED` recipe — any other recipe status is rejected with
        `ERR_RECIPE_NOT_LOCKED` — by naming a `method` of `DATABASE` or
        `LAB`."

        Design: Corner/errors/err_recipe_not_locked_on_panel_compute
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_recipe(product["id"], client["id"],
                               [{"ingredient_id": wafer["id"], "quantity_g": 100}])
        assert recipe["status"] == "DRAFT"

        resp = api.create_nutrient_panel(recipe["id"], {"method": "DATABASE"},
                                         TEST_USERS["label_analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_LOCKED, expected_status=409)


class TestDatabaseVsLabDivergence:
    def test_database_and_lab_panels_diverge(self, api):
        """PRD §3.4: "Under the laboratory method, the panel adopts the
        recipe's most recently validated analysis exactly as measured,
        decimals and all; when the recipe has no validated analysis —
        `latest_validated_lab_analysis_id` empty — the request is rejected
        with `ERR_NO_VALIDATED_LAB_ANALYSIS`, and when one exists the panel
        records it in `basis_lab_analysis_id`."
        PRD §3.4: "The two methods legitimately disagree: identical recipes
        yield different panel numbers depending on the method."

        Design: Difficulty/dual_variant_calc/database_vs_lab_panel_divergence
        """
        client = create_client()
        product = create_product(client)
        recipe = _cookie_recipe(client, product)

        panel_db = compute_panel(recipe["id"], method="DATABASE")
        assert panel_db["kcal_per_100g"] == pytest.approx(366.75, abs=0.005), (
            "586.8 raw kcal over 160 g finished mass, scaled per 100 g"
        )

        lab = submit_lab_analysis(recipe["id"], client["id"], lab_report_ref="LR-100")
        review_lab_analysis(lab["id"], outcome="VALIDATED")

        panel_lab = compute_panel(recipe["id"], method="LAB")
        assert_nutrient_panel(panel_lab)
        assert panel_lab["kcal_per_100g"] == pytest.approx(350.0, abs=0.005), (
            "the LAB panel adopts the validated assay exactly as measured"
        )
        assert panel_lab["basis_lab_analysis_id"] == lab["id"]

    def test_lab_validation_does_not_stale_database_panel(self, api):
        """PRD §3.4: "The panel is linked to its recipe via `recipe_id` and
        enters as `CURRENT`."
        PRD §3.3: "The validating reviewer's identity lands in `reviewed_by`;
        the recipe's `latest_validated_lab_analysis_id` is repointed to this
        analysis; any other `VALIDATED` analysis of the same recipe is moved
        by the system to `SUPERSEDED`; every lab-method panel whose
        `basis_lab_analysis_id` names the superseded analysis flips to
        `STALE`; claim assessments whose `basis_panel_id` went stale flip to
        `SUSPENDED`; and every label version carrying a newly suspended claim
        has its `content_status` recomputed to `NEEDS_REVISION`."

        Design: Difficulty/dual_variant_calc/database_vs_lab_panel_divergence
        """
        client = create_client()
        product = create_product(client)
        recipe = _cookie_recipe(client, product)
        panel_db = compute_panel(recipe["id"], method="DATABASE")

        lab = submit_lab_analysis(recipe["id"], client["id"], lab_report_ref="LR-100")
        review_lab_analysis(lab["id"], outcome="VALIDATED")
        panel_lab = compute_panel(recipe["id"], method="LAB")

        panel_db_after = validate_success(api.get_nutrient_panel(panel_db["id"], ADMIN))
        panel_lab_after = validate_success(api.get_nutrient_panel(panel_lab["id"], ADMIN))
        assert panel_db_after["status"] == "CURRENT", (
            "a DATABASE panel survives an unrelated-method lab validation"
        )
        assert panel_lab_after["status"] == "CURRENT"
        recipe_after = get_recipe(recipe["id"])
        assert recipe_after["latest_validated_lab_analysis_id"] == lab["id"]
