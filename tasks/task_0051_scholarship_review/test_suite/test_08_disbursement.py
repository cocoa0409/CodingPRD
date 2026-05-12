"""DisbursementPlan: create / approve / SOD / revert / execute, plus
tax-withholding and payment-channel routing."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock,
    api_client,
    approve_disbursement_plan_payload,
    approve_plan_dept,
    approve_plan_finance,
    assert_disbursement_record,
    create_disbursement_plan,
    create_objection,
    create_open_scholarship,
    create_quota_allocation_payload,
    create_scholarship_with_quota,
    create_submitted_application,
    dept_officer_headers,
    DEPT_OFFICER_ID_1,
    DEPT_OFFICER_ID_2,
    execute_plan,
    finance_officer_headers,
    FINANCE_OFFICER_ID_1,
    FINANCE_OFFICER_ID_2,
    finalize_scholarship,
    get_success_data,
    list_external_sync,
    find_external_sync_events,
    revert_plan_dept,
    rule_objection,
    setup_announced_with_one_awarded,
    setup_dept_approved_plan,
    setup_executed_plan,
    setup_finalized_with_one_awarded,
    transition_scholarship,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanCreateAndApprove:

    def test_dept_approve_succeeds_and_records_dept_approver_id(self):
        """PRD §3.10: "On success the plan transitions DRAFT →
        DEPT_APPROVED, the plan's dept_approver_id is set to the
        requesting DeptOfficer's X-User-ID, and an AuditEvent with
        event_type DISBURSEMENT_APPROVED and payload.level of DEPT is
        recorded."

        Claim: dept approve -> status=DEPT_APPROVED and
        dept_approver_id == requester X-User-ID.
        """
        state = setup_finalized_with_one_awarded()
        plan = create_disbursement_plan(state["scholarship"]["id"])
        result = approve_plan_dept(
            state["scholarship"]["id"], plan["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        assert result["status"] == "DEPT_APPROVED"
        assert result["dept_approver_id"] == DEPT_OFFICER_ID_1

    def test_dept_approve_on_zero_gross_plan_returns_plan_empty(self):
        """PRD §3.10: "The plan-execute capability ... the parent
        scholarship must be in FINALIZED status (else ERR_INVALID_STATE)
        and the plan's total_gross_cents must be strictly greater than
        zero (else ERR_PLAN_EMPTY)."

        Claim: dept-approve on a plan with total_gross_cents==0 -> 409
        ERR_PLAN_EMPTY.
        """
        # Build a FINALIZED scholarship with NO AWARDED applications.
        # We can finalize a scholarship that has only WITHDRAWN
        # applications: open it, no one applies, REVIEWING (cascade
        # withdraws none — there's nothing to cascade), then ANNOUNCED
        # (no candidates to award), then FINALIZED.
        sch, _ = create_scholarship_with_quota(
            total_quota=1,
            application_window_start="2026-06-01T00:00:00Z",
            application_window_end="2026-06-30T00:00:00Z",
            announcement_window_end="2026-07-15T00:00:00Z",
        )
        from test_helpers import open_scholarship, close_and_review
        open_scholarship(sch)
        close_and_review(sch)
        validate_success(
            api_client.transition_scholarship(
                sch["id"], {"to_status": "ANNOUNCED"}, ADMIN,
            ),
        )
        advance_clock(sch["announcement_window_end"])
        validate_success(
            api_client.transition_scholarship(
                sch["id"], {"to_status": "FINALIZED"}, ADMIN,
            ),
        )
        plan = create_disbursement_plan(sch["id"])
        # total_gross_cents must be 0 since no AWARDED apps.
        assert plan["total_gross_cents"] == 0
        resp = api_client.approve_disbursement_plan(
            sch["id"], plan["id"],
            approve_disbursement_plan_payload(level="DEPT"),
            dept_officer_headers(DEPT_OFFICER_ID_1),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_EMPTY.value)


class TestSODOnFinanceApproval:

    def test_finance_approver_equals_dept_approver_rejected(self):
        """PRD §3.10: "A FinanceOfficer then requests finance-level
        approval with level of FINANCE; the requester's X-User-ID must
        differ from the plan's dept_approver_id (else
        ERR_SOD_VIOLATION)."

        Claim: same X-User-ID approves at both levels -> ERR_SOD_VIOLATION.
        """
        state = setup_finalized_with_one_awarded()
        plan = create_disbursement_plan(
            state["scholarship"]["id"],
            officer_id=FINANCE_OFFICER_ID_1,
        )
        # Dept approve with id U1 (use the SAME id for finance)
        approve_plan_dept(
            state["scholarship"]["id"], plan["id"],
            officer_id="user-conflict-1",
        )
        # Now attempt finance approve with the SAME user id.
        resp = api_client.approve_disbursement_plan(
            state["scholarship"]["id"], plan["id"],
            approve_disbursement_plan_payload(level="FINANCE"),
            finance_officer_headers("user-conflict-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_finance_approver_differs_from_dept_approver_succeeds(self):
        """PRD §3.10: "On success the plan transitions DEPT_APPROVED →
        FINANCE_APPROVED, the finance_approver_id is set to the
        requester's X-User-ID".

        Claim: distinct U1 (dept) and U2 (finance) -> FINANCE_APPROVED.
        """
        state = setup_finalized_with_one_awarded()
        plan = create_disbursement_plan(state["scholarship"]["id"])
        approve_plan_dept(
            state["scholarship"]["id"], plan["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        result = approve_plan_finance(
            state["scholarship"]["id"], plan["id"],
            officer_id=FINANCE_OFFICER_ID_1,
        )
        assert result["status"] == "FINANCE_APPROVED"
        assert result["finance_approver_id"] == FINANCE_OFFICER_ID_1


class TestRevertCycle:

    def test_dept_revert_clears_dept_approver_id(self):
        """PRD §3.10: "On a successful revert the plan transitions
        DEPT_APPROVED → DRAFT, the dept_approver_id is cleared back to
        null".

        Claim: dept-officer who approved reverts -> status=DRAFT and
        dept_approver_id is null.
        # difficulty: non_linear_state_machine/disbursement_plan_revert_cycle
        """
        state = setup_dept_approved_plan(
            dept_officer_id=DEPT_OFFICER_ID_1,
        )
        result = revert_plan_dept(
            state["scholarship"]["id"], state["plan"]["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        assert result["status"] == "DRAFT"
        assert result["dept_approver_id"] is None

    def test_revert_preserves_total_gross_cents(self):
        """PRD §3.10: "the snapshotted total_gross_cents and total_tax_cents
        remain unchanged — the system never recomputes them after
        creation, even across revert cycles."

        Claim: total_gross_cents and total_tax_cents unchanged after
        revert.
        # difficulty: compensating_invariant/disbursement_gross_invariant_under_approve_and_revert
        """
        state = setup_dept_approved_plan(
            dept_officer_id=DEPT_OFFICER_ID_1,
        )
        before_gross = state["plan"]["total_gross_cents"]
        before_tax = state["plan"]["total_tax_cents"]
        result = revert_plan_dept(
            state["scholarship"]["id"], state["plan"]["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        assert result["total_gross_cents"] == before_gross
        assert result["total_tax_cents"] == before_tax

    def test_revert_by_different_dept_officer_rejected(self):
        """PRD §3.10: "the same DeptOfficer who approved it (and only
        that officer) may revert it back to DRAFT — a different
        DeptOfficer who attempts to revert is rejected with
        ERR_FORBIDDEN".

        Claim: revert by a different DeptOfficer -> ERR_FORBIDDEN.
        """
        state = setup_dept_approved_plan(
            dept_officer_id=DEPT_OFFICER_ID_1,
        )
        resp = api_client.revert_disbursement_plan(
            state["scholarship"]["id"], state["plan"]["id"],
            dept_officer_headers(DEPT_OFFICER_ID_2),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestExecutorMismatch:

    def test_executor_must_equal_finance_approver(self):
        """PRD §3.10: "The plan-execute capability is permitted only to
        the same FinanceOfficer whose X-User-ID equals the plan's
        finance_approver_id (else ERR_EXECUTOR_MISMATCH)."

        Claim: a FinanceOfficer X-User-ID != finance_approver_id -> 403
        ERR_EXECUTOR_MISMATCH.
        """
        state = setup_finalized_with_one_awarded()
        plan = create_disbursement_plan(state["scholarship"]["id"])
        approve_plan_dept(
            state["scholarship"]["id"], plan["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        approve_plan_finance(
            state["scholarship"]["id"], plan["id"],
            officer_id=FINANCE_OFFICER_ID_1,
        )
        resp = api_client.execute_disbursement_plan(
            state["scholarship"]["id"], plan["id"],
            finance_officer_headers(FINANCE_OFFICER_ID_2),
        )
        validate_error(resp, ApiErrorId.ERR_EXECUTOR_MISMATCH.value)


class TestExecutionCreatesRecords:

    def test_execute_creates_disbursement_record_per_awarded_application(self):
        """PRD §3.10: "For each application currently in AWARDED, a
        single DisbursementRecord is created, carrying its parent plan_id,
        the originating application_id and the recipient student_id, the
        executed-time fields gross_cents ..., tax_withheld_cents ...,
        net_cents (equal to gross_cents minus tax_withheld_cents),
        payment_channel ..., and executed_at".

        Claim: execute -> one DisbursementRecord per AWARDED app, with
        gross_cents == scholarship.per_award_amount_cents.
        """
        state = setup_executed_plan(
            per_award_amount_cents=1_500_000,
        )
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        assert len(records) == 1, (
            "PRD §3.10: one DisbursementRecord per AWARDED application"
        )
        rec = records[0]
        assert_disbursement_record(rec)
        assert rec["gross_cents"] == 1_500_000


class TestTaxWithholding:
    """PRD §3.10 tax tiers + surcharge with the pinned 'round each
    component then sum' order."""

    def test_tax_at_500250_pinned_rounding_yields_1509(self):
        """PRD §3.10: "the alternative of computing the unrounded sum and
        rounding once at the end is explicitly forbidden because at
        fractional-edge gross values the two procedures can differ by
        one cent."

        Claim: gross=500250 -> tax_withheld_cents == 1509 (the pinned
        order; the forbidden order would yield 1508).
        # difficulty: dual_variant_calc/tax_withholding_per_component_vs_sum_then_round
        # difficulty: combinatorial_formula/rounding_order_pinned_in_tax_withholding_mode_b
        """
        # gross=500250 cents lies in tier [500000, 2000000) at 3%.
        # tier 0 [0, 500000)*0% -> 0
        # tier 1 [500000, 500250)*3% -> 250 cents * 0.03 = 7.5
        #   round_half_up(7.5) = 8 cents
        # surcharge: 500250 * 3/1000 = 1500.75 -> round_half_up = 1501
        # Pinned: 8 + 1501 = 1509
        # Forbidden (sum then round): 7.5 + 1500.75 = 1508.25 -> 1508
        state = setup_executed_plan(per_award_amount_cents=500_250)
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        assert rec["tax_withheld_cents"] == 1509, (
            f"PRD §3.10 pinned round-per-component-then-sum yields 1509; "
            f"forbidden sum-then-round yields 1508. Got "
            f"{rec['tax_withheld_cents']}."
        )
        assert rec["net_cents"] == 500_250 - 1509

    def test_tax_at_5000000_uses_top_tier(self):
        """PRD §3.10: "from 5,000,000 cents up to 1,000,000,000 cents
        excluded at 20 percent". And "the slice amount is multiplied by
        the tier's rate-percent and divided by 100, then rounded half-up
        to integer cents, and this per-tier rounded amount is accumulated
        into the base tax." Plus the flat 0.3% surcharge.

        Claim: gross=5_000_000 -> tax_withheld_cents = 360_000:
          tier1 (500k..2m): 1_500_000 * 3% = 45_000
          tier2 (2m..5m):   3_000_000 * 10% = 300_000
          tier3 (5m..1b):  slice = 5_000_000 - 5_000_000 = 0 -> 0
          surcharge: 5_000_000 * 3/1000 = 15_000
          total = 45_000 + 300_000 + 0 + 15_000 = 360_000
        # difficulty: combinatorial_formula/tiered_tax_with_three_inputs_mode_a
        """
        state = setup_executed_plan(per_award_amount_cents=5_000_000)
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        assert rec["tax_withheld_cents"] == 360_000, (
            f"Expected 360_000 (tier rates 3%+10% within top tier "
            f"slices plus 0.3% surcharge); got "
            f"{rec['tax_withheld_cents']}"
        )
        assert rec["net_cents"] == 5_000_000 - 360_000


