"""Cycle-scoped fiscal invariants and boundary precision on the
merit-budget and equity-pool gates.

Covers:
* Exact boundary on merit_budget (<= passes, > fails).
* Exact boundary on equity_refresh_pool.
* Compensating-action invariant: approve + recall round-trip returns
  consumed counters to their pre-approve values (PRD §2.8).
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
# Merit budget — exact boundary <= vs > (PRD §2.8, §3.7)
# ===========================================================================
class TestMeritBudgetBoundary:

    def test_approve_with_zero_remaining_budget_passes(self, api):
        """PRD §3.7 / §2.8: "the cycle's `merit_budget_consumed_cents`
        plus this plan's `merit_increase_cents` is less than or equal
        to `merit_budget_cents`".

        Boundary precision: a plan that exactly fills the remaining
        budget (delta == 0) MUST pass.

        # difficulty: boundary_precision_check/merit_budget_exact_boundary
        """
        # final_rating=EXCEEDS, base=10_000_000 -> merit=600_000.
        # merit_budget_cents=600_000 lets exactly one approve succeed.
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_base_salary_cents=10_000_000,
            merit_budget_cents=600_000,
        )
        propose_plan(bundle)
        assert bundle.comp_plan["merit_increase_cents"] == 600_000
        approve_plan(bundle)
        assert bundle.comp_plan["status"] == "APPROVED"

    def test_approve_one_cent_over_budget_rejected(self, api):
        """PRD §3.7 / §5: "Approval would push
        `Cycle.merit_budget_consumed_cents` above
        `Cycle.merit_budget_cents`" -> ERR_MERIT_BUDGET_EXCEEDED.

        Boundary precision: 1 cent over MUST fail.

        # difficulty: boundary_precision_check/merit_budget_exact_boundary
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_base_salary_cents=10_000_000,
            merit_budget_cents=599_999,  # 1 cent short
        )
        propose_plan(bundle)
        assert bundle.comp_plan["merit_increase_cents"] == 600_000
        res = api.approve_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.approver.headers,
        )
        validate_error(res, "ERR_MERIT_BUDGET_EXCEEDED")


# ===========================================================================
# Equity pool — exact boundary (PRD §2.8, §3.7)
# ===========================================================================
class TestEquityPoolBoundary:

    def test_approve_at_exact_equity_pool_passes(self, api):
        """PRD §3.7: "the cycle's `equity_pool_consumed_units` plus
        this plan's `equity_refresh_units` is less than or equal to
        `equity_refresh_pool_units`"."""
        # Level 4 EXCEEDS ANNUAL = 300 units; pool exactly 300.
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_job_level=4,
            equity_refresh_pool_units=300,
        )
        propose_plan(bundle)
        assert bundle.comp_plan["equity_refresh_units"] == 300
        approve_plan(bundle)
        assert bundle.comp_plan["status"] == "APPROVED"

    def test_approve_one_unit_over_equity_pool_rejected(self, api):
        """PRD §5: ERR_EQUITY_POOL_EXHAUSTED when approval would push
        `equity_pool_consumed_units` above `equity_refresh_pool_units`."""
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_job_level=4,
            equity_refresh_pool_units=299,  # 1 unit short
        )
        propose_plan(bundle)
        assert bundle.comp_plan["equity_refresh_units"] == 300
        res = api.approve_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.approver.headers,
        )
        validate_error(res, "ERR_EQUITY_POOL_EXHAUSTED")


# ===========================================================================
# Compensating-action invariant — approve + recall round-trip
# ===========================================================================
class TestCompensatingActionInvariant:

    def test_recall_restores_merit_budget_consumed(self, api):
        """PRD §2.8: "For any approve/recall pair on the same plan,
        both totals must equal the values they held immediately before
        the approve — compensating release is exact, not lossy."

        # difficulty: compensating_invariant/merit_budget_consumed_round_trip
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_base_salary_cents=10_000_000,
        )
        propose_plan(bundle)
        cyc_baseline = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        baseline = cyc_baseline["merit_budget_consumed_cents"]
        approve_plan(bundle)
        cyc_after_approve = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert cyc_after_approve["merit_budget_consumed_cents"] == (
            baseline + bundle.comp_plan["merit_increase_cents"]
        )
        # Recall using the same Approver (PRD §3.7: "An already-approved
        # plan can be recalled (`APPROVED → REJECTED`) by an
        # `Approver`...recall is the exact compensating action").
        recalled = validate_success(api.recall_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.approver.headers,
        ), 200)
        assert recalled["status"] == "REJECTED"
        cyc_after_recall = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert cyc_after_recall["merit_budget_consumed_cents"] == baseline

    def test_recall_restores_equity_pool_consumed(self, api):
        """PRD §2.8: same compensating-action invariant on the equity
        pool counter.

        # difficulty: compensating_invariant/equity_pool_consumed_round_trip
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_job_level=4,
        )
        propose_plan(bundle)
        cyc_baseline = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        baseline = cyc_baseline["equity_pool_consumed_units"]
        approve_plan(bundle)
        cyc_after_approve = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert cyc_after_approve["equity_pool_consumed_units"] == (
            baseline + bundle.comp_plan["equity_refresh_units"]
        )
        validate_success(api.recall_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.approver.headers,
        ), 200)
        cyc_after_recall = validate_success(api.get_cycle(
            bundle.cycle["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert cyc_after_recall["equity_pool_consumed_units"] == baseline

    def test_recall_after_close_rejected(self, api):
        """PRD §3.7: "An already-approved plan can be recalled
        (`APPROVED → REJECTED`) by an `Approver` while the cycle is
        still `COMP_PLANNING` — never after closure".

        This documents the time bound on recall. The cycle has to be
        CLOSED for the verification. Closure requires all plans
        APPROVED/REJECTED and counters within budgets. We approve our
        plan, close the cycle, then attempt recall.
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="MEETS",
            subject_base_salary_cents=10_000_000,
        )
        propose_plan(bundle)
        approve_plan(bundle)
        # Close the cycle (HRBP-only per PRD §4).
        cyc = validate_success(api.close_cycle(
            bundle.cycle["id"], bundle.hrbp.headers,
        ), 200)
        assert cyc["status"] == "CLOSED"
        res = api.recall_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.approver.headers,
        )
        # PRD §3.7 names "never after closure" but does not pin a
        # specific error_id — two-reader test allows ERR_INVALID_STATE
        # (state precondition failed) or another 4xx. Accept either of
        # the deterministic state-conflict errors.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, ["ERR_INVALID_STATE",
                                       "ERR_CYCLE_NOT_OPEN"])
