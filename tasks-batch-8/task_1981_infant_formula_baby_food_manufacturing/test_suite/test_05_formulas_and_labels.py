"""Formulas and label submissions: creation, the non-linear review/revision
cycles, segregation of duties on approval, and the batches sub-resource
(PRD §2.4, §2.6, §3.3, §3.5, §4)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, assert_formula,
    create_approved_nutrient_profile, create_ingredient, create_draft_formula,
    create_passed_validation,
    make_qa_manager_headers,
)


def _base_formula(users, code):
    """Approved profile + two ingredients + DRAFT formula. Returns formula."""
    profile = create_approved_nutrient_profile(users, profile_code="INF-0-6M")
    ing_a = create_ingredient(users, f"{code}-A", "Ingredient A",
                              "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
    ing_b = create_ingredient(users, f"{code}-B", "Ingredient B",
                              "CARBOHYDRATE", "LOW_RISK", "AMBIENT")
    return create_draft_formula(users, code, f"{code} Product",
                                profile["id"], ing_a["id"], ing_b["id"])


class TestFormulaCreation:
    def test_create_formula_success(self, api, users):
        """PRD §3.3: "The new formula starts in `DRAFT`." PRD §4: "Operations
        that create a new resource — whether a top-level resource or a child
        resource added to a parent's collection — return `201 Created`."

        Design: Corner/endpoints/create_formula_success_201
        """
        res_formula = _base_formula(users, "IF-EP-1")
        assert res_formula["status"] == "DRAFT"
        assert res_formula["formula_code"] == "IF-EP-1"
        assert_formula(res_formula)

    def test_formula_batches_subresource_returns_array(self, api, users):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." The formula's batch
        collection (PRD §4, GET /api/v1/formulas/{id}/batches) is an array,
        empty before any batch exists.

        Design: Corner/endpoints/get_formula_batches_subresource
        """
        formula = _base_formula(users, "CEREAL-SUB")
        res = api.list_formula_batches(formula["id"], users["qm"]["headers"])
        data, _meta = validate_paginated(res)
        assert isinstance(data, list)
        assert data == []


class TestFormulaReviewCycle:
    def test_formula_review_revision_cycle(self, api, users):
        """PRD §3.3: "Submitting a formula for review transitions
        `DRAFT → IN_REVIEW`" and "A formula may instead be returned from
        `IN_REVIEW` to `DRAFT` by a `QA_MANAGER` with no additional
        preconditions." The cycle repeats: a returned formula can be submitted
        again.

        Design: Difficulty/non_linear_state_machine/formula_review_revision_cycle
        """
        formula = _base_formula(users, "IF-CYCLE-1")
        submitted = validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        assert submitted["status"] == "IN_REVIEW"
        returned = validate_success(api.return_formula_for_revision(
            formula["id"], users["qm"]["headers"]))
        assert returned["status"] == "DRAFT"
        resubmitted = validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        assert resubmitted["status"] == "IN_REVIEW"

    def test_formula_version_increments_each_transition(self, api, users):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation, including system-driven state
        transitions and cascades."

        Design: Difficulty/non_linear_state_machine/formula_review_revision_cycle
        """
        formula = _base_formula(users, "IF-CYCLE-2")
        v0 = formula["version"]
        submitted = validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        assert submitted["version"] == v0 + 1
        returned = validate_success(api.return_formula_for_revision(
            formula["id"], users["qm"]["headers"]))
        assert returned["version"] == v0 + 2
        resubmitted = validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        assert resubmitted["version"] == v0 + 3


class TestLabelReviewCycle:
    def _approved_formula(self, api, users, code):
        formula = _base_formula(users, code)
        validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        create_passed_validation(users, formula["id"])
        return validate_success(api.approve_formula(
            formula["id"], users["qm"]["headers"]))

    def test_label_review_revision_cycle(self, api, users):
        """PRD §3.5: "The submission step moves `DRAFT → SUBMITTED`" and
        "A `QA_MANAGER` may also return a submission from `UNDER_REVIEW` to
        `DRAFT` with no preconditions." A returned label can be submitted
        again.

        Design: Difficulty/non_linear_state_machine/label_submission_review_revision_cycle
        """
        formula = self._approved_formula(api, users, "IF-LABEL-CYCLE")
        label = validate_success(api.create_label_submission(
            {"formula_id": formula["id"],
             "submission_type": "NEW_PRODUCT_REGISTRATION",
             "label_text": "Label Cycle Test - Initial label"},
            users["ra1"]["headers"]), 201)
        validate_success(api.submit_label(label["id"], users["ra1"]["headers"]))
        validate_success(api.assign_label_reviewer(
            label["id"], {"reviewer_id": users["qm"]["user"]["id"]},
            users["qm"]["headers"]))
        returned = validate_success(api.return_label_for_revision(
            label["id"], users["qm"]["headers"]))
        assert returned["status"] == "DRAFT"
        resubmitted = validate_success(api.submit_label(
            label["id"], users["ra1"]["headers"]))
        assert resubmitted["status"] == "SUBMITTED"

    def test_label_version_increments_each_transition(self, api, users):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation, including system-driven state
        transitions and cascades."

        Design: Difficulty/non_linear_state_machine/label_submission_review_revision_cycle
        """
        formula = self._approved_formula(api, users, "IF-LABEL-CYCLE-2")
        label = validate_success(api.create_label_submission(
            {"formula_id": formula["id"],
             "submission_type": "NEW_PRODUCT_REGISTRATION",
             "label_text": "Label Cycle Test - version probe"},
            users["ra1"]["headers"]), 201)
        v0 = label["version"]
        submitted = validate_success(api.submit_label(
            label["id"], users["ra1"]["headers"]))
        assert submitted["version"] == v0 + 1
        under_review = validate_success(api.assign_label_reviewer(
            label["id"], {"reviewer_id": users["qm"]["user"]["id"]},
            users["qm"]["headers"]))
        assert under_review["version"] == v0 + 2
        returned = validate_success(api.return_label_for_revision(
            label["id"], users["qm"]["headers"]))
        assert returned["version"] == v0 + 3


class TestSegregationOfDuties:
    def test_submitter_cannot_approve_own_formula(self, api, users):
        """PRD §3.3: "Approval — `IN_REVIEW → APPROVED` — is performed by a
        `QA_MANAGER` other than the user who submitted for review (violations
        yield `ERR_SEGREGATION_OF_DUTIES`)". PRD §2.1: "Segregation-of-duties
        checks compare the resource's recorded prior actor (for example, the
        user who submitted a nutrient profile or who submitted batch test
        results) against the `X-User-ID` presented on the approval or release
        call; the role name alone is not sufficient for those checks." A
        PASSED validation exists so that only the segregation rule can fail.

        Design: Corner/validations/segregation_of_duties_formula_approve
        """
        formula = _base_formula(users, "IF-SOD-1")
        submitter_id = users["ra1"]["user"]["id"]
        validate_success(api.submit_formula_for_review(
            formula["id"], users["ra1"]["headers"]))
        create_passed_validation(users, formula["id"])
        # Same acting user (identical X-User-ID), now wearing the QA_MANAGER
        # role required by the endpoint.
        res = api.approve_formula(
            formula["id"], make_qa_manager_headers(submitter_id))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