class TestPaymentChannelRouting:

    def test_net_at_routing_threshold_routes_to_bank(self):
        """PRD §3.10: "when the record's net_cents is at least 1,000,000
        cents (in other words, when the net payout is at least 10,000.00
        yuan in the customary local-currency reading of cents), the
        record's payment_channel is overridden to BANK".
        PRD §3.10: "The boundary is inclusive on the BANK side: a record
        whose net_cents is exactly 1,000,000 cents routes to BANK."

        Claim: with plan.payment_channel=CAMPUS_CARD but a high gross,
        execution overrides per-record payment_channel to BANK.
        """
        # gross=5_000_000 -> tax=360_000 -> net=4_640_000 (>= 1_000_000)
        state = setup_executed_plan(
            per_award_amount_cents=5_000_000,
            payment_channel="CAMPUS_CARD",
        )
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        assert rec["net_cents"] >= 1_000_000
        assert rec["payment_channel"] == "BANK", (
            "PRD §3.10: net >= 1_000_000 forces BANK override"
        )

    def test_low_net_keeps_plan_channel(self):
        """PRD §3.10: "otherwise the record's payment_channel equals the
        plan's payment_channel."

        Claim: with low gross/low net (< 1_000_000), record retains the
        plan's payment_channel.
        """
        # gross=500_250 -> tax=1509 -> net=498_741 (< 1_000_000)
        state = setup_executed_plan(
            per_award_amount_cents=500_250,
            payment_channel="CAMPUS_CARD",
        )
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        assert rec["net_cents"] < 1_000_000
        assert rec["payment_channel"] == "CAMPUS_CARD"


