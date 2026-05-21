"""CompPlan lifecycle: DRAFT -> PROPOSED -> APPROVED / REJECTED.
Recall (APPROVED -> REJECTED) preserves compensating-action invariants.
Segregation of duties (approver != manager) and version-pinning gates.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    approve_plan,
    create_comp_plan_payload,
    propose_plan,
    setup_draft_comp_plan,
    setup_finalized_review_case,
    validate_error,
    validate_success,
)


# ===========================================================================
# Promotion-step rule (PRD §3.7)
# ===========================================================================
class TestPromotionStep:

    def test_promotion_step_must_be_exactly_plus_one(self, api):
        """PRD §3.7: "First, it must equal the subject's current
        `job_level` plus exactly 1 — strictly one rung at a time, no
        skips — otherwise `ERR_PROMO_STEP_INVALID`."

        Subject is level 4; promotion_to_level=6 must fail.
        """
        bundle = setup_finalized_review_case(
            final_rating="EXCEEDS",
            subject_job_level=4,
        )
        res = api.create_comp_plan(
            bundle.cycle["id"],
            create_comp_plan_payload(
                bundle.subject["id"], promotion_to_level=6,
            ),
            bundle.manager.headers,
        )
        validate_error(res, "ERR_PROMO_STEP_INVALID")

    def test_promotion_to_level_plus_one_accepted(self, api):
        """PRD §3.7: "...must equal the subject's current `job_level`
        plus exactly 1...".
        """
        bundle = setup_finalized_review_case(
            final_rating="EXCEEDS",
            subject_job_level=4,
        )
        plan = validate_success(api.create_comp_plan(
            bundle.cycle["id"],
            create_comp_plan_payload(
                bundle.subject["id"], promotion_to_level=5,
            ),
            bundle.manager.headers,
        ), 201)
        assert plan["promotion_to_level"] == 5


# ===========================================================================
# PIP-promotion safety gate (PRD §3.7, §2.7)
# ===========================================================================
class TestPipPromotionGate:

    def test_promotion_blocked_while_on_pip(self, api):
        """PRD §3.7: "Second, it may not be set while the subject is
        `ON_PIP`, otherwise `ERR_PROMO_BLOCKED_BY_PIP`."

        # difficulty: cross_entity_state_dependency/comp_plan_promote_requires_employee_not_pip
        """
        # Setup: subject driven to ON_PIP via NI calibration; cycle in
        # COMP_PLANNING. Now create a CompPlan with promotion_to_level
        # set.
        bundle = setup_finalized_review_case(
            final_rating="NEEDS_IMPROVEMENT",
            subject_job_level=4,
        )
        # Re-read subject to confirm ON_PIP.
        subj = validate_success(api.get_employee(
            bundle.subject["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert subj["status"] == "ON_PIP"
        res = api.create_comp_plan(
            bundle.cycle["id"],
            create_comp_plan_payload(
                bundle.subject["id"], promotion_to_level=5,
            ),
            bundle.manager.headers,
        )
        validate_error(res, "ERR_PROMO_BLOCKED_BY_PIP")


# ===========================================================================
# Validation priority — PIP-promo (priority 60) wins over budget
# (priority 90)
# ===========================================================================
class TestValidationPriorityPipVsBudget:

    def test_pip_promo_wins_over_merit_budget(self, api):
        """PRD §2.7: "Likewise, the PIP-promotion safety guard sits
        **above** the budget guard: an `ON_PIP` employee whose draft
        plan also exceeds budget produces `ERR_PROMO_BLOCKED_BY_PIP`,
        not `ERR_MERIT_BUDGET_EXCEEDED`."

        Two failures simultaneously possible: subject ON_PIP and merit
        would also exceed budget. Priority 60 wins.

        # difficulty: priority_pair_validation_conflict/pip_promo_vs_merit_budget
        """
        # Setup: tiny merit budget (1 cent) + ON_PIP subject + promotion.
        bundle = setup_finalized_review_case(
            final_rating="NEEDS_IMPROVEMENT",
            subject_job_level=4,
            merit_budget_cents=1,
        )
        # PRD §2.7 says ERR_PROMO_BLOCKED_BY_PIP fires before
        # ERR_MERIT_BUDGET_EXCEEDED. Attempt to create a plan with
        # promotion set while on PIP — the create call itself should
        # surface ERR_PROMO_BLOCKED_BY_PIP, not anything else.
        res = api.create_comp_plan(
            bundle.cycle["id"],
            create_comp_plan_payload(
                bundle.subject["id"], promotion_to_level=5,
            ),
            bundle.manager.headers,
        )
        validate_error(res, "ERR_PROMO_BLOCKED_BY_PIP")


# ===========================================================================
# Propose / Approve happy paths
# ===========================================================================
class TestComPlanLifecycle:

    def test_propose_transitions_to_proposed(self, api):
        """PRD §3.7: "A Manager or HRBP proposes the plan (`DRAFT →
        PROPOSED`)...".
        """
        bundle = setup_draft_comp_plan(final_rating="MEETS")
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        assert plan["status"] == "PROPOSED"

    def test_approve_transitions_to_approved_and_consumes_budget(self, api):
        """PRD §3.7: "On success, `merit_budget_consumed_cents` increases
        by `merit_increase_cents`, `equity_pool_consumed_units`
        increases by `equity_refresh_units`, `approved_at` is set to the
        server clock, `updated_at` is refreshed, and `version` is
        incremented."."""
        bundle = setup_draft_comp_plan(
            final_rating="EXCEEDS",
            subject_base_salary_cents=10_000_000,
            subject_job_level=4,
        )
        propose_plan(bundle)
        merit = bundle.comp_plan["merit_increase_cents"]
        equity = bundle.comp_plan["equity_refresh_units"]
        cyc_before = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        approve_plan(bundle)
        assert bundle.comp_plan["status"] == "APPROVED"
        assert bundle.comp_plan["approved_at"] is not None
        cyc_after = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert cyc_after["merit_budget_consumed_cents"] == (
            cyc_before["merit_budget_consumed_cents"] + merit
        )
        assert cyc_after["equity_pool_consumed_units"] == (
            cyc_before["equity_pool_consumed_units"] + equity
        )


# ===========================================================================
# Approver-is-manager segregation (PRD §2.11)
# ===========================================================================
class TestApproverSegregation:

    def test_approver_who_is_pinned_manager_blocked(self, api):
        """PRD §2.11: "the compensation approver: when an `Approver`
        acts on a `CompPlan` (approve, reject, or recall), the acting
        `X-User-ID` must not equal the `manager_employee_id`
        snapshotted on the plan's pinned `ReviewCase`; otherwise
        `ERR_APPROVER_IS_MANAGER` with HTTP 422."
        """
        bundle = setup_draft_comp_plan(final_rating="MEETS")
        propose_plan(bundle)
        # The bundle.manager is the case's manager_employee_id; mint
        # Approver headers using THAT id and try to approve.
        from test_helpers.test_users import make_approver_headers
        rogue_headers = make_approver_headers(bundle.manager.id)
        res = api.approve_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"], rogue_headers,
        )
        validate_error(res, "ERR_APPROVER_IS_MANAGER")


# ===========================================================================
# Version-pinning gate — PRD §2.10, §3.7
# ===========================================================================
class TestVersionPinning:

    def test_pinned_version_recorded_on_create(self, api):
        """PRD §3.7: "the server identifies the `FINALIZED`
        `ReviewCase` whose `subject_employee_id` matches, pins it via
        `pinned_review_case_id` and `pinned_review_case_version` (the
        case's current `version` at this instant)...".

        Verifies the pinning side-effect on plan creation. The
        complementary stale-pin negative test would require mutating a
        FINALIZED ReviewCase after plan creation — PRD §3.3 names
        FINALIZED as immutable, so the deterministic stale-pin path
        is not reachable via PRD-stated endpoints. See generator
        summary report bucket `difficulty-coverage-blocked-by-prd-silence`
        / `stale_pin_vs_merit_budget`.
        """
        bundle = setup_draft_comp_plan(final_rating="MEETS")
        # Same-version propose must succeed when versions agree.
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        assert plan["pinned_review_case_version"] == (
            bundle.review_case["version"]
        )
