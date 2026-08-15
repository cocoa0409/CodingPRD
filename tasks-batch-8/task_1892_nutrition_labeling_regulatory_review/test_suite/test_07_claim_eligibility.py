"""Claim eligibility: evaluation order (market recognition, per-serving
disqualifiers, per-RACC thresholds), the pinned raw-path rounding, market
variants of regulation, and the suspension cycle on panel staleness."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_claim_assessment,
    compute_panel,
    create_and_lock_recipe,
    create_claim,
    create_client,
    create_ingredient,
    create_label_draft,
    create_product,
    create_racc_assignment,
    create_recipe,
    get_label_version,
    list_claims,
    review_lab_analysis,
    setup_lab_claim_workspace,
    submit_lab_analysis,
    validate_error,
    validate_success,
)


def _single_ingredient_workspace(ingredient_overrides, product_overrides=None,
                                 market_code="US_FDA", declared_format="TABULAR"):
    """Client + product + one-ingredient LOCKED recipe + DATABASE panel +
    RACC assignment + DRAFT label (basis DATABASE)."""
    client = create_client(home_market_code=market_code)
    product = create_product(client, **(product_overrides or {}))
    ingredient = create_ingredient(client, **ingredient_overrides)
    recipe = create_and_lock_recipe(
        product["id"], client["id"],
        [{"ingredient_id": ingredient["id"], "quantity_g": 100}])
    panel = compute_panel(recipe["id"], method="DATABASE")
    racc = create_racc_assignment(product["id"], market_code=market_code)
    label = create_label_draft(product["id"], racc["id"],
                               market_code=market_code,
                               declared_format=declared_format,
                               statement_recipe_id=recipe["id"])
    return {"client": client, "product": product, "ingredient": ingredient,
            "recipe": recipe, "panel": panel, "racc": racc, "label": label}


CHIPS = dict(name="Chips", kcal_per_100g=500, fat_g_per_100g=10.0,
             satfat_g_per_100g=3.0, chol_mg_per_100g=0, sodium_mg_per_100g=1700,
             carb_g_per_100g=60, fiber_g_per_100g=4.0, sugar_g_per_100g=2.0,
             protein_g_per_100g=6.0)
SNACK_PRODUCT = dict(name="Chips", product_category="SNACK", net_weight_g=30,
                     total_surface_area_sq_in=20.0, pdp_area_sq_in=6.0,
                     household_unit_name="piece", household_unit_weight_g=1)


class TestDisqualifierOverridesThreshold:
    def test_disqualifier_overrides_passing_threshold(self, api):
        """PRD §3.7: "Second, disqualifiers on the per-serving values, checked
        in the fixed order fat, then saturated fat, then cholesterol, then
        sodium: total fat strictly above 13.0 grams, saturated fat strictly
        above 4.0 grams, cholesterol strictly above 60.0 milligrams, or sodium
        strictly above 480.0 milligrams per serving each disqualify, the first
        breach hit determines `disqualified_by` as `FAT`, `SATFAT`, `CHOL`, or
        `SODIUM`, and any breach renders the claim `INELIGIBLE`."

        Design: Difficulty/combinatorial_formula/claim_disqualifier_overrides_passing_threshold
        """
        ws = _single_ingredient_workspace(CHIPS, SNACK_PRODUCT)
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert_claim_assessment(claim)
        assert claim["status"] == "INELIGIBLE", (
            "the per-serving sodium disqualifier (1700 x 0.30 = 510.0 > "
            "480.0) fires even though the per-RACC fat threshold is met"
        )
        assert claim["disqualified_by"] == "SODIUM", (
            "fat 3.0 / satfat 0.9 / chol 0 per serving are all under; sodium "
            "is the first breach"
        )

    def test_disqualified_claim_persists_evaluation_fields(self, api):
        """PRD §3.7: "Every evaluated claim persists
        `evaluated_value_per_racc`, the `threshold_value` that was applied,
        `disqualified_by`, and the `basis_panel_id` of the panel used."
        PRD §3.7: "Third, the claim's own threshold on the per-RACC value,
        identical in both markets where regulated: `FAT_FREE` requires fat
        below 0.5 grams; `LOW_FAT` fat at most 3.0 grams; `SUGAR_FREE` sugars
        below 0.5 grams; `LOW_SODIUM` sodium at most 140 milligrams;
        `HIGH_FIBER` fiber at least 5.0 grams; `LOW_CALORIE` at most 40
        calories."

        Design: Difficulty/combinatorial_formula/claim_disqualifier_overrides_passing_threshold
        """
        ws = _single_ingredient_workspace(CHIPS, SNACK_PRODUCT)
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["evaluated_value_per_racc"] == pytest.approx(3.0), (
            "10.0 g/100g x 30 g RACC / 100 — the threshold is met exactly"
        )
        assert claim["threshold_value"] == pytest.approx(3.0)
        assert claim["basis_panel_id"] == ws["panel"]["id"]
        assert claim["status"] == "INELIGIBLE"


class TestNestedRoundingRawPath:
    BRINE = dict(name="Brine Mix", kcal_per_100g=100, fat_g_per_100g=4.115,
                 satfat_g_per_100g=1.0, chol_mg_per_100g=0,
                 sodium_mg_per_100g=50, carb_g_per_100g=10, fiber_g_per_100g=1.0,
                 sugar_g_per_100g=1.0, protein_g_per_100g=2.0)

    def test_claim_input_computed_from_raw_unrounded_value(self, api):
        """PRD §2.5: "One ordering rule is pinned and non-negotiable: all
        downstream quantities — per-RACC claim inputs, per-serving
        declarations — are computed from the raw, unrounded per-100-gram
        values, never from the two-decimal declared values."
        PRD §3.7: "Two compared values are derived per nutrient, each rounded
        half-up to two decimals from the raw per-100-gram vector: the per-RACC
        value scales by `racc_g`, and the per-serving value scales by
        `serving_size_g`."

        Design: Difficulty/combinatorial_formula/nested_rounding_raw_path_pinned
        """
        ws = _single_ingredient_workspace(self.BRINE, SNACK_PRODUCT)
        assert ws["panel"]["fat_g_per_100g"] == pytest.approx(4.12), (
            "the declared per-100g value is the 2dp half-up rounding of raw "
            "4.115"
        )
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["evaluated_value_per_racc"] == pytest.approx(1.23), (
            "raw path: round_half_up(4.115 x 0.30, 2); the round-first path "
            "would yield 1.24"
        )

    def test_raw_path_claim_settles_eligible(self, api):
        """PRD §2.5: "One ordering rule is pinned and non-negotiable: all
        downstream quantities — per-RACC claim inputs, per-serving
        declarations — are computed from the raw, unrounded per-100-gram
        values, never from the two-decimal declared values."
        PRD §3.7: "Meeting the threshold settles the claim `ELIGIBLE`;
        missing it settles `INELIGIBLE`, with `disqualified_by` recorded as
        `NONE` when no disqualifier fired."

        Design: Difficulty/combinatorial_formula/nested_rounding_raw_path_pinned
        """
        ws = _single_ingredient_workspace(self.BRINE, SNACK_PRODUCT)
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["status"] == "ELIGIBLE", (
            "1.23 <= 3.0 and no per-serving disqualifier (fat 1.23 / satfat "
            "0.3 / chol 0 / sodium 15 all under)"
        )
        assert claim["disqualified_by"] == "NONE"


class TestLowFatThresholdBoundary:
    def test_fat_at_exactly_3_per_racc_eligible(self, api):
        """PRD §3.7: "Third, the claim's own threshold on the per-RACC value,
        identical in both markets where regulated: `FAT_FREE` requires fat
        below 0.5 grams; `LOW_FAT` fat at most 3.0 grams; `SUGAR_FREE` sugars
        below 0.5 grams; `LOW_SODIUM` sodium at most 140 milligrams;
        `HIGH_FIBER` fiber at least 5.0 grams; `LOW_CALORIE` at most 40
        calories."
        PRD §3.7: "Meeting the threshold settles the claim `ELIGIBLE`;
        missing it settles `INELIGIBLE`, with `disqualified_by` recorded as
        `NONE` when no disqualifier fired."

        Design: Difficulty/boundary_precision_check/boundary_low_fat_threshold_exact
        """
        mix_a = dict(CHIPS, name="Cracker Mix A", sodium_mg_per_100g=100,
                     fiber_g_per_100g=2.0, sugar_g_per_100g=2.0,
                     protein_g_per_100g=6.0, carb_g_per_100g=70,
                     kcal_per_100g=400, satfat_g_per_100g=2.0)
        ws = _single_ingredient_workspace(mix_a, dict(SNACK_PRODUCT,
                                                      name="Crackers A"))
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["evaluated_value_per_racc"] == pytest.approx(3.0)
        assert claim["status"] == "ELIGIBLE", "3.0 <= 3.0: boundary inclusive"

    def test_fat_just_above_3_per_racc_ineligible(self, api):
        """PRD §3.7: "Third, the claim's own threshold on the per-RACC value,
        identical in both markets where regulated: `FAT_FREE` requires fat
        below 0.5 grams; `LOW_FAT` fat at most 3.0 grams; `SUGAR_FREE` sugars
        below 0.5 grams; `LOW_SODIUM` sodium at most 140 milligrams;
        `HIGH_FIBER` fiber at least 5.0 grams; `LOW_CALORIE` at most 40
        calories."
        PRD §3.7: "Meeting the threshold settles the claim `ELIGIBLE`;
        missing it settles `INELIGIBLE`, with `disqualified_by` recorded as
        `NONE` when no disqualifier fired."

        Design: Difficulty/boundary_precision_check/boundary_low_fat_threshold_exact
        """
        mix_b = dict(CHIPS, name="Cracker Mix B", fat_g_per_100g=10.05,
                     sodium_mg_per_100g=100, fiber_g_per_100g=2.0,
                     sugar_g_per_100g=2.0, protein_g_per_100g=6.0,
                     carb_g_per_100g=70, kcal_per_100g=400,
                     satfat_g_per_100g=2.0)
        ws = _single_ingredient_workspace(mix_b, dict(SNACK_PRODUCT,
                                                      name="Crackers B"))
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["evaluated_value_per_racc"] == pytest.approx(3.02), (
            "10.05 x 0.30 = 3.015, rounded half-up"
        )
        assert claim["status"] == "INELIGIBLE", "3.02 > 3.0"
        assert claim["disqualified_by"] == "NONE", (
            "no disqualifier fired; the threshold alone settles it"
        )


class TestClaimPrerequisites:
    def test_claim_rejected_when_recipe_not_locked(self, api):
        """PRD §3.7: "Claims may only be added while the label's
        `review_status` is `DRAFT` or `IN_REVIEW`; attempts on labels in any
        other review state are rejected with `ERR_INVALID_STATE_TRANSITION`,
        and a product without a currently `LOCKED` recipe fails with
        `ERR_RECIPE_NOT_LOCKED`."

        Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_unlocked_recipe
        """
        client = create_client()
        product = create_product(client)
        flour = create_ingredient(client, name="Wheat Flour",
                                  allergen_tags=["WHEAT"])
        create_recipe(product["id"], client["id"],
                      [{"ingredient_id": flour["id"], "quantity_g": 120}])
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        label = create_label_draft(product["id"], racc["id"],
                                   ingredient_statement_text="Wheat Flour",
                                   contains_text="Contains: Wheat.")

        resp = api.create_claim(label["id"], {"claim_type": "LOW_FAT"},
                                TEST_USERS["label_analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_LOCKED, expected_status=409)
        assert list_claims(label["id"]) == [], (
            "no ClaimAssessment is persisted by the rejected call"
        )

    def test_claim_succeeds_once_recipe_locked(self, api):
        """PRD §3.7: "Evaluation is synchronous at creation and always reads
        the most recent `CURRENT` panel of the label's locked recipe whose
        method equals the label's `nutrient_basis`, together with the `racc_g`
        and `serving_size_g` of the pinned RACC assignment."
        PRD §3.7: "Meeting the threshold settles the claim `ELIGIBLE`;
        missing it settles `INELIGIBLE`, with `disqualified_by` recorded as
        `NONE` when no disqualifier fired."

        Design: Difficulty/cross_entity_state_dependency/claim_blocked_by_unlocked_recipe
        """
        client = create_client()
        product = create_product(client)
        flour = create_ingredient(
            client, name="Wheat Flour", allergen_tags=["WHEAT"],
            kcal_per_100g=360, fat_g_per_100g=2.0, satfat_g_per_100g=0.3,
            chol_mg_per_100g=0, sodium_mg_per_100g=5, carb_g_per_100g=75,
            fiber_g_per_100g=3.0, sugar_g_per_100g=1.0, protein_g_per_100g=10)
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": flour["id"], "quantity_g": 120}])
        compute_panel(recipe["id"], method="DATABASE")
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        label = create_label_draft(product["id"], racc["id"],
                                   statement_recipe_id=recipe["id"])

        claim = create_claim(label["id"], "LOW_FAT")
        assert_claim_assessment(claim)
        assert claim["status"] == "ELIGIBLE", (
            "fat per RACC 2.0 x 0.55 = 1.1 <= 3.0 once the recipe is LOCKED"
        )


class TestClaimSuspensionCycle:
    def test_eligible_claim_suspends_when_basis_panel_stales(self, api):
        """PRD §3.7: "Thereafter its health tracks its basis panel: when the
        panel goes `STALE` through either cascade of §3.2 and §3.3, an
        `ELIGIBLE` claim is suspended, and the owning label's `content_status`
        flips to `NEEDS_REVISION`."

        Design: Difficulty/non_linear_state_machine/claim_suspension_cycle_on_panel_staleness
        """
        ws = setup_lab_claim_workspace()
        assert ws["claim"]["status"] == "ELIGIBLE", (
            "fat per RACC 1.4 x 0.55 = 0.77 <= 3.0"
        )

        lab2 = submit_lab_analysis(
            ws["recipe"]["id"], ws["client"]["id"], lab_report_ref="LR-101",
            kcal_per_100g=351.0, fat_g_per_100g=1.5, sodium_mg_per_100g=3.6,
            carb_g_per_100g=80.1, sugar_g_per_100g=24.1)
        review_lab_analysis(lab2["id"], outcome="VALIDATED")

        claim = list_claims(ws["label"]["id"])[0]
        assert claim["status"] == "SUSPENDED", "cycle leg 1"
        assert get_label_version(ws["label"]["id"])["content_status"] == (
            "NEEDS_REVISION"
        )

    def test_suspended_claim_reevaluates_eligible_on_new_panel(self, api):
        """PRD §3.7: "When a new `CURRENT` panel later appears for the label's
        recipe and nutrient basis, each suspended claim re-evaluates against
        it: a passing evaluation returns the claim to `ELIGIBLE` and repoints
        `basis_panel_id` to the new panel, while a failing evaluation settles
        it as `INELIGIBLE`; either way the label's content status is
        recomputed."

        Design: Difficulty/non_linear_state_machine/claim_suspension_cycle_on_panel_staleness
        """
        ws = setup_lab_claim_workspace()
        lab2 = submit_lab_analysis(
            ws["recipe"]["id"], ws["client"]["id"], lab_report_ref="LR-101",
            kcal_per_100g=351.0, fat_g_per_100g=1.5, sodium_mg_per_100g=3.6,
            carb_g_per_100g=80.1, sugar_g_per_100g=24.1)
        review_lab_analysis(lab2["id"], outcome="VALIDATED")

        panel2 = compute_panel(ws["recipe"]["id"], method="LAB")
        claim = list_claims(ws["label"]["id"])[0]
        assert claim["status"] == "ELIGIBLE", (
            "cycle leg 2: re-evaluated against the new panel, fat per RACC "
            "1.5 x 0.55 = 0.825 -> 0.83 <= 3.0"
        )
        assert claim["basis_panel_id"] == panel2["id"]


class TestMarketRecognition:
    def test_claim_not_required_unregulated_market(self, api):
        """PRD §3.7: "First, market recognition: the Canadian market does not
        regulate `SUGAR_FREE` or `LOW_CALORIE`, so a claim of either type on a
        `CA_CFIA` label settles immediately as `NOT_REQUIRED`, leaving
        `evaluated_value_per_racc`, `threshold_value`, and `disqualified_by`
        empty."

        Design: Corner/calculations/calc_claim_not_required_unregulated_market
        """
        ws = _single_ingredient_workspace(
            dict(name="Wafers"), market_code="CA_CFIA")
        claim = create_claim(ws["label"]["id"], "SUGAR_FREE")
        assert claim["status"] == "NOT_REQUIRED"
        assert claim["evaluated_value_per_racc"] is None, (
            "no threshold comparison performed"
        )
        assert claim["threshold_value"] is None
        assert claim["disqualified_by"] is None

    def test_high_fiber_at_exactly_5g_eligible(self, api):
        """PRD §3.7: "Third, the claim's own threshold on the per-RACC value,
        identical in both markets where regulated: `FAT_FREE` requires fat
        below 0.5 grams; `LOW_FAT` fat at most 3.0 grams; `SUGAR_FREE` sugars
        below 0.5 grams; `LOW_SODIUM` sodium at most 140 milligrams;
        `HIGH_FIBER` fiber at least 5.0 grams; `LOW_CALORIE` at most 40
        calories."
        PRD §3.7: "Meeting the threshold settles the claim `ELIGIBLE`;
        missing it settles `INELIGIBLE`, with `disqualified_by` recorded as
        `NONE` when no disqualifier fired."

        Design: Corner/calculations/calc_high_fiber_at_exactly_5g_eligible
        """
        bran = dict(name="Bran Mix", kcal_per_100g=300, fat_g_per_100g=1.0,
                    satfat_g_per_100g=0.2, chol_mg_per_100g=0,
                    sodium_mg_per_100g=50, carb_g_per_100g=70,
                    fiber_g_per_100g=12.5, sugar_g_per_100g=5.0,
                    protein_g_per_100g=8.0)
        cereal = dict(name="Cereal", product_category="CEREAL", net_weight_g=120,
                      total_surface_area_sq_in=50.0, pdp_area_sq_in=10.0,
                      household_unit_name="piece", household_unit_weight_g=13)
        ws = _single_ingredient_workspace(bran, cereal,
                                          declared_format="STANDARD_VERTICAL")
        claim = create_claim(ws["label"]["id"], "HIGH_FIBER")
        assert claim["evaluated_value_per_racc"] == pytest.approx(5.0), (
            "12.5 g/100g x 40 g RACC / 100"
        )
        assert claim["status"] == "ELIGIBLE", ">= boundary inclusive"
