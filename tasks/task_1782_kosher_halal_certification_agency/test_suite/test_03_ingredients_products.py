"""Ingredient review loop, change notices, and product recipe rules."""
from test_helpers import (
    ApiErrorId,
    create_approved_ingredient,
    create_draft_product,
    create_prospect_client,
    create_submitted_ingredient,
    make_client_contact_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIngredientReviewLoop:
    def test_ingredient_change_notice_reapproval_cycle_traversed_twice(
            self, api, reviewer_headers):
        """PRD section 3.3: "The client files a change notice on an `APPROVED`
        ingredient, carrying the free-text `change_summary`; the text is stored
        on the ingredient record (it is null until the first notice) and the
        ingredient moves to `CHANGE_PENDING`." PRD section 3.3: "The client then
        resubmits (`CHANGE_PENDING` → `UNDER_REVIEW`), and the reviewer decides
        again."

        Design: Difficulty/non_linear_state_machine/ingredient_change_notice_reapproval_cycle
        """
        client = create_prospect_client(legal_name="Cycle Co")
        cc = make_client_contact_headers(client["id"])
        ing = create_approved_ingredient(client["id"], name="IngC1")
        assert ing["status"] == "APPROVED"

        noticed = validate_success(
            api.file_change_notice(ing["id"], "supplier plant move", cc), 201)
        assert noticed["status"] == "CHANGE_PENDING"
        assert noticed["change_summary"] == "supplier plant move"

        resubmitted = validate_success(api.resubmit_ingredient(ing["id"], cc))
        assert resubmitted["status"] == "UNDER_REVIEW"

        reapproved = validate_success(
            api.approve_ingredient(ing["id"], reviewer_headers))
        assert reapproved["status"] == "APPROVED"

        noticed2 = validate_success(
            api.file_change_notice(ing["id"], "second formulation tweak", cc), 201)
        assert noticed2["status"] == "CHANGE_PENDING", (
            "the loop is cyclic: a second change notice must succeed")
        assert noticed2["change_summary"] == "second formulation tweak"

    def test_ingredient_change_summary_null_until_first_notice(
            self, api, reviewer_headers):
        """PRD section 3.3: "the text is stored on the ingredient record (it is
        null until the first notice) and the ingredient moves to
        `CHANGE_PENDING`."

        Design: Difficulty/non_linear_state_machine/ingredient_change_notice_reapproval_cycle
        """
        client = create_prospect_client(legal_name="Cycle Co 2")
        cc = make_client_contact_headers(client["id"])
        ing = create_approved_ingredient(client["id"], name="IngC2")
        assert ing.get("change_summary") is None, (
            "change_summary is null until the first change notice")

        noticed = validate_success(
            api.file_change_notice(ing["id"], "supplier plant move", cc), 201)
        assert noticed["change_summary"] == "supplier plant move"
        assert noticed["status"] == "CHANGE_PENDING"

        validate_success(api.resubmit_ingredient(ing["id"], cc))
        reapproved = validate_success(
            api.approve_ingredient(ing["id"], reviewer_headers))
        assert reapproved["status"] == "APPROVED", (
            "re-approval after a change notice restores APPROVED")


class TestIngredientStateGates:
    def test_ingredient_start_review_from_approved_rejected(
            self, api, reviewer_headers):
        """PRD section 3.3: "A `CertificationReviewer` starts the review
        (`SUBMITTED` → `UNDER_REVIEW`)". PRD section 3.3: "Wrong-state calls
        surface `ERR_INGREDIENT_INVALID_STATE`."

        Design: Corner/state_machines/ingredient_start_review_from_approved_rejected
        """
        client = create_prospect_client(legal_name="SM1 Co")
        ing = create_approved_ingredient(client["id"], name="I1",
                                         source_category="MINERAL")
        assert ing["status"] == "APPROVED"
        resp = api.start_ingredient_review(ing["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_INGREDIENT_INVALID_STATE)

    def test_change_notice_on_submitted_ingredient_rejected(self, api):
        """PRD section 3.3: "The client files a change notice on an `APPROVED`
        ingredient". PRD section 3.3: "Wrong-state calls surface
        `ERR_INGREDIENT_INVALID_STATE`."

        Design: Corner/state_machines/change_notice_on_submitted_ingredient_rejected
        """
        client = create_prospect_client(legal_name="SM2 Co")
        cc = make_client_contact_headers(client["id"])
        ing = create_submitted_ingredient(client["id"], name="I2")
        assert ing["status"] == "SUBMITTED"
        resp = api.file_change_notice(ing["id"], "too early", cc)
        validate_error(resp, ApiErrorId.ERR_INGREDIENT_INVALID_STATE)

    def test_animal_ingredient_without_species_documentation_rejected(
            self, api, reviewer_headers):
        """PRD section 3.3: "Approving an ingredient whose `source_category` is
        `ANIMAL` requires `has_species_documentation` to be true — species and
        slaughter documentation is mandatory for animal-derived approvals —
        else `ERR_ANIMAL_SOURCE_DOCUMENTATION_REQUIRED` (HTTP 422)."

        Design: Corner/validations/animal_ingredient_without_species_documentation_rejected
        """
        client = create_prospect_client(legal_name="An Co",
                                        certification_scheme="HALAL")
        ing = create_submitted_ingredient(
            client["id"], name="Gelatin", source_category="ANIMAL",
            has_species_documentation=False)
        validate_success(api.start_ingredient_review(ing["id"], reviewer_headers))
        resp = api.approve_ingredient(ing["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_SOURCE_DOCUMENTATION_REQUIRED)
        after = validate_success(api.get_ingredient(ing["id"], reviewer_headers))
        assert after["status"] == "UNDER_REVIEW", (
            "a rejected approval must not move the ingredient")


class TestProductRecipes:
    def test_link_unapproved_ingredient_rejected(self, api, reviewer_headers):
        """PRD section 3.4: "Additional ingredients are linked one at a time by
        the client with a payload containing the `ingredient_id`, subject to the
        same same-client and `APPROVED` checks".

        Design: Corner/validations/link_unapproved_ingredient_rejected
        """
        client = create_prospect_client(legal_name="LU Co")
        cc = make_client_contact_headers(client["id"])
        ing = create_submitted_ingredient(client["id"], name="IU")
        validate_success(api.start_ingredient_review(ing["id"], reviewer_headers))
        product = create_draft_product(client["id"], [], name="PLu")
        resp = api.add_product_ingredient(product["id"], ing["id"], cc)
        validate_error(resp, ApiErrorId.ERR_INGREDIENT_NOT_APPROVED)

    def test_duplicate_junction_rejected(self, api):
        """PRD section 3.4: "an ingredient that already has a non-`REMOVED`
        junction on this product is rejected with
        `ERR_DUPLICATE_PRODUCT_INGREDIENT`."

        Design: Corner/validations/duplicate_junction_rejected
        """
        client = create_prospect_client(legal_name="DJ Co")
        cc = make_client_contact_headers(client["id"])
        ing = create_approved_ingredient(client["id"], name="IDJ")
        product = create_draft_product(client["id"], [ing["id"]], name="PDJ")
        resp = api.add_product_ingredient(product["id"], ing["id"], cc)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PRODUCT_INGREDIENT)

    def test_submit_review_without_ingredients_rejected(self, api):
        """PRD section 3.4: "Submitting a product for review (`DRAFT` →
        `IN_REVIEW`) requires at least one junction in `ACTIVE` status; an empty
        recipe yields `ERR_PRODUCT_HAS_NO_INGREDIENTS` (HTTP 422)."

        Design: Corner/validations/submit_review_without_ingredients_rejected
        """
        client = create_prospect_client(legal_name="NI Co")
        cc = make_client_contact_headers(client["id"])
        product = create_draft_product(client["id"], [], name="PNi")
        resp = api.submit_product_review(product["id"], cc)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_HAS_NO_INGREDIENTS)

    def test_certify_eligible_on_draft_product_rejected(
            self, api, reviewer_headers):
        """PRD section 3.4: "A `CertificationReviewer` then declares the product
        certification-eligible (`IN_REVIEW` → `CERTIFIABLE`)". PRD section 2.8:
        "Only then are entity-state gates evaluated (the family of
        `ERR_*_INVALID_STATE` errors)".

        Design: Corner/state_machines/certify_eligible_on_draft_product_rejected
        """
        client = create_prospect_client(legal_name="PV Co")
        ing = create_approved_ingredient(client["id"], name="IP")
        product = create_draft_product(client["id"], [ing["id"]], name="PPv")
        assert product["status"] == "DRAFT"
        resp = api.certify_product_eligible(product["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_INVALID_STATE)

    def test_product_junction_double_delete_rejected(self, api,
                                                     reviewer_headers):
        """PRD section 3.4: "re-removing an already-`REMOVED` junction yields
        `ERR_PRODUCT_INGREDIENT_INVALID_STATE`."

        Design: Corner/state_machines/product_junction_double_delete_rejected
        """
        client = create_prospect_client(legal_name="SM10 Co")
        cc = make_client_contact_headers(client["id"])
        ing = create_approved_ingredient(client["id"], name="I10")
        product = create_draft_product(client["id"], [ing["id"]], name="P10")
        junctions, _meta = validate_paginated(
            api.list_product_ingredients(product["id"], cc))
        junction_id = junctions[0]["id"]
        removed = validate_success(api.delete_product_ingredient(junction_id, cc))
        assert removed["status"] == "REMOVED"
        resp = api.delete_product_ingredient(junction_id, cc)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_INGREDIENT_INVALID_STATE)