class TestScholarshipDisburse:

    def test_disburse_requires_executed_plan(self):
        """PRD §3.11: "The transition requires that a DisbursementPlan
        for this scholarship has reached EXECUTED (else
        ERR_DISBURSEMENT_NOT_EXECUTED)."

        Claim: FINALIZED -> DISBURSED while plan is only DEPT_APPROVED
        -> ERR_DISBURSEMENT_NOT_EXECUTED.
        # difficulty: cross_entity_state_dependency/application_disbursed_requires_disbursement_plan_executed
        """
        state = setup_dept_approved_plan()
        resp = api_client.transition_scholarship(
            state["scholarship"]["id"],
            {"to_status": "DISBURSED"},
            finance_officer_headers(FINANCE_OFFICER_ID_1),
        )
        validate_error(
            resp, ApiErrorId.ERR_DISBURSEMENT_NOT_EXECUTED.value,
        )

    def test_disburse_cascades_application_to_disbursed_and_plan_to_archived(
        self,
    ):
        """PRD §3.11: "every application currently in AWARDED for this
        scholarship transitions AWARDED → DISBURSED by cascade, and each
        cascaded application records its own AuditEvent and emits one
        ExternalSyncEvent with kind FINANCE_DISBURSED. Simultaneously,
        the DisbursementPlan transitions EXECUTED → ARCHIVED automatically".

        Claim: FINALIZED→DISBURSED -> Application.status=DISBURSED,
        Plan.status=ARCHIVED, FINANCE_DISBURSED event emitted.
        # difficulty: transitive_cascade/scholarship_disbursed_cascade_chain
        """
        state = setup_executed_plan()
        validate_success(
            api_client.transition_scholarship(
                state["scholarship"]["id"],
                {"to_status": "DISBURSED"},
                finance_officer_headers(FINANCE_OFFICER_ID_1),
            ),
        )
        app = validate_success(
            api_client.get_application(
                state["scholarship"]["id"],
                state["application"]["id"], ADMIN,
            ),
        )
        plan = validate_success(
            api_client.get_disbursement_plan(
                state["scholarship"]["id"],
                state["plan"]["id"], ADMIN,
            ),
        )
        assert app["status"] == "DISBURSED"
        assert plan["status"] == "ARCHIVED"
        events = list_external_sync()
        fin = find_external_sync_events(
            events, kind="FINANCE_DISBURSED",
            application_id=state["application"]["id"],
        )
        assert fin, "PRD §3.11: FINANCE_DISBURSED event expected"
