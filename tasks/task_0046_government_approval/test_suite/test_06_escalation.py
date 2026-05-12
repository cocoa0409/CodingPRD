"""Escalation flows: lead-reviewer escalates a disagreement, PlatformAdmin
resolves.

Covers PRD §3.9 (Escalation), parts of §2.5 (cascades), §3.8 (aggregation
prerequisites).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    decide,
    decide_review_task_payload,
    escalate,
    get_application,
    get_success_data,
    list_review_tasks,
    make_lead_reviewer_headers,
    resolve_escalation,
    resolve_escalation_payload,
    setup_application_under_review_parallel,
    setup_application_under_review_serial,
    setup_application_under_review_single_dept,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Escalation eligibility (PRD §3.9)
# ===========================================================================
class TestEscalationEligibility:
    def test_escalate_serial_routing_is_rejected(self, api):
        """PRD §3.9: "A LeadReviewer of the lead department of a PARALLEL
        routing whose aggregation_rule is not LEAD_DECIDES may escalate
        when at least one ReviewTask for the application has reached
        AGREED and at least one has reached DISAGREED -- that is, a real
        disagreement exists. Any escalation that does not satisfy these
        three preconditions (PARALLEL routing, aggregation rule different
        from LEAD_DECIDES, current disagreement among decided tasks) is
        rejected with ERR_ESCALATION_NOT_PERMITTED."

        Claim: escalating a SERIAL-routed application is rejected.
        """
        ctx = setup_application_under_review_serial(department_count=2)
        lead_headers = make_lead_reviewer_headers(ctx["lead_department"]["id"])
        resp = api.escalate_application(
            ctx["application"]["id"], lead_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATION_NOT_PERMITTED)

    def test_escalate_lead_decides_routing_is_rejected(self, api):
        """PRD §3.9: "Any escalation that does not satisfy these three
        preconditions (PARALLEL routing, aggregation rule different from
        LEAD_DECIDES, current disagreement among decided tasks) is
        rejected with ERR_ESCALATION_NOT_PERMITTED."

        Claim: escalating a PARALLEL/LEAD_DECIDES routing is rejected.
        """
        ctx = setup_application_under_review_parallel(
            department_count=2, aggregation_rule="LEAD_DECIDES",
        )
        resp = api.escalate_application(
            ctx["application"]["id"], ctx["lead_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATION_NOT_PERMITTED)

    def test_escalate_with_no_disagreement_is_rejected(self, api):
        """PRD §3.9: "may escalate when at least one ReviewTask for the
        application has reached AGREED and at least one has reached
        DISAGREED -- that is, a real disagreement exists."

        Claim: escalating before any DISAGREED has been filed is
        rejected with ERR_ESCALATION_NOT_PERMITTED.
        """
        ctx = setup_application_under_review_parallel(
            department_count=2, aggregation_rule="MAJORITY",
        )
        # No tasks have been decided yet -- no disagreement exists.
        resp = api.escalate_application(
            ctx["application"]["id"], ctx["lead_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_ESCALATION_NOT_PERMITTED)


# ===========================================================================
# Successful escalation (PRD §3.9)
# ===========================================================================
class TestEscalationFlow:
    def test_escalate_with_disagreement_flips_to_escalated(self, api):
        """PRD §3.9: "The escalation request flips the application from
        UNDER_REVIEW to ESCALATED, pauses every IN_PROGRESS ReviewTask
        (no further opinions are accepted while ESCALATED)."

        Claim: with one AGREED + one DISAGREED on a 3-stage
        PARALLEL/MAJORITY routing, escalate flips review_status to ESCALATED.
        """
        ctx = setup_application_under_review_parallel(
            department_count=3, aggregation_rule="MAJORITY",
        )
        first = ctx["review_tasks"][0]
        second = ctx["review_tasks"][1]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        second_headers = ctx["reviewer_headers_by_dept_id"][second["department_id"]]
        decide(first["id"], "AGREED", first_headers)
        decide(second["id"], "DISAGREED", second_headers)
        # Application still UNDER_REVIEW (third task still IN_PROGRESS,
        # MAJORITY waits for all to decide).
        mid = get_application(ctx["application"]["id"])
        assert mid["review_status"] == "UNDER_REVIEW"
        resp = api.escalate_application(
            ctx["application"]["id"], ctx["lead_reviewer_headers"],
        )
        validate_success(resp)
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "ESCALATED"


# ===========================================================================
# Escalation resolution (PRD §3.9)
# ===========================================================================
class TestEscalationResolution:
    def _build_escalated(self, parent_for_lead: bool = False):
        """Helper: walk a 3-stage PARALLEL/MAJORITY application to ESCALATED."""
        ctx = setup_application_under_review_parallel(
            department_count=3,
            aggregation_rule="MAJORITY",
            parent_for_lead=parent_for_lead,
        )
        first = ctx["review_tasks"][0]
        second = ctx["review_tasks"][1]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        second_headers = ctx["reviewer_headers_by_dept_id"][second["department_id"]]
        decide(first["id"], "AGREED", first_headers)
        decide(second["id"], "DISAGREED", second_headers)
        escalate(ctx["application"]["id"], ctx["lead_reviewer_headers"])
        return ctx

    def test_escalation_resolved_agreed_drives_to_approved(self, api):
        """PRD §3.9: "An AGREED resolution transitions the application
        from ESCALATED to APPROVED, marks every still-PENDING or
        IN_PROGRESS ReviewTask as AGREED with a system-attributed opinion."

        Claim: PlatformAdmin AGREED resolution -> Application APPROVED.
        """
        ctx = self._build_escalated()
        resolve_escalation(ctx["application"]["id"], "AGREED")
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "APPROVED"

    def test_escalation_resolved_disagreed_drives_to_rejected_and_refunds(
        self, api,
    ):
        """PRD §3.9: "A DISAGREED resolution transitions the application
        from ESCALATED to REJECTED, marks every still-PENDING or
        IN_PROGRESS ReviewTask as DISAGREED with a system-attributed
        opinion, refunds the payment by setting payment_status to
        REFUNDED when payment_status is PAID and the pinned
        fee_amount_cents is greater than 0."

        Claim: with fee>0, DISAGREED resolution -> REJECTED + REFUNDED.
        """
        ctx = setup_application_under_review_parallel(
            department_count=3,
            aggregation_rule="MAJORITY",
            fee_amount_cents=1000,
        )
        first = ctx["review_tasks"][0]
        second = ctx["review_tasks"][1]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        second_headers = ctx["reviewer_headers_by_dept_id"][second["department_id"]]
        decide(first["id"], "AGREED", first_headers)
        decide(second["id"], "DISAGREED", second_headers)
        escalate(ctx["application"]["id"], ctx["lead_reviewer_headers"])
        resolve_escalation(ctx["application"]["id"], "DISAGREED")
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"
        assert refreshed["payment_status"] == "REFUNDED"
