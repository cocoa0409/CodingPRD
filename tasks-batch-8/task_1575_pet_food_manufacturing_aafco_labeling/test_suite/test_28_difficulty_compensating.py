"""Difficulty: compensating invariants — recall terminate restores the lot
population and counts; the revision loop preserves the 100.00 inclusion
invariant by rejection (PRD §3.3, §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_ingredient_line,
    create_ingredient,
    get_brand,
    get_formula,
    get_lot_by_id,
    initiate_recall,
    setup_batch_in_state,
    setup_nutrient_review_formula,
    validate_error,
    validate_success,
)


class TestRecallInitiateTerminatePreservesLotPopulation:
    def _setup_recalled_lot(self, api):
        ctx = setup_batch_in_state("COMPLETED", planned_kg=200.0, line_id="LINE-H",
                                   with_lot=True)
        recall = initiate_recall(
            ctx["formula"]["id"], [ctx["batch"]["id"]],
            recall_class="CLASS_III", reason="Test recall",
        )
        return ctx, recall

    def test_terminate_restores_brand_count_and_formula_flag(self, api, qa_approver_headers):
        """PRD §3.8: "Termination moves an `INITIATED` recall to `TERMINATED`
        with a compensating cascade: every lot this action had moved to
        `RECALLED` returns to `QUARANTINED`, and every batch it had moved to
        `RECALLED` returns to `ON_HOLD`, after which the formula's
        `open_recall_flag` and the brand's `open_recall_count` are recomputed."

        Design: Difficulty/compensating_invariant/recall_initiate_terminate_preserves_lot_population
        """
        ctx, recall = self._setup_recalled_lot(api)
        assert get_brand(ctx["brand"]["id"])["open_recall_count"] == 1

        terminated = validate_success(api.terminate_recall(recall["id"], qa_approver_headers))
        assert terminated["status"] == "TERMINATED"
        # Conserved quantity: the count returns to its pre-initiation value.
        assert get_brand(ctx["brand"]["id"])["open_recall_count"] == 0
        assert get_formula(ctx["formula"]["id"])["open_recall_flag"] is False

    def test_terminate_returns_lots_to_quarantined(self, api, qa_approver_headers):
        """PRD §3.8: "every lot this action had moved to `RECALLED` returns to
        `QUARANTINED`, and every batch it had moved to `RECALLED` returns to
        `ON_HOLD`"

        Design: Difficulty/compensating_invariant/recall_initiate_terminate_preserves_lot_population
        """
        ctx, recall = self._setup_recalled_lot(api)
        lot_after_initiate = get_lot_by_id(ctx["batch"]["id"], ctx["lot"]["id"])
        assert lot_after_initiate["status"] == "RECALLED"

        validate_success(api.terminate_recall(recall["id"], qa_approver_headers))
        lot_after_terminate = get_lot_by_id(ctx["batch"]["id"], ctx["lot"]["id"])
        assert lot_after_terminate["status"] == "QUARANTINED"


class TestRevisionCyclePreservesInclusionSum:
    def _setup_drifted_revision(self, api, qa_approver_headers):
        """Formula with one 100% line in NUTRIENT_REVIEW; revision requested; a
        second 5% line added (sum now 105)."""
        ctx = setup_nutrient_review_formula()
        validate_success(api.request_revision(ctx["formula"]["id"], qa_approver_headers))
        extra = create_ingredient()
        add_ingredient_line(ctx["formula"]["id"], extra["id"], inclusion_pct=5.0)
        return ctx

    def test_resubmit_with_drifted_sum_rejected(
        self, api, qa_approver_headers, formulation_scientist_headers
    ):
        """PRD §3.3: "The composition rule is enforced at submission time: the
        inclusion percentages across all of a formula's lines must total 100.00
        within an absolute tolerance of 0.01 — totals from 99.99 to 100.01
        inclusive pass"
        PRD §3.3: "The guards evaluate in order: first, every referenced
        ingredient must still be `ACTIVE`, else `ERR_INGREDIENT_INACTIVE`; then
        the inclusion-sum rule, else `ERR_INCLUSION_SUM_INVALID` (HTTP 422)."

        Design: Difficulty/compensating_invariant/revision_cycle_preserves_inclusion_sum
        """
        ctx = self._setup_drifted_revision(api, qa_approver_headers)
        resp = api.submit_nutrient_review(ctx["formula"]["id"], formulation_scientist_headers)
        validate_error(resp, ApiErrorId.ERR_INCLUSION_SUM_INVALID.value)

    def test_rejected_resubmit_preserves_draft_state(
        self, api, qa_approver_headers, formulation_scientist_headers
    ):
        """PRD §3.3: "The composition rule is enforced at submission time: the
        inclusion percentages across all of a formula's lines must total 100.00
        within an absolute tolerance of 0.01 — totals from 99.99 to 100.01
        inclusive pass"
        PRD §3.3: "Requesting a revision loops the formula back to `DRAFT` and
        increments its `revision_number` by one"

        Design: Difficulty/compensating_invariant/revision_cycle_preserves_inclusion_sum
        """
        ctx = self._setup_drifted_revision(api, qa_approver_headers)
        resp = api.submit_nutrient_review(ctx["formula"]["id"], formulation_scientist_headers)
        validate_error(resp, ApiErrorId.ERR_INCLUSION_SUM_INVALID.value, expected_status=422)
        # The invariant is preserved by rejection: the formula stays in DRAFT.
        assert get_formula(ctx["formula"]["id"])["status"] == "DRAFT"
