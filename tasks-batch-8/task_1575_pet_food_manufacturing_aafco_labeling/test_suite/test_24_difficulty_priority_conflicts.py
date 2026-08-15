"""Difficulty: priority-pair validation conflicts (PRD §2.10, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_ingredient,
    create_pairing,
    create_supplier,
    get_formula,
    make_qa_approver_headers,
    post_nutrient_profile,
    setup_draft_formula,
    validate_error,
    validate_success,
)


class TestStateVsBusinessSafetyPairingApproveConflict:
    def _setup_approved_pairing_then_suspend(self, api):
        supplier = create_supplier(approve=True)
        ingredient = create_ingredient()
        pairing = create_pairing(
            supplier["id"], ingredient["id"],
            requester_user_id="qa-requester-41", approve=True,
            approver_user_id="qa-approver-41",
        )
        assert pairing["approval_state"] == "APPROVED"
        validate_success(api.suspend_supplier(supplier["id"], make_qa_approver_headers("qa-approver-42")))
        return pairing

    def test_reapprove_of_approved_pairing_returns_invalid_state(self, api):
        """PRD §2.10: "Fourth, transition validity: the requested action must
        correspond to a transition that exists from the resource's current state,
        else `ERR_INVALID_STATE` (HTTP 409)"
        PRD §2.10: "Business rules then evaluate in their declared priority"
        PRD §3.2: "A `QAApprover` may revoke a pairing currently in `APPROVED`" —
        the decision transitions defined for a pairing are approve/reject from
        `PENDING_REVIEW` and revoke from `APPROVED`; approve does not exist from
        `APPROVED`, so the state check fires before the supplier-approval rule.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_pairing_approve_conflict
        """
        pairing = self._setup_approved_pairing_then_suspend(api)
        resp = api.approve_pairing(pairing["id"], make_qa_approver_headers("qa-approver-43"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_conflict_keeps_pairing_approved(self, api):
        """PRD §2.10: "Fourth, transition validity: the requested action must
        correspond to a transition that exists from the resource's current state,
        else `ERR_INVALID_STATE` (HTTP 409)"
        PRD §3.2: "Approval moves the pairing to `APPROVED`" — with the
        transition undefined from `APPROVED`, the rejected re-approval leaves the
        pairing's state untouched.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_pairing_approve_conflict
        """
        pairing = self._setup_approved_pairing_then_suspend(api)
        resp = api.approve_pairing(pairing["id"], make_qa_approver_headers("qa-approver-43"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
        current = validate_success(
            api.get_pairing(pairing["id"], make_qa_approver_headers("qa-approver-43"))
        )
        assert current["approval_state"] == "APPROVED"


class TestReferentialVsConstraintSubstantiateConflict:
    def _setup_deficient_uncovered_formula(self, api):
        """Formula in NUTRIENT_REVIEW with a DEFICIENT profile and no APPROVED
        pairing for its ingredient: both the sourcing-coverage check and the
        adequacy-basis gate would fail."""
        ctx = setup_draft_formula(with_line=True)
        post_nutrient_profile(ctx["formula"]["id"], crude_protein_min_pct=10.0)
        from test_helpers import TEST_USERS

        submitted = validate_success(
            api.submit_nutrient_review(
                ctx["formula"]["id"], TEST_USERS["formulation_scientist_headers"]
            )
        )
        assert submitted["status"] == "NUTRIENT_REVIEW"
        return ctx

    def test_substantiate_reports_sourcing_coverage_first(self, api, qa_approver_headers):
        """PRD §3.3: "Substantiation moves the formula to `SUBSTANTIATED` and is
        gated, in order, by two checks. First, sourcing coverage: for every
        ingredient line on the formula there must exist at least one
        supplier–ingredient pairing in the `APPROVED` state covering that
        ingredient, else `ERR_UNAPPROVED_INGREDIENT_SOURCE`. Second, the
        adequacy-basis gate, whose failure is `ERR_SUBSTANTIATION_UNMET`
        (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_substantiate_conflict
        """
        ctx = self._setup_deficient_uncovered_formula(api)
        resp = api.substantiate_formula(ctx["formula"]["id"], qa_approver_headers)
        validate_error(resp, ApiErrorId.ERR_UNAPPROVED_INGREDIENT_SOURCE.value)

    def test_substantiate_conflict_leaves_formula_in_review(self, api, qa_approver_headers):
        """PRD §3.3: "Substantiation moves the formula to `SUBSTANTIATED` and is
        gated, in order, by two checks. First, sourcing coverage: for every
        ingredient line on the formula there must exist at least one
        supplier–ingredient pairing in the `APPROVED` state covering that
        ingredient, else `ERR_UNAPPROVED_INGREDIENT_SOURCE`. Second, the
        adequacy-basis gate, whose failure is `ERR_SUBSTANTIATION_UNMET`
        (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_substantiate_conflict
        """
        ctx = self._setup_deficient_uncovered_formula(api)
        resp = api.substantiate_formula(ctx["formula"]["id"], qa_approver_headers)
        validate_error(
            resp, ApiErrorId.ERR_UNAPPROVED_INGREDIENT_SOURCE.value, expected_status=422
        )
        assert get_formula(ctx["formula"]["id"])["status"] == "NUTRIENT_REVIEW"
