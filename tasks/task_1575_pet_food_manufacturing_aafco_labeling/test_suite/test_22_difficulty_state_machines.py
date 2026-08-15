"""Difficulty: non-linear state machines — the formula revision cycle and the
complaint triage fork (PRD §3.3, §3.8)."""
import pytest

from test_helpers import (
    create_complaint,
    setup_draft_formula,
    setup_nutrient_review_formula,
    validate_success,
)


class TestFormulaReviewRevisionCycle:
    def test_request_revision_loops_back_and_increments_revision(
        self, api, qa_approver_headers
    ):
        """PRD §3.3: "Requesting a revision loops the formula back to `DRAFT` and
        increments its `revision_number` by one — the cyclic rework loop."
        PRD §3.3: "A formula starts in `DRAFT` with `revision_number` 1"

        Design: Difficulty/non_linear_state_machine/formula_review_revision_cycle
        """
        ctx = setup_nutrient_review_formula()
        assert ctx["formula"]["status"] == "NUTRIENT_REVIEW"
        assert ctx["formula"]["revision_number"] == 1

        back = validate_success(api.request_revision(ctx["formula"]["id"], qa_approver_headers))
        assert back["status"] == "DRAFT"
        assert back["revision_number"] == 2

    def test_cycle_resubmission_keeps_incremented_revision(
        self, api, qa_approver_headers, formulation_scientist_headers
    ):
        """PRD §3.3: "Requesting a revision loops the formula back to `DRAFT` and
        increments its `revision_number` by one — the cyclic rework loop."
        PRD §3.3: "Submission for nutrient review moves the formula from `DRAFT`
        to `NUTRIENT_REVIEW`."

        Design: Difficulty/non_linear_state_machine/formula_review_revision_cycle
        """
        ctx = setup_nutrient_review_formula()
        validate_success(api.request_revision(ctx["formula"]["id"], qa_approver_headers))
        resubmitted = validate_success(
            api.submit_nutrient_review(ctx["formula"]["id"], formulation_scientist_headers)
        )
        # The cycle is traversed; the lap counter is kept, not reset.
        assert resubmitted["status"] == "NUTRIENT_REVIEW"
        assert resubmitted["revision_number"] == 2


class TestComplaintCaseBranchingForkAutoEscalation:
    def test_triage_at_or_above_threshold_auto_escalates(self, api, quality_analyst_headers):
        """PRD §3.8: "Triage computes the final `triage_score`, recomputes the
        brand's `complaint_score`, and then branches: ordinarily the case moves
        from `INTAKE` to `TRIAGED`, but when the final score reaches 60.0 or
        higher the case auto-escalates directly to `ESCALATED_RECALL` instead —
        the escalation fork is part of the triage transition itself."
        PRD §3.8: "Severity contributes 5 points for `MINOR`, 20 for `SERIOUS`,
        45 for `LIFE_THREATENING`, and 60 for `DEATH`. Category contributes 2 for
        `PALATABILITY`, 3 for `PACKAGING`, 8 for `LABEL_DEFECT`, 12 for
        `FOREIGN_MATERIAL`, and 15 for `ILLNESS`. A confirmed adverse event adds
        a further 10 points."

        Design: Difficulty/non_linear_state_machine/complaint_case_branching_fork_auto_escalation
        """
        ctx = setup_draft_formula()
        case = create_complaint(
            ctx["brand"]["id"], ctx["formula"]["id"],
            severity="DEATH", category="ILLNESS", adverse_event_flag=True,
        )
        triaged = validate_success(
            api.triage_complaint(
                case["id"], {"confirm_adverse_event_flag": True}, quality_analyst_headers
            )
        )
        # 60 + 15 + 10 = 85.0 >= 60.0 -> fork straight to ESCALATED_RECALL.
        assert triaged["triage_score"] == pytest.approx(85.0, abs=0.005)
        assert triaged["status"] == "ESCALATED_RECALL"

    def test_triage_below_threshold_takes_triaged_branch(self, api, quality_analyst_headers):
        """PRD §3.8: "ordinarily the case moves from `INTAKE` to `TRIAGED`, but
        when the final score reaches 60.0 or higher the case auto-escalates
        directly to `ESCALATED_RECALL` instead — the escalation fork is part of
        the triage transition itself."

        Design: Difficulty/non_linear_state_machine/complaint_case_branching_fork_auto_escalation
        """
        ctx = setup_draft_formula()
        case = create_complaint(
            ctx["brand"]["id"], ctx["formula"]["id"],
            severity="SERIOUS", category="ILLNESS", adverse_event_flag=True,
        )
        triaged = validate_success(
            api.triage_complaint(
                case["id"], {"confirm_adverse_event_flag": True}, quality_analyst_headers
            )
        )
        # 20 + 15 + 10 = 45.0 < 60.0 -> the ordinary TRIAGED branch.
        assert triaged["triage_score"] == pytest.approx(45.0, abs=0.005)
        assert triaged["status"] == "TRIAGED"
