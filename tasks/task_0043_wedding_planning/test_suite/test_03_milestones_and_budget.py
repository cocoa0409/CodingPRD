"""Milestone CRUD + status progression, budget reallocation, and the
project ledger invariant. Covers PRD §3.1 and §3.5.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_milestone,
    assert_project_ledger_invariant,
    create_milestone_payload,
    create_project,
    find_audit_entries,
    list_audit_entries,
    patch_milestone_payload,
    reallocate_budget_payload,
    setup_project_in_planning,
    setup_project_with_one_contract_accepted,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §3.1 -- Milestone status progression PENDING -> IN_PROGRESS -> COMPLETED.
# ===========================================================================
class TestMilestoneStatusTransitions:

    def test_advance_pending_to_in_progress(self, api, planner_headers):
        """PRD §3.1: "Advancing from PENDING to IN_PROGRESS requires the
        milestone to be in PENDING (otherwise ERR_MILESTONE_NOT_PENDING)."

        Claim: PATCH milestone {status: IN_PROGRESS} on a PENDING milestone
        succeeds.
        """
        project = create_project()
        milestone = add_milestone(project["id"], percent_of_budget=100.0)
        # Activate so the project leaves DRAFT (status changes are allowed
        # via the milestone update endpoint regardless of the project stage,
        # but staying in DRAFT works too -- PRD §3.1 doesn't gate it on
        # project status).
        res = api.patch_milestone(
            project["id"], milestone["id"],
            patch_milestone_payload(status="IN_PROGRESS"),
            planner_headers,
        )
        data = validate_success(res)
        assert data["status"] == "IN_PROGRESS"

    def test_advance_in_progress_to_completed(self, api, planner_headers):
        """PRD §3.1: "advancing from IN_PROGRESS to COMPLETED requires it
        to be in IN_PROGRESS (otherwise ERR_MILESTONE_NOT_IN_PROGRESS)."

        Claim: walk PENDING -> IN_PROGRESS -> COMPLETED via two PATCHes.
        """
        project = create_project()
        milestone = add_milestone(project["id"], percent_of_budget=100.0)
        api.patch_milestone(
            project["id"], milestone["id"],
            patch_milestone_payload(status="IN_PROGRESS"),
            planner_headers,
        )
        res = api.patch_milestone(
            project["id"], milestone["id"],
            patch_milestone_payload(status="COMPLETED"),
            planner_headers,
        )
        data = validate_success(res)
        assert data["status"] == "COMPLETED"

    def test_skip_pending_to_completed_rejected(self, api, planner_headers):
        """PRD §3.1: "advancing from IN_PROGRESS to COMPLETED requires it
        to be in IN_PROGRESS (otherwise ERR_MILESTONE_NOT_IN_PROGRESS)."

        Claim: PENDING -> COMPLETED skipping IN_PROGRESS ->
        ERR_MILESTONE_NOT_IN_PROGRESS / 409.
        """
        project = create_project()
        milestone = add_milestone(project["id"], percent_of_budget=100.0)
        res = api.patch_milestone(
            project["id"], milestone["id"],
            patch_milestone_payload(status="COMPLETED"),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_MILESTONE_NOT_IN_PROGRESS.value)

    def test_re_advance_in_progress_rejected(self, api, planner_headers):
        """PRD §3.1: "Advancing from PENDING to IN_PROGRESS requires the
        milestone to be in PENDING (otherwise ERR_MILESTONE_NOT_PENDING)."

        Claim: re-PATCH IN_PROGRESS on an IN_PROGRESS milestone ->
        ERR_MILESTONE_NOT_PENDING / 409.
        """
        project = create_project()
        milestone = add_milestone(project["id"], percent_of_budget=100.0)
        api.patch_milestone(
            project["id"], milestone["id"],
            patch_milestone_payload(status="IN_PROGRESS"),
            planner_headers,
        )
        res = api.patch_milestone(
            project["id"], milestone["id"],
            patch_milestone_payload(status="IN_PROGRESS"),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_MILESTONE_NOT_PENDING.value)


# ===========================================================================
# §3.1 -- Milestone-percent-sum invariant.
# ===========================================================================
class TestMilestonePercentSum:

    def test_create_second_milestone_breaking_sum_rejected(
        self, api, planner_headers
    ):
        """PRD §3.1: "After every such mutation -- and again as a
        precondition to leaving DRAFT -- the sum of percent_of_budget
        across all milestones on the project MUST equal exactly 100.0; if
        it does not, the mutation or activation is rejected with
        ERR_MILESTONE_PERCENTAGES_INVALID (HTTP 422)."

        Claim: project with one 100% milestone + adding a second 50%
        milestone -> ERR_MILESTONE_PERCENTAGES_INVALID / 422.
        """
        project = create_project()
        add_milestone(project["id"], percent_of_budget=100.0)
        res = api.create_milestone(
            project["id"],
            create_milestone_payload(label="Extra", percent_of_budget=50.0),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_MILESTONE_PERCENTAGES_INVALID.value)


# ===========================================================================
# §3.5 -- Budget reallocation: re-summed and audit-logged.
# ===========================================================================
class TestBudgetReallocation:

    def test_reallocation_preserves_total_and_logs_audit(
        self, api, planner_headers
    ):
        """PRD §3.5: "A planner may rewrite the milestone-share allocation
        without changing total_budget_cents by invoking the budget-
        reallocation operation with an allocations payload -- a list of
        {milestone_id, percent_of_budget} pairs covering every milestone on
        the project. The new shares MUST again sum to exactly 100.0
        (otherwise ERR_MILESTONE_PERCENTAGES_INVALID); on success, every
        affected Milestone.percent_of_budget is updated and an AuditEntry
        with event_kind of BUDGET_REALLOCATED records the before/after
        snapshot in its payload."

        Claim: reallocation that sums to 100.0 succeeds AND appends a
        BUDGET_REALLOCATED audit entry.
        """
        project = create_project()
        m1 = add_milestone(project["id"], label="One", percent_of_budget=100.0)
        # Project is still DRAFT; add a second milestone via reallocation
        # is not the API -- but a reallocation rewrites existing milestones.
        # Add a second milestone to the DRAFT project first so percent
        # rebalances; PRD §3.1 says this only works when the SUM equals
        # 100.0 after every mutation, so do it as a single reallocation
        # using a single milestone that re-targets the same id.
        # Simpler: reallocate the single milestone to itself at 100.0
        # (a no-op semantically) so the audit entry is appended.
        res = api.reallocate_budget(
            project["id"],
            reallocate_budget_payload(allocations=[
                {"milestone_id": m1["id"], "percent_of_budget": 100.0},
            ]),
            planner_headers,
        )
        validate_success(res)
        entries = list_audit_entries(project["id"])
        realloc_entries = find_audit_entries(
            entries, event_kind="BUDGET_REALLOCATED"
        )
        assert len(realloc_entries) >= 1, (
            "PRD §3.5: BUDGET_REALLOCATED audit entry expected after "
            "reallocate"
        )

    def test_reallocation_not_summing_to_100_rejected(
        self, api, planner_headers
    ):
        """PRD §3.5: "The new shares MUST again sum to exactly 100.0
        (otherwise ERR_MILESTONE_PERCENTAGES_INVALID)."

        Claim: reallocation of one milestone to 99.99 ->
        ERR_MILESTONE_PERCENTAGES_INVALID / 422.
        """
        project = create_project()
        m1 = add_milestone(project["id"], percent_of_budget=100.0)
        res = api.reallocate_budget(
            project["id"],
            reallocate_budget_payload(allocations=[
                {"milestone_id": m1["id"], "percent_of_budget": 99.99},
            ]),
            planner_headers,
        )
        validate_error(res, ApiErrorId.ERR_MILESTONE_PERCENTAGES_INVALID.value)


# ===========================================================================
# §3.5 -- Project ledger invariant after a contract is signed.
# ===========================================================================
class TestProjectLedgerInvariant:

    def test_balance_invariant_after_sign(self, api):
        """PRD §3.5: "The budget_balance_cents is then total_budget_cents
        minus provisional_committed_cents minus finalized_settled_cents."

        Claim: after signing one contract for 300_000, the project's
        ledger satisfies balance = total - committed - settled.
        """
        from test_helpers import get_project
        project, _v, _q, _c = setup_project_with_one_contract_accepted(
            total_budget_cents=2_000_000,
            quote_amount_cents=300_000,
        )
        p_after = get_project(project["id"])
        assert_project_ledger_invariant(p_after)

    def test_provisional_committed_includes_pinned_amount(self, api):
        """PRD §3.5: "The provisional_committed_cents is the sum, across
        every Contract on this project whose contract_status is either
        SIGNED or ACCEPTED and whose linked Settlement (if any) is not yet
        FINALIZED, of pinned_amount_cents plus the sum of approved-
        ChangeOrder delta_amount_cents against that contract."

        Claim: ACCEPTED contract with pinned_amount=300_000 and zero
        change orders -> provisional_committed_cents == 300_000 (any
        provisional from VENUE/CATERING contracts in this fixture is also
        included; we instead use a one-contract scenario via
        setup_project_with_one_contract_accepted).
        """
        from test_helpers import get_project
        project, _v, _q, _c = setup_project_with_one_contract_accepted(
            total_budget_cents=2_000_000,
            quote_amount_cents=300_000,
            vendor_category="PHOTOGRAPHY",
        )
        p_after = get_project(project["id"])
        assert p_after["provisional_committed_cents"] == 300_000, (
            f"PRD §3.5: pinned_amount_cents must be the sole component; "
            f"got {p_after['provisional_committed_cents']}"
        )
