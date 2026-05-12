"""Approval workflow: serial/parallel routing, segregation of duties,
delegation, escalation, cancellation cascades (PRD §3.3, §3.4, §3.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_hours,
    advance_clock,
    approve_step_as,
    approve_step_payload,
    delegate_step_payload,
    find_step_by_stage,
    find_steps_by_stage,
    make_dept_head_headers,
    make_finance_headers,
    make_gm_headers,
    make_legal_headers,
    reject_step_as,
    setup_approved_po,
    setup_awarded_po,
    setup_tier3_po_with_two_serial_steps,
    setup_tier4_parallel_pending,
    stage_actor,
    validate_error,
    validate_success,
)


# ===========================================================================
# Final-step cascade (PRD §3.3 — last PENDING flips PO to APPROVED)
# ===========================================================================
class TestFinalStepCascade:
    def test_tier1_single_step_approval_cascades_po_and_requirement(
        self, api, buyer_headers, requester_headers
    ):
        """PRD §3.3: "if this is the final remaining PENDING step on the
        purchase order, the cascade fires: the purchase order transitions
        from PENDING_APPROVAL to APPROVED, its approved_at is set to the
        current time, and the parent requirement transitions to APPROVED."

        Claim: approving the only step on a TIER_1 PO sets PO to APPROVED
        AND Requirement to APPROVED, AND populates approved_at.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        step = setup["approval_steps"][0]
        approve_step_as(
            step["id"], role_headers=stage_actor("DEPARTMENT_HEAD", "tier1-final")
        )
        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        assert po["status"] == "APPROVED"
        assert po["approved_at"] is not None
        req = validate_success(
            api.get_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        assert req["status"] == "APPROVED"


# ===========================================================================
# Rejection cascade (PRD §3.3 — sibling SKIP, budget release)
# ===========================================================================
class TestRejectionCascade:
    def test_rejection_cascades_po_requirement_siblings_budget(
        self, api, buyer_headers, requester_headers, finance_headers
    ):
        """PRD §3.3: "On rejection, the cascade is opposite and total: the
        step writes its decided_at, an AuditLogEntry with action
        APPROVAL_STEP_REJECT is appended, the purchase order moves to
        REJECTED, the parent requirement moves to REJECTED, every other
        PENDING step on the same purchase order moves to SKIPPED, and the
        budget commitment is released — committed_amount_cents is
        decremented by the purchase order's total_amount_cents."

        Claim: rejecting any step on a TIER_3 PO triggers PO REJECTED,
        Requirement REJECTED, sibling steps SKIPPED, budget release.
        """
        # TIER_3 setup: DEPT_HEAD + parallel FIN/LEGAL + GM.
        setup = setup_awarded_po(
            quote_specs=[(100_000, 90.0), (110_000, 80.0), (120_000, 70.0)],
            quantity=100,
            budget_total_cents=200_000_000,
        )
        steps = setup["approval_steps"]
        committed_before = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["committed_amount_cents"]

        dept = find_step_by_stage(steps, "DEPARTMENT_HEAD")
        # Reject the dept-head step.
        reject_step_as(
            dept["id"],
            role_headers=stage_actor("DEPARTMENT_HEAD", "rej-cascade"),
            decision_comment="No longer needed.",
        )

        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        assert po["status"] == "REJECTED"
        req = validate_success(
            api.get_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        assert req["status"] == "REJECTED"
        # Siblings should be SKIPPED.
        listed = validate_success(
            api.list_approval_steps(setup["po"]["id"], buyer_headers), 200
        )
        listed = listed.get("approval_steps", listed) if isinstance(listed, dict) else listed
        for s in listed:
            if s["stage"] == "DEPARTMENT_HEAD":
                assert s["status"] == "REJECTED"
            else:
                assert s["status"] == "SKIPPED"
        # Budget released: committed_amount_cents decremented.
        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        assert budget["committed_amount_cents"] == committed_before - setup["po"]["total_amount_cents"]


# ===========================================================================
# Predecessor-not-decided (PRD §3.3, §2.8 priority 10)
# ===========================================================================
class TestSerialPredecessor:
    def test_serial_finance_blocked_before_dept_head_decided(
        self, api, buyer_headers
    ):
        """PRD §3.3: "A serial step approve attempted before its
        predecessor has cleared returns ERR_PREDECESSOR_NOT_DECIDED."

        Claim: on TIER_2, attempting to approve FINANCE before DEPT_HEAD
        is decided returns ERR_PREDECESSOR_NOT_DECIDED.
        """
        # TIER_2 PO: DEPT_HEAD + FINANCE serial.
        setup = setup_tier3_po_with_two_serial_steps()
        steps = setup["approval_steps"]
        finance_step = find_step_by_stage(steps, "FINANCE")
        res = api.approve_step(
            finance_step["id"],
            stage_actor("FINANCE", "predec"),
            payload=approve_step_payload(),
        )
        validate_error(res, ApiErrorId.ERR_PREDECESSOR_NOT_DECIDED.value)


# ===========================================================================
# Segregation of duties — same user on two steps (PRD §2.8 priority 7)
# ===========================================================================
class TestSegregationOfDutiesApprovals:
    def test_same_user_cannot_decide_two_steps(self, api, buyer_headers):
        """PRD §3.3: "no two steps on the same purchase order may be
        decided by the same X-User-ID — this is the segregation-of-duties
        check that precedes any other step-level rule once authorization
        has been granted; a violator receives ERR_SEGREGATION_OF_DUTIES."

        Claim: approving DEPT_HEAD as user_X then attempting to approve
        FINANCE as the same user_X yields ERR_SEGREGATION_OF_DUTIES.
        """
        setup = setup_tier3_po_with_two_serial_steps()
        steps = setup["approval_steps"]
        dept = find_step_by_stage(steps, "DEPARTMENT_HEAD")
        finance = find_step_by_stage(steps, "FINANCE")

        # The PRD §2.8 rule compares X-User-ID across steps regardless of
        # role label. Use the SAME X-User-ID for both calls — but since
        # each step has a distinct assignee_role, we need a user who can
        # authentically act as both DepartmentHead and FinanceApprover.
        # The first decision uses dept-head role; the second attempt
        # tries to approve FINANCE step using the same X-User-ID acting
        # as FinanceApprover. Since RBAC checks role+endpoint and only
        # requires the role be in the allowlist, we can submit the same
        # X-User-ID under FinanceApprover role.
        from prd_bench_local_runner.testing import build_user_headers
        shared_user_id = "soductors-x"
        dept_headers = build_user_headers(shared_user_id, "DepartmentHead")
        finance_headers = build_user_headers(shared_user_id, "FinanceApprover")
        approve_step_as(dept["id"], role_headers=dept_headers)
        res = api.approve_step(finance["id"], finance_headers)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# Delegation (PRD §3.4)
# ===========================================================================
class TestDelegation:
    def test_delegate_changes_assignee_user_id_only(self, api):
        """PRD §3.4: "The step remains in PENDING; only assignee_user_id
        is rewritten to the target, while original_assignee_user_id is
        preserved so the audit trail and any later 'delegate chain
        matches' check can still resolve back to the originator."

        Claim: after delegate, status remains PENDING; assignee_user_id
        is the target; original_assignee_user_id is the originator.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        step = setup["approval_steps"][0]
        # Assignee is some dept-head user picked by the server. Delegate
        # to a peer DepartmentHead user.
        from test_helpers import build_user_headers
        original_assignee = step["assignee_user_id"]
        # The originator is whoever the server set as assignee_user_id.
        # We delegate using their headers.
        originator_headers = build_user_headers(original_assignee, "DepartmentHead")
        target_user_id = "dept-head-delegate-target"
        res = api.delegate_step(
            step["id"],
            delegate_step_payload(target_user_id=target_user_id),
            originator_headers,
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "PENDING"
        assert updated["assignee_user_id"] == target_user_id
        assert updated["original_assignee_user_id"] == original_assignee

    # DELETED test_delegate_invalid_role_rejected: PRD §3.4 names the
    # ERR_DELEGATE_INVALID_ROLE error but does not specify how the server
    # resolves target_user_id's role (no /users endpoint, opaque user IDs
    # for non-Supplier roles per §2.1). Unique-derivability fails — a
    # PRD-faithful implementer could store role per X-User-ID across
    # requests OR require a separate registration step, producing
    # divergent test outcomes. Silence-pattern: applies_to-scope.


# ===========================================================================
# Escalation via clock advance (PRD §3.4)
# ===========================================================================
class TestEscalation:
    def test_clock_past_deadline_escalates_pending_step(
        self, api, buyer_headers, platform_admin_headers
    ):
        """PRD §3.4: "When the test clock advances past a step's
        deadline_at, the system runs an escalation sweep. Each PENDING
        step whose deadline_at is now at or before the current time
        transitions to ESCALATED: the step's assignee_user_id is
        rewritten to a GeneralManager user (the escalation target by
        stage routing), the step's deadline_at is extended to 24 hours
        after the moment of escalation, and an AuditLogEntry with action
        APPROVAL_STEP_ESCALATE is appended."

        Claim: after clock past deadline_at, the step is ESCALATED with
        deadline_at extended.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        step = setup["approval_steps"][0]
        deadline = step["deadline_at"]
        # Advance one hour past deadline.
        advance_clock(add_hours(deadline, 1))
        listed = validate_success(
            api.list_approval_steps(setup["po"]["id"], buyer_headers), 200
        )
        listed = listed.get("approval_steps", listed) if isinstance(listed, dict) else listed
        s = next(s for s in listed if s["id"] == step["id"])
        assert s["status"] == "ESCALATED"
        # Deadline extended.
        assert s["deadline_at"] != deadline


# DELETED class TestApprovalDeadlinePassed and its sole test
# test_approve_after_clock_at_deadline_rejected: PRD §3.4 says clock
# advance both escalates the step (assignee rewritten to GM, deadline
# extended +24h) and runs the deadline check, all as a single atomic
# sweep. PRD does not state whether a subsequent /approve issued at
# clock=T sees the pre-sweep deadline or the post-sweep extended
# deadline. Unique-derivability fails: the priority-9
# ERR_APPROVAL_DEADLINE_PASSED branch can be either pre-empted by
# ERR_INVALID_STATE (ESCALATED step) or pre-empted by priority-4
# ERR_FORBIDDEN (only GM may act on ESCALATED).


# ===========================================================================
# PO cancellation by buyer (PRD §3.5)
# ===========================================================================
class TestPurchaseOrderCancel:
    def test_cancel_pristine_po_releases_budget_and_skips_steps(
        self, api, buyer_headers, finance_headers
    ):
        """PRD §3.5: "The buyer may also cancel a purchase order while
        approval is still pristine: cancellation is permitted only when
        no ApprovalStep on the purchase order has its decided_at set, in
        which case the purchase order moves to CANCELLED, every
        ApprovalStep on the order moves to SKIPPED, and the budget
        commitment is released by subtracting the purchase order's
        total_amount_cents from committed_amount_cents."

        Claim: cancelling a pristine PO sets PO=CANCELLED, all steps
        SKIPPED, and committed_amount_cents drops by the PO total.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        committed_before = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )["committed_amount_cents"]
        validate_success(
            api.cancel_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        po = validate_success(
            api.get_purchase_order(setup["po"]["id"], buyer_headers), 200
        )
        assert po["status"] == "CANCELLED"
        listed = validate_success(
            api.list_approval_steps(setup["po"]["id"], buyer_headers), 200
        )
        listed = listed.get("approval_steps", listed) if isinstance(listed, dict) else listed
        for s in listed:
            assert s["status"] == "SKIPPED"
        budget = validate_success(
            api.get_budget_account(setup["budget"]["id"], finance_headers), 200
        )
        assert budget["committed_amount_cents"] == (
            committed_before - setup["po"]["total_amount_cents"]
        )


# ===========================================================================
# Rework rejected requirement (PRD §3.5)
# ===========================================================================
class TestRequirementRework:
    def test_rework_rejected_requirement_returns_to_draft(
        self, api, buyer_headers, requester_headers
    ):
        """PRD §3.5: "The originating requester may rework a REJECTED
        requirement back to DRAFT; this clears justification and leaves
        any quotes already created on the requirement in their existing
        REJECTED state — they are not resurrected."

        Claim: after rework on REJECTED requirement, status=DRAFT and
        justification is cleared.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        # Reject the only step.
        step = setup["approval_steps"][0]
        reject_step_as(
            step["id"],
            role_headers=stage_actor("DEPARTMENT_HEAD", "rework"),
            decision_comment="Rework needed.",
        )
        rew = validate_success(
            api.rework_requirement(setup["requirement"]["id"], requester_headers),
            200,
        )
        assert rew["status"] == "DRAFT"
        assert rew.get("justification") in (None, "")


# ===========================================================================
# AuditLog appends on approval actions (PRD §2.11)
# ===========================================================================
class TestAuditLogAppends:
    def test_approve_appends_audit_log_entry(self, api, gm_headers):
        """PRD §2.11: "an AuditLogEntry is appended whenever an
        ApprovalStep is approved (action = APPROVAL_STEP_APPROVE)".

        Claim: after approving any step, a queryable AuditLogEntry with
        action=APPROVAL_STEP_APPROVE exists for that step.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        step = setup["approval_steps"][0]
        approve_step_as(
            step["id"], role_headers=stage_actor("DEPARTMENT_HEAD", "audit")
        )
        # PRD §4 names GeneralManager / FinanceApprover / LegalApprover as
        # readers of /audit-log.
        listed = validate_success(
            api.list_audit_log(
                gm_headers,
                params={
                    "entity_type": "ApprovalStep",
                    "entity_id": step["id"],
                    "action": "APPROVAL_STEP_APPROVE",
                },
            ),
            200,
        )
        # Permit either a list-shaped or paginated response.
        entries = listed
        if isinstance(entries, dict):
            entries = entries.get("audit_log") or entries.get("entries") or entries.get("data") or entries
        assert isinstance(entries, list)
        assert any(
            e.get("action") == "APPROVAL_STEP_APPROVE"
            and e.get("entity_id") == step["id"]
            for e in entries
        ), "Expected APPROVAL_STEP_APPROVE entry on the step"
