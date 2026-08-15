"""Recipe lock and lab review state machines, initial states, and the two
depth-4 freshness cascades (recipe lock and lab validation)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    compute_panel,
    create_and_lock_recipe,
    create_claim,
    create_client,
    create_ingredient,
    create_label_draft,
    create_market_variant,
    create_product,
    create_racc_assignment,
    create_recipe,
    get_label_version,
    get_recipe,
    list_claims,
    lock_recipe,
    make_client_rep_headers,
    review_lab_analysis,
    setup_cookie_workspace,
    setup_lab_claim_workspace,
    submit_lab_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]
REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def _lab_analyses_by_id(recipe_id):
    data, _meta = validate_paginated(api_client.list_lab_analyses(recipe_id, ADMIN))
    return {a["id"]: a for a in data}


class TestRecipeLock:
    def test_recipe_lock_from_locked_returns_invalid_state(self, api):
        """PRD §3.2: "A `ClientRep` locks a recipe that is currently `DRAFT` —
        locking from any other status is rejected with
        `ERR_INVALID_STATE_TRANSITION` — and the lock sets the recipe's
        `status` to `LOCKED` and increments its `version`."

        Design: Corner/state_machines/sm_recipe_lock_from_locked_returns_invalid_state
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": wafer["id"], "quantity_g": 100}])

        resp = api.lock_recipe(recipe["id"],
                               make_client_rep_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)
        assert get_recipe(recipe["id"])["status"] == "LOCKED", (
            "no supersede side effects fire on the rejected lock"
        )


class TestLabReview:
    def test_lab_review_terminal_lockdown(self, api):
        """PRD §3.3: "A second decision attempt on an analysis that has
        already left `SUBMITTED` is rejected with
        `ERR_LAB_REVIEW_ALREADY_DECIDED`."
        PRD §3.3: "Rejection is simple: the reviewer stamps the decision,
        `reviewed_by` records the reviewer's `X-User-ID`, and the analysis
        settles in `REJECTED`, a terminal state."

        Design: Corner/state_machines/sm_lab_review_terminal_lockdown
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_and_lock_recipe(
            product["id"], client["id"],
            [{"ingredient_id": wafer["id"], "quantity_g": 100}])
        lab = submit_lab_analysis(recipe["id"], client["id"], lab_report_ref="LR-1")
        decided = review_lab_analysis(lab["id"], outcome="REJECTED")
        assert decided["status"] == "REJECTED"
        assert decided["reviewed_by"] == "reviewer-1"

        resp = api.review_lab_analysis(lab["id"], {"outcome": "VALIDATED"},
                                       REVIEWER)
        validate_error(resp, ApiErrorId.ERR_LAB_REVIEW_ALREADY_DECIDED,
                       expected_status=409)
        analyses = _lab_analyses_by_id(recipe["id"])
        assert analyses[lab["id"]]["status"] == "REJECTED"


class TestInitialStates:
    def test_entity_initial_states(self, api):
        """PRD §3.2: "A new recipe begins life in `DRAFT` status."
        PRD §3.6: "The new draft initializes with `review_status` `DRAFT`,
        `release_status` `NOT_RELEASED`, `review_round` 0, and `prepared_by`
        set to the creating analyst's `X-User-ID`; the product's `version`
        increments as part of the same write."
        PRD §3.8: "A new variant starts in `DRAFT` status."
        PRD §3.7: "That derived flag follows one rule everywhere:
        `content_status` is `NEEDS_REVISION` whenever any claim on the label
        is `SUSPENDED`, or the product's locked recipe has changed out from
        under the label's pinned basis, or the pinned panel snapshot has gone
        `STALE` — and it is `READY` when none of those hold."

        Design: Corner/state_machines/sm_entity_initial_states
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_recipe(product["id"], client["id"],
                               [{"ingredient_id": wafer["id"], "quantity_g": 100}])
        assert recipe["status"] == "DRAFT", "a new recipe begins life in DRAFT"

        recipe = lock_recipe(recipe["id"], client["id"])
        compute_panel(recipe["id"], method="DATABASE")
        racc = create_racc_assignment(product["id"], market_code="US_FDA")
        label = create_label_draft(product["id"], racc["id"],
                                   statement_recipe_id=recipe["id"])
        assert label["review_status"] == "DRAFT"
        assert label["release_status"] == "NOT_RELEASED"
        assert label["content_status"] == "READY"
        assert label["review_round"] == 0
        assert label["prepared_by"] == "analyst-1"

        variant = create_market_variant(label["id"], market_code="CA_CFIA",
                                        effective_start="2026-09-01T00:00:00Z")
        assert variant["status"] == "DRAFT"


