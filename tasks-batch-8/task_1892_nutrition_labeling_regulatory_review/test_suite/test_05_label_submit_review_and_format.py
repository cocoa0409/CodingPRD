"""Canonical statement computation, submit-review gates (state before
statement safety), and the auto-created format check's tier boundaries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    canonical_statements,
    compute_panel,
    create_and_lock_recipe,
    create_client,
    create_ingredient,
    create_label_draft,
    create_product,
    create_racc_assignment,
    create_recipe,
    get_label_version,
    lock_recipe,
    set_clock,
    setup_wafer_workspace,
    submit_label,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]


class TestCanonicalStatements:
    def test_ingredient_statement_canonical_order(self, api):
        """PRD §3.2: "The canonical order sorts the recipe's lines by
        `quantity_g` descending, breaks ties by the ingredient's `created_at`
        ascending, and breaks any remaining tie by ingredient `name`
        ascending. The returned `ingredient_statement_text` is the
        comma-joined ingredient names in that order. The returned
        `contains_text` is built from the distinct allergen tags in the order
        they first appear along the canonical line order, rendered as the
        literal prefix `Contains: `, the comma-joined tags, and a closing
        period; when no line carries any allergen tag, the canonical statement
        is exactly `Contains: None.`"

        Design: Corner/calculations/calc_ingredient_statement_canonical_order
        """
        client = create_client()
        product = create_product(client, include_household=False)
        # The clock is advanced between creations so the created_at tie-break
        # is unambiguous regardless of the server's timestamp source.
        flour = create_ingredient(
            client, name="Wheat Flour", allergen_tags=["WHEAT"],
            kcal_per_100g=360, fat_g_per_100g=2.0, satfat_g_per_100g=0.3,
            chol_mg_per_100g=0, sodium_mg_per_100g=5, carb_g_per_100g=75,
            fiber_g_per_100g=3.0, sugar_g_per_100g=1.0, protein_g_per_100g=10)
        set_clock("2026-08-02T00:00:00Z")
        sugar = create_ingredient(
            client, name="Sugar",
            kcal_per_100g=387, fat_g_per_100g=0, satfat_g_per_100g=0,
            chol_mg_per_100g=0, sodium_mg_per_100g=0, carb_g_per_100g=100,
            fiber_g_per_100g=0, sugar_g_per_100g=100, protein_g_per_100g=0)
        set_clock("2026-08-03T00:00:00Z")
        butter = create_ingredient(
            client, name="Butter", allergen_tags=["MILK"],
            kcal_per_100g=717, fat_g_per_100g=81.0, satfat_g_per_100g=51.0,
            chol_mg_per_100g=215, sodium_mg_per_100g=11, carb_g_per_100g=0.1,
            fiber_g_per_100g=0, sugar_g_per_100g=0.1, protein_g_per_100g=0.9)

        # Line input order deliberately disagrees with the canonical order.
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": butter["id"], "quantity_g": 50},
             {"ingredient_id": sugar["id"], "quantity_g": 100},
             {"ingredient_id": flour["id"], "quantity_g": 100}])

        canonical = canonical_statements(recipe["id"])
        assert canonical["ingredient_statement_text"] == "Wheat Flour, Sugar, Butter", (
            "quantity_g descending; the 100 g tie breaks by the ingredient's "
            "created_at ascending — flour before sugar — regardless of line "
            "input order"
        )
        assert canonical["contains_text"] == "Contains: WHEAT, MILK.", (
            "allergens in first-appearance order along the canonical lines; "
            "PRD §3.2 renders the comma-joined tags themselves, which are the "
            "uppercase allergen codes of §3.2's allergen_tags enum"
        )
        assert isinstance(canonical["canonical_order"], list)
        assert len(canonical["canonical_order"]) == 3


class TestSubmitReviewStatementSafety:
    def test_allergen_statement_incomplete_rejected(self, api):
        """PRD §3.6: "Two statement checks then run against the canonical
        forms of §3.2: a `contains_text` that does not equal the canonical
        allergen statement for the locked recipe's lines is rejected with
        `ERR_ALLERGEN_STATEMENT_INCOMPLETE`, and an
        `ingredient_statement_text` that does not equal the canonical
        descending-weight ordering is rejected with
        `ERR_INGREDIENT_ORDER_VIOLATION`."
        PRD §3.2: "The returned `contains_text` is built from the distinct
        allergen tags in the order they first appear along the canonical line
        order, rendered as the literal prefix `Contains: `, the comma-joined
        tags, and a closing period; when no line carries any allergen tag, the
        canonical statement is exactly `Contains: None.`"

        Design: Corner/validations/val_allergen_statement_incomplete_rejected
        """
        client = create_client()
        product = create_product(client)
        flour = create_ingredient(client, name="Wheat Flour",
                                  allergen_tags=["WHEAT"])
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": flour["id"], "quantity_g": 100}])
        compute_panel(recipe["id"], method="DATABASE")
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        label = create_label_draft(
            product["id"], racc["id"],
            ingredient_statement_text="Wheat Flour",
            contains_text="Contains: None.")

        resp = api.submit_label_review(label["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_STATEMENT_INCOMPLETE,
                       expected_status=422)
        assert get_label_version(label["id"])["review_status"] == "DRAFT", (
            "a rejected submission leaves the label in DRAFT"
        )

    def test_ingredient_order_violation_rejected(self, api):
        """PRD §3.6: "Two statement checks then run against the canonical
        forms of §3.2: a `contains_text` that does not equal the canonical
        allergen statement for the locked recipe's lines is rejected with
        `ERR_ALLERGEN_STATEMENT_INCOMPLETE`, and an
        `ingredient_statement_text` that does not equal the canonical
        descending-weight ordering is rejected with
        `ERR_INGREDIENT_ORDER_VIOLATION`."
        PRD §3.2: "The canonical order sorts the recipe's lines by
        `quantity_g` descending, breaks ties by the ingredient's `created_at`
        ascending, and breaks any remaining tie by ingredient `name`
        ascending."

        Design: Corner/validations/val_ingredient_order_violation_rejected
        """
        client = create_client()
        product = create_product(client)
        flour = create_ingredient(client, name="Wheat Flour",
                                  allergen_tags=["WHEAT"])
        sugar = create_ingredient(client, name="Sugar")
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": flour["id"], "quantity_g": 120},
             {"ingredient_id": sugar["id"], "quantity_g": 40}])
        compute_panel(recipe["id"], method="DATABASE")
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        # Out-of-order statement; the Contains text is discovered from the
        # computed-statement endpoint so only the ordering check can fire.
        label = create_label_draft(
            product["id"], racc["id"],
            ingredient_statement_text="Sugar, Wheat Flour",
            statement_recipe_id=recipe["id"])

        resp = api.submit_label_review(label["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INGREDIENT_ORDER_VIOLATION,
                       expected_status=422)


class TestSubmitReviewStateGates:
    def test_state_error_precedes_statement_safety(self, api):
        """PRD §2.8: "Every request is validated against a fixed priority
        sequence, and the first failing check determines the error returned."
        PRD §2.8: "4. **State and concurrency.** Optimistic-concurrency
        mismatches (`ERR_STALE_VERSION`), from-state preconditions of every
        action (`ERR_INVALID_STATE_TRANSITION`), lab double-decision
        (`ERR_LAB_REVIEW_ALREADY_DECIDED`), recipe-lock requirements
        (`ERR_RECIPE_NOT_LOCKED`), panel currency (`ERR_PANEL_NOT_CURRENT`),
        review-state requirements (`ERR_LABEL_NOT_IN_REVIEW`,
        `ERR_LABEL_NOT_APPROVED`), and content readiness
        (`ERR_CONTENT_REVISION_REQUIRED`)."
        PRD §2.8: "5. **Statement safety.** The canonical allergen statement
        check (`ERR_ALLERGEN_STATEMENT_INCOMPLETE`) and the canonical
        ingredient-ordering check (`ERR_INGREDIENT_ORDER_VIOLATION`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_review_state_beats_safety_rejected
        """
        client = create_client()
        product = create_product(client)
        flour = create_ingredient(client, name="Wheat Flour",
                                  allergen_tags=["WHEAT"])
        # The recipe is never locked; the drafted Contains text omits WHEAT.
        create_recipe(product["id"], client["id"],
                      [{"ingredient_id": flour["id"], "quantity_g": 120}])
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        label = create_label_draft(
            product["id"], racc["id"],
            ingredient_statement_text="Wheat Flour",
            contains_text="Contains: None.")

        resp = api.submit_label_review(label["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_RECIPE_NOT_LOCKED, expected_status=409)
        assert get_label_version(label["id"])["review_status"] == "DRAFT", (
            "no transition occurred"
        )

    def test_statement_safety_fires_once_state_passes(self, api):
        """PRD §2.8: "Every request is validated against a fixed priority
        sequence, and the first failing check determines the error returned."
        PRD §3.6: "Two statement checks then run against the canonical forms
        of §3.2: a `contains_text` that does not equal the canonical allergen
        statement for the locked recipe's lines is rejected with
        `ERR_ALLERGEN_STATEMENT_INCOMPLETE`, and an
        `ingredient_statement_text` that does not equal the canonical
        descending-weight ordering is rejected with
        `ERR_INGREDIENT_ORDER_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/submit_review_state_beats_safety_rejected
        """
        client = create_client()
        product = create_product(client)
        flour = create_ingredient(client, name="Wheat Flour",
                                  allergen_tags=["WHEAT"])
        recipe = create_recipe(product["id"], client["id"],
                               [{"ingredient_id": flour["id"], "quantity_g": 120}])
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        label = create_label_draft(
            product["id"], racc["id"],
            ingredient_statement_text="Wheat Flour",
            contains_text="Contains: None.")

        # Control: once the recipe is LOCKED and a CURRENT panel exists, the
        # same draft reaches the statement-safety check and fails there.
        lock_recipe(recipe["id"], client["id"])
        compute_panel(recipe["id"], method="DATABASE")
        resp = api.submit_label_review(label["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_STATEMENT_INCOMPLETE,
                       expected_status=422)

    def test_panel_not_current_on_submit_rejected(self, api):
        """PRD §3.6: "The label must be in `DRAFT` review status — anything
        else is rejected with `ERR_INVALID_STATE_TRANSITION` — the product
        must have a currently `LOCKED` recipe (`ERR_RECIPE_NOT_LOCKED`), and a
        `CURRENT` panel must exist for that recipe whose method matches the
        label's `nutrient_basis` (`ERR_PANEL_NOT_CURRENT`)."
        PRD §3.2: "The cascade that follows is what makes the lock decisive:
        any sibling recipe of the same product that was `LOCKED` flips to
        `SUPERSEDED`, that superseded recipe's `CURRENT` nutrient panels flip
        to `STALE`, every claim assessment on that product's labels whose
        basis panel just went stale flips to `SUSPENDED`, and each affected
        label version's `content_status` is recomputed to `NEEDS_REVISION`."

        Design: Corner/validations/val_panel_not_current_on_submit_rejected
        """
        ws = setup_wafer_workspace()
        # A newer formulation locks, superseding v1 and staling its panel.
        recipe_v2 = create_recipe(ws["product"]["id"], ws["client"]["id"],
                                  [{"ingredient_id": ws["wafer"]["id"],
                                    "quantity_g": 90}], name="v2")
        lock_recipe(recipe_v2["id"], ws["client"]["id"])

        resp = api.submit_label_review(ws["label"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_PANEL_NOT_CURRENT, expected_status=409)


class TestFormatCompliance:
    def test_type_size_below_min_violation(self, api):
        """PRD §3.6: "The minimum type size comes from `pdp_area_sq_in`: a
        principal display panel of at most 5.0 square inches requires 0.03125
        inches, and a larger panel requires 0.0625 inches."
        PRD §3.6: "A `declared_format` outside the allowed set records the
        violation `FORMAT_NOT_ALLOWED_FOR_PACKAGE`; a `declared_type_size_in`
        below the tier minimum records `TYPE_SIZE_BELOW_MIN`."
        PRD §3.6: "The check persists its `allowed_formats`,
        `min_type_size_in`, and the `violations` list, and its `result` is
        `PASS` exactly when the violations list is empty, otherwise `FAIL`."

        Design: Corner/calculations/calc_format_type_size_violation
        """
        ws = setup_wafer_workspace(
            label_overrides={"declared_format": "TABULAR",
                             "declared_type_size_in": 0.03125})
        submit_label(ws["label"]["id"])

        checks, meta = validate_paginated(
            api.list_format_checks(ws["label"]["id"], ADMIN))
        assert meta["total_count"] == 1
        check = checks[0]
        assert check["min_type_size_in"] == 0.0625, "pdp 6.0 > 5.0"
        assert check["result"] == "FAIL"
        assert check["violations"] == ["TYPE_SIZE_BELOW_MIN"], (
            "TABULAR is allowed at 30 sq in; only the type size is violated"
        )

    def test_exact_12sqin_admits_linear(self, api):
        """PRD §3.6: "The allowed format set comes from
        `total_surface_area_sq_in`: a package of at most 12.0 square inches
        may carry only `LINEAR`; a package greater than 12.0 and at most 40.0
        square inches may carry `SIMPLIFIED`, `TABULAR`, or
        `STANDARD_VERTICAL`; a package greater than 40.0 square inches must
        carry `STANDARD_VERTICAL`."
        PRD §3.6: "The check persists its `allowed_formats`,
        `min_type_size_in`, and the `violations` list, and its `result` is
        `PASS` exactly when the violations list is empty, otherwise `FAIL`."

        Design: Difficulty/boundary_precision_check/boundary_small_package_format_at_exact_12sqin
        """
        ws = setup_wafer_workspace(
            product_overrides={"total_surface_area_sq_in": 12.0,
                               "pdp_area_sq_in": 4.0},
            label_overrides={"declared_format": "LINEAR",
                             "declared_type_size_in": 0.03125})
        submit_label(ws["label"]["id"])

        checks, _meta = validate_paginated(
            api.list_format_checks(ws["label"]["id"], ADMIN))
        check = checks[0]
        assert check["allowed_formats"] == ["LINEAR"], (
            "area exactly 12.0 qualifies for LINEAR (at most 12.0)"
        )
        assert check["min_type_size_in"] == 0.03125, "pdp exactly 5.0 or less"
        assert check["violations"] == []
        assert check["result"] == "PASS"

    def test_just_above_12sqin_rejects_linear(self, api):
        """PRD §3.6: "The allowed format set comes from
        `total_surface_area_sq_in`: a package of at most 12.0 square inches
        may carry only `LINEAR`; a package greater than 12.0 and at most 40.0
        square inches may carry `SIMPLIFIED`, `TABULAR`, or
        `STANDARD_VERTICAL`; a package greater than 40.0 square inches must
        carry `STANDARD_VERTICAL`."
        PRD §3.6: "A `declared_format` outside the allowed set records the
        violation `FORMAT_NOT_ALLOWED_FOR_PACKAGE`; a `declared_type_size_in`
        below the tier minimum records `TYPE_SIZE_BELOW_MIN`."

        Design: Difficulty/boundary_precision_check/boundary_small_package_format_at_exact_12sqin
        """
        ws = setup_wafer_workspace(
            product_overrides={"total_surface_area_sq_in": 12.5,
                               "pdp_area_sq_in": 4.0},
            label_overrides={"declared_format": "LINEAR",
                             "declared_type_size_in": 0.03125})
        submit_label(ws["label"]["id"])

        checks, _meta = validate_paginated(
            api.list_format_checks(ws["label"]["id"], ADMIN))
        check = checks[0]
        assert check["result"] == "FAIL"
        assert "FORMAT_NOT_ALLOWED_FOR_PACKAGE" in check["violations"], (
            "12.5 > 12.0: LINEAR is not in the allowed set"
        )
