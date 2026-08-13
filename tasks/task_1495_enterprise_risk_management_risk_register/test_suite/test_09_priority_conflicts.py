"""Difficulty: priority_pair_validation_conflict — when two rules could
reject, the higher-priority class wins per PRD §2.8."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_assessed_risk,
    create_proposed_plan, approve_plan, create_approved_appetite,
    create_appetite,
    make_risk_owner_headers, make_risk_manager_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_RISK_MANAGER_2,
)


class TestPlanApproveStateBeatsBudget:
    """Instance: state (priority 7) beats business_fiscal (priority 12)."""

    def _build_rejected_plan_overbudget(self):
        """Risk ASSESSED with treatment_budget_cents=100_000; plan budget
        300_000 created then REJECTED by RiskManager."""
        risk = create_assessed_risk(
            likelihood=3, impact=3, treatment_budget_cents=100_000,
        )
        plan = create_proposed_plan(risk["id"], budget_cents=300_000)
        # Reject the plan (different manager than proposer: SoD passes)
        api_client.reject_treatment_plan(
            plan["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            payload={"reason": "scope"},
        )
        return risk, plan

    def test_approve_rejected_plan_returns_invalid_state_not_budget(self):
        """PRD §3.5: "Approval moves `PROPOSED` → `APPROVED` under three
        guards evaluated in precedence order: the risk-state guard first (the
        parent risk must be in `ASSESSED`, `TREATMENT`, `MONITORING`, or
        `REASSESSMENT`, else `ERR_INVALID_STATE`), then segregation of duties
        (the approver must differ from `proposer_user_id`, else
        `ERR_SOD_VIOLATION`), and finally the budget guard, always last".

        Note: the risk-state guard referenced here is the transition guard —
        REJECTED plans cannot transition to APPROVED, so the state guard
        (priority 7) fires before the budget guard (priority 12).

        Design: Difficulty/priority_pair_validation_conflict/plan_approve_state_beats_business_fiscal
        """
        _, plan = self._build_rejected_plan_overbudget()
        # Approve with a different manager (passes SoD) — but plan is REJECTED
        res = api_client.approve_treatment_plan(
            plan["id"], make_risk_manager_headers(USER_RISK_MANAGER_2),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_approve_rejected_plan_http_status_409(self):
        """PRD §3.5: "Approval moves `PROPOSED` → `APPROVED` under three
        guards evaluated in precedence order: the risk-state guard first (the
        parent risk must be in `ASSESSED`, `TREATMENT`, `MONITORING`, or
        `REASSESSMENT`, else `ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/plan_approve_state_beats_business_fiscal
        """
        _, plan = self._build_rejected_plan_overbudget()
        res = api_client.approve_treatment_plan(
            plan["id"], make_risk_manager_headers(USER_RISK_MANAGER_2),
        )
        assert res.status_code == 409


class TestAppetiteConstraintBeatsTemporal:
    """Instance: business_constraint (priority 9) beats business_temporal
    (priority 10)."""

    def _build_category_with_approved_appetite(self):
        cat = create_category(name="CP")
        create_approved_appetite(
            cat["id"], tolerance_score=10, acceptance_cap_score=20,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        return cat

    def test_tolerance_out_of_range_beats_window_overlap(self):
        """PRD §3.1: "Both scores are integers from 1 to 25 inclusive, and the
        cap must be at least the tolerance; any violation of these ranges is
        rejected with `ERR_TOLERANCE_OUT_OF_RANGE`."
        PRD §2.8: "From highest to lowest priority: ... 9. Domain ranges and
        uniqueness... 10. Temporal rules — appetite window overlap...".

        Design: Difficulty/priority_pair_validation_conflict/appetite_constraint_range_beats_temporal_overlap
        """
        cat = self._build_category_with_approved_appetite()
        # tolerance_score 30 is out of 1..25 AND window overlaps APPROVED one
        res = api_client.create_appetite_statement(
            {
                "category_id": cat["id"],
                "tolerance_score": 30, "acceptance_cap_score": 20,
                "effective_from": "2026-06-01T00:00:00Z",
                "effective_to": "2027-06-01T00:00:00Z",
            },
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_TOLERANCE_OUT_OF_RANGE.value)

    def test_tolerance_out_of_range_http_status_422(self):
        """PRD §3.1: "Both scores are integers from 1 to 25 inclusive, and the
        cap must be at least the tolerance; any violation of these ranges is
        rejected with `ERR_TOLERANCE_OUT_OF_RANGE`."

        Design: Difficulty/priority_pair_validation_conflict/appetite_constraint_range_beats_temporal_overlap
        """
        cat = self._build_category_with_approved_appetite()
        res = api_client.create_appetite_statement(
            {
                "category_id": cat["id"],
                "tolerance_score": 30, "acceptance_cap_score": 20,
                "effective_from": "2026-06-01T00:00:00Z",
                "effective_to": "2027-06-01T00:00:00Z",
            },
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        assert res.status_code == 422
