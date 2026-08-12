"""Recipes, their revisions, and the label artwork regime."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_recipe,
    build_sourced_run,
    create_account_payload,
    create_label_approval_payload,
    create_recipe_payload,
    assert_liters,
    make_platform_admin_headers,
    read_batch,
    read_recipe,
    read_run,
    set_clock,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
SALES = TEST_USERS["sales_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_create_recipe_opens_at_revision_one_with_no_active_label(api):
    """PRD 3.1: "A newly registered recipe has `recipe_version_number` set to 1 and
    `active_label_approval_id` set to null."
    PRD 2.4: "Seventeen of the eighteen resource families also carry `updated_at`,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row."

    Design: Corner/entities/create_recipe_returns_every_declared_field_at_version_one
    """
    payload = create_recipe_payload(
        name="Yuzu Sparkler",
        style="BOTANICAL_SODA",
        target_ph_ceiling=3.4,
        planned_f1_days=6,
        planned_f2_days=2,
        base_gravity_brix=6.5,
        intended_abv_class="NON_ALCOHOLIC",
    )
    recipe = validate_success(api.create_recipe(payload, OPERATOR), 201)

    assert_recipe(recipe)
    assert recipe["recipe_version_number"] == 1, "a newly registered recipe opens at revision 1"
    assert recipe["version"] == 1, "the concurrency token starts at 1 on creation"
    assert recipe["active_label_approval_id"] is None
    assert recipe["style"] == "BOTANICAL_SODA"
    assert abs(recipe["target_ph_ceiling"] - 3.4) < 1e-9


def test_optional_recipe_and_account_inputs_take_their_declared_defaults(api):
    """PRD 3.1: "Two further inputs are optional: `f2_added_sugar_g_per_l`, the grams
    of priming sugar per liter dosed at secondary fermentation, which defaults to 0,
    and `pasteurization_required`, which defaults to false and, when true, forces
    every packaging run of the recipe to be flash-pasteurized."
    PRD 3.9: "Two inputs are optional: `credit_terms_days`, the net payment terms in
    whole days, which defaults to 30, and `alcoholic_license_on_file`, which defaults
    to false and decides whether the account may receive alcoholic product at all."

    Design: Corner/entities/recipe_optional_fields_take_their_declared_defaults
    """
    recipe = validate_success(
        api.create_recipe(create_recipe_payload(name="Plain Kombucha"), OPERATOR), 201
    )
    account = validate_success(
        api.create_account(
            create_account_payload(account_name="Default Terms Co", credit_limit=1000.0),
            SALES,
        ),
        201,
    )

    assert recipe["f2_added_sugar_g_per_l"] == 0
    assert recipe["pasteurization_required"] is False
    assert account["credit_terms_days"] == 30
    assert account["status"] == "ONBOARDING", "an account opens in status ONBOARDING"
    assert account["alcoholic_license_on_file"] is False


def test_reading_an_unknown_recipe_answers_the_production_not_found_code(api):
    """PRD 2.7: "`ERR_PRODUCTION_RESOURCE_NOT_FOUND` (HTTP 404) covers a missing
    `Recipe`, `LabelApproval`, `ScobyCulture`, `Vessel`, `IngredientLot`, `Batch` or
    `BatchIngredientUse`."

    Design: Corner/entities/get_recipe_with_an_unknown_id_returns_not_found
    """
    response = api.get_recipe(NON_EXISTENT_UUID, OPERATOR)
    validate_error(response, ApiErrorId.ERR_PRODUCTION_RESOURCE_NOT_FOUND.value, 404)


def test_platform_admin_may_not_approve_the_label_revision_it_submitted(api):
    """PRD 2.1: "A label revision may not be approved by the same `X-User-ID` that
    submitted it."
    PRD 2.1: "`PlatformAdmin` is a hierarchical override for the role check only — it
    does **not** bypass any of these three comparisons."

    Design: Corner/rbac/platform_admin_is_still_bound_by_the_label_segregation_rule
    """
    admin = make_platform_admin_headers("admin-1")
    recipe = validate_success(api.create_recipe(create_recipe_payload(), OPERATOR), 201)
    label = validate_success(
        api.create_label_approval(
            create_label_approval_payload(
                recipe["id"], abv_class="NON_ALCOHOLIC", pasteurized=False
            ),
            admin,
        ),
        201,
    )
    validate_success(api.submit_label_approval(label["id"], admin))

    response = api.approve_label_approval(label["id"], admin)
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after = validate_success(api.list_recipe_label_approvals(recipe["id"], admin))
    revision = [row for row in after if row["id"] == label["id"]][0]
    assert revision["status"] == "SUBMITTED", "a refused approval leaves the revision SUBMITTED"
    assert read_recipe(api, recipe["id"])["active_label_approval_id"] is None


def test_revising_a_recipe_bumps_the_number_and_stales_the_approved_label(api):
    """PRD 3.1: "Revising a recipe is a deliberately disruptive act. A revision takes
    an optional `change_note`, increments `recipe_version_number` by 1, and then runs
    the four-hop recipe revision cascade described in section 2.12: every `APPROVED`
    label revision of that recipe drops to `STALE` with `stale_reason`
    `RECIPE_REVISED`, `active_label_approval_id` is nulled, every packaging run of
    that recipe still in `DRAFT` or `SOURCED` against a now-stale revision is driven
    to `ABORTED`, and each aborted run hands its drawn liters back to its source
    batches."

    Design: Difficulty/transitive_cascade/recipe_revision_stales_the_label_and_aborts_the_sourced_run
    """
    built = build_sourced_run(api, liters_drawn=120.0, run_code="PR-8", vessel_code="FV-8")
    set_clock(api, "2026-05-10T00:00:00.000Z")

    revised = validate_success(
        api.revise_recipe(built["recipe"]["id"], {"change_note": "Ginger dosing raised"}, OPERATOR)
    )

    assert revised["recipe_version_number"] == 2
    assert revised["active_label_approval_id"] is None

    labels = validate_success(
        api.list_recipe_label_approvals(built["recipe"]["id"], COMPLIANCE)
    )
    revision = [row for row in labels if row["id"] == built["label"]["id"]][0]
    assert revision["status"] == "STALE"
    assert revision["stale_reason"] == "RECIPE_REVISED"


def test_revising_a_recipe_aborts_the_sourced_run_and_returns_its_drawn_liters(api):
    """PRD 2.12: "For each run aborted by hop 3, every source draw is returned — the
    batch's `drawn_liters` is decreased and its `remaining_liters` increased by the
    drawn liters, and the batch's `version` is incremented."
    PRD 2.11: "For every batch, `pitched_liters` always equals `remaining_liters` plus
    `drawn_liters` plus `loss_liters`."

    Design: Difficulty/transitive_cascade/recipe_revision_stales_the_label_and_aborts_the_sourced_run
    """
    built = build_sourced_run(api, liters_drawn=120.0, run_code="PR-8", vessel_code="FV-8")
    set_clock(api, "2026-05-10T00:00:00.000Z")

    validate_success(
        api.revise_recipe(built["recipe"]["id"], {"change_note": "Ginger dosing raised"}, OPERATOR)
    )

    run = read_run(api, built["run"]["id"])
    assert run["status"] == "ABORTED", "an in-flight SOURCED run may not print a stale label"
    assert run["source_batch_count"] == 1, "source_draws are retained for audit"

    batch = read_batch(api, built["batch"]["id"])
    assert_liters(batch["drawn_liters"], 0.0, "drawn_liters after the abort")
    assert_liters(batch["remaining_liters"], 400.0, "remaining_liters after the abort")
    assert_liters(batch["loss_liters"], 0.0, "loss_liters after the abort")