class TestRecipeLockCascade:
    def test_lock_supersedes_sibling_and_stales_panel(self, api):
        """PRD §3.2: "A `ClientRep` locks a recipe that is currently `DRAFT` —
        locking from any other status is rejected with
        `ERR_INVALID_STATE_TRANSITION` — and the lock sets the recipe's
        `status` to `LOCKED` and increments its `version`."
        PRD §3.2: "The cascade that follows is what makes the lock decisive:
        any sibling recipe of the same product that was `LOCKED` flips to
        `SUPERSEDED`, that superseded recipe's `CURRENT` nutrient panels flip
        to `STALE`, every claim assessment on that product's labels whose
        basis panel just went stale flips to `SUSPENDED`, and each affected
        label version's `content_status` is recomputed to `NEEDS_REVISION`."

        Design: Difficulty/transitive_cascade/cascade_recipe_lock_depth4
        """
        ws = setup_cookie_workspace(submit=True)
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["status"] == "ELIGIBLE"

        recipe_v2 = create_recipe(
            ws["product"]["id"], ws["client"]["id"],
            [{"ingredient_id": ws["flour"]["id"], "quantity_g": 130},
             {"ingredient_id": ws["sugar"]["id"], "quantity_g": 30}],
            name="v2")
        lock_recipe(recipe_v2["id"], ws["client"]["id"])

        assert get_recipe(ws["recipe"]["id"])["status"] == "SUPERSEDED", (
            "hop 1: v1 superseded because v2 locked"
        )
        panels, _meta = validate_paginated(
            api.list_nutrient_panels(ws["recipe"]["id"], ADMIN))
        assert panels[0]["id"] == ws["panel"]["id"]
        assert panels[0]["status"] == "STALE", (
            "hop 2: the superseded recipe's CURRENT panel goes STALE"
        )

    def test_lock_cascade_suspends_claims_and_flags_label(self, api):
        """PRD §3.2: "The cascade that follows is what makes the lock
        decisive: any sibling recipe of the same product that was `LOCKED`
        flips to `SUPERSEDED`, that superseded recipe's `CURRENT` nutrient
        panels flip to `STALE`, every claim assessment on that product's
        labels whose basis panel just went stale flips to `SUSPENDED`, and
        each affected label version's `content_status` is recomputed to
        `NEEDS_REVISION`."
        PRD §3.7: "That derived flag follows one rule everywhere:
        `content_status` is `NEEDS_REVISION` whenever any claim on the label
        is `SUSPENDED`, or the product's locked recipe has changed out from
        under the label's pinned basis, or the pinned panel snapshot has gone
        `STALE` — and it is `READY` when none of those hold."

        Design: Difficulty/transitive_cascade/cascade_recipe_lock_depth4
        """
        ws = setup_cookie_workspace(submit=True)
        claim = create_claim(ws["label"]["id"], "LOW_FAT")
        assert claim["status"] == "ELIGIBLE"

        recipe_v2 = create_recipe(
            ws["product"]["id"], ws["client"]["id"],
            [{"ingredient_id": ws["flour"]["id"], "quantity_g": 130},
             {"ingredient_id": ws["sugar"]["id"], "quantity_g": 30}],
            name="v2")
        lock_recipe(recipe_v2["id"], ws["client"]["id"])

        claims = list_claims(ws["label"]["id"])
        assert claims[0]["status"] == "SUSPENDED", (
            "hop 3: the claim's basis panel went stale"
        )
        assert get_label_version(ws["label"]["id"])["content_status"] == (
            "NEEDS_REVISION"
        ), "hop 4: the label recompute is caused by the claim flip"


class TestLabValidationCascade:
    def test_validation_supersedes_analysis_and_stales_panel(self, api):
        """PRD §3.3: "The validating reviewer's identity lands in
        `reviewed_by`; the recipe's `latest_validated_lab_analysis_id` is
        repointed to this analysis; any other `VALIDATED` analysis of the same
        recipe is moved by the system to `SUPERSEDED`; every lab-method panel
        whose `basis_lab_analysis_id` names the superseded analysis flips to
        `STALE`; claim assessments whose `basis_panel_id` went stale flip to
        `SUSPENDED`; and every label version carrying a newly suspended claim
        has its `content_status` recomputed to `NEEDS_REVISION`."

        Design: Difficulty/transitive_cascade/cascade_lab_validation_depth4
        """
        ws = setup_lab_claim_workspace()
        lab2 = submit_lab_analysis(
            ws["recipe"]["id"], ws["client"]["id"], lab_report_ref="LR-101",
            kcal_per_100g=351.0, fat_g_per_100g=1.5, sodium_mg_per_100g=3.6,
            carb_g_per_100g=80.1, sugar_g_per_100g=24.1)
        review_lab_analysis(lab2["id"], outcome="VALIDATED")

        analyses = _lab_analyses_by_id(ws["recipe"]["id"])
        assert analyses[ws["lab1"]["id"]]["status"] == "SUPERSEDED", (
            "hop 1: lab1 is superseded by lab2's validation"
        )
        panel1 = validate_success(api.get_nutrient_panel(ws["panel"]["id"], ADMIN))
        assert panel1["status"] == "STALE", (
            "hop 2: the panel is staled because its basis analysis was "
            "superseded"
        )

    def test_validation_cascade_suspends_claim_and_flags_label(self, api):
        """PRD §3.3: "The validating reviewer's identity lands in
        `reviewed_by`; the recipe's `latest_validated_lab_analysis_id` is
        repointed to this analysis; any other `VALIDATED` analysis of the same
        recipe is moved by the system to `SUPERSEDED`; every lab-method panel
        whose `basis_lab_analysis_id` names the superseded analysis flips to
        `STALE`; claim assessments whose `basis_panel_id` went stale flip to
        `SUSPENDED`; and every label version carrying a newly suspended claim
        has its `content_status` recomputed to `NEEDS_REVISION`."

        Design: Difficulty/transitive_cascade/cascade_lab_validation_depth4
        """
        ws = setup_lab_claim_workspace()
        assert ws["claim"]["status"] == "ELIGIBLE"
        lab2 = submit_lab_analysis(
            ws["recipe"]["id"], ws["client"]["id"], lab_report_ref="LR-101",
            kcal_per_100g=351.0, fat_g_per_100g=1.5, sodium_mg_per_100g=3.6,
            carb_g_per_100g=80.1, sugar_g_per_100g=24.1)
        review_lab_analysis(lab2["id"], outcome="VALIDATED")

        claims = list_claims(ws["label"]["id"])
        assert claims[0]["status"] == "SUSPENDED", (
            "hop 3: the claim's basis panel went stale"
        )
        assert get_label_version(ws["label"]["id"])["content_status"] == (
            "NEEDS_REVISION"
        ), "hop 4: the label recompute is caused by the claim flip"
