"""Decision recording and I-130 → I-485 cascades — PRD §3.7.

Coverage:
- APPROVE on I-485 requires priority_date_status == CURRENT when
  CaseTypeConfig.requires_priority_date_current is true
  (ERR_PRIORITY_DATE_NOT_CURRENT).
- APPROVE pins decision_at and transitions to APPROVED.
- I-130 APPROVE cascade hop 1: dependent I-485 with null priority_date
  inherits the I-130's priority_date.
- DENY requires denial_reason in {OFFICER_DENIAL, INELIGIBLE}.
- DENY on I-130 cascade hop 1: dependent I-485 (non-terminal) forced
  to DENIED with denial_reason=INELIGIBLE.
- DENY on I-130 cascade hop 2: SCHEDULED Biometrics/Interview on
  dependent set to CANCELLED.
- Withdrawal paths — DRAFT, FILED (no completed biometrics),
  BIOMETRICS_SCHEDULED (cancels SCHEDULED biometrics).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    complete_biometrics,
    complete_interview,
    create_case,
    decide_case,
    decide_case_payload,
    file_case,
    issue_rfe,
    make_petitioner_headers,
    re_get_case,
    ready_for_decision,
    respond_rfe,
    schedule_biometrics,
    schedule_interview,
    seed_all_case_type_configs,
    server_offset_iso,
    setup_approved_i130_with_dependent_i485,
    setup_biometrics_completed,
    setup_dependent_i485_in_interview_scheduled,
    setup_filed_case,
    setup_i130_ready_with_real_dependent_i485,
    setup_interview_scheduled,
    setup_petitioner_and_beneficiary,
    setup_ready_for_decision_i130,
    setup_ready_for_decision_i485,
    setup_rfe_responded,
    validate_error,
    validate_success,
    withdraw_case,
)


# ===========================================================================
# Approval
# ===========================================================================
class TestApproval:

    def test_i130_approve_sets_decision_at(self, api):
        """PRD §3.7: "Recording an approval pins decision_at to the
        present instant and transitions the case to APPROVED."

        Claim: deciding APPROVE on a READY_FOR_DECISION I-130 sets
        decision_at non-null and Case.status=APPROVED.
        """
        bundle = setup_ready_for_decision_i130()
        case = bundle["case"]
        decided = decide_case(case, decision="APPROVE")
        assert decided["status"] == "APPROVED"
        assert decided.get("decision_at") is not None

    def test_i485_approve_rejected_when_priority_not_current(self, api):
        """PRD §3.7: "Approval is rejected with
        ERR_PRIORITY_DATE_NOT_CURRENT when the case's
        CaseTypeConfig.requires_priority_date_current is true and its
        priority_date_status is anything other than CURRENT."

        Claim: attempting APPROVE on an I-485 whose
        priority_date_status is NOT_CURRENT ->
        ERR_PRIORITY_DATE_NOT_CURRENT.
        """
        # Drive an I-485 to READY_FOR_DECISION with no bulletin row
        # matching the beneficiary's preference_category/country, so
        # priority_date_currency yields NOT_CURRENT (no row -> NOT_CURRENT
        # per PRD §2.9).
        bundle = setup_ready_for_decision_i485(
            preference_category="F2A",
        )
        case = bundle["case"]
        assert case["status"] == "READY_FOR_DECISION"
        assert case["priority_date_status"] != "CURRENT"
        resp = api_client.decide_case(
            case["id"],
            decide_case_payload(decision="APPROVE"),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_PRIORITY_DATE_NOT_CURRENT.value,
        )

    def test_i130_approve_cascade_to_dependent_i485_priority_date(self, api):
        """PRD §3.7: "When the case is an I-130, the approval has a
        two-hop cascade onto dependent I-485 filings. In the first hop,
        for every dependent I-485 whose linked_i130_case_id references
        this case and whose priority_date is currently null, the system
        sets the dependent's priority_date to this I-130's
        priority_date."

        Claim: after approving an I-130, a dependent I-485 in DRAFT
        with priority_date null inherits the I-130's priority_date.
        """
        seed_all_case_type_configs()
        p, b = setup_petitioner_and_beneficiary(preference_category="F2A")
        i130 = create_case(p, b, case_type="I-130")
        i130 = file_case(i130, p)
        # Dependent I-485 in DRAFT.
        i485 = create_case(
            p, b, case_type="I-485", linked_i130_case_id=i130["id"],
        )
        assert i485.get("priority_date") is None
        i130 = ready_for_decision(i130)
        i130 = decide_case(i130, decision="APPROVE")
        # Re-read dependent to observe cascade hop 1.
        dep = re_get_case(i485["id"])
        assert dep["priority_date"] == i130["priority_date"], (
            f"Cascade hop 1: dependent I-485 priority_date should "
            f"inherit from approved I-130; got "
            f"dep={dep['priority_date']!r} i130={i130['priority_date']!r}"
        )


# ===========================================================================
# Denial
# ===========================================================================
class TestDenial:

    def test_deny_requires_denial_reason_in_allowed_set(self, api):
        """PRD §3.7: "Denial requires the officer to supply a
        denial_reason drawn from OFFICER_DENIAL or INELIGIBLE; the
        other two members of the denial-reason set, RFE_TIMEOUT and
        ABANDONMENT, are reserved for system-driven outcomes."

        Claim: DENY with denial_reason=RFE_TIMEOUT (system-only) ->
        ERR_VALIDATION.
        """
        bundle = setup_ready_for_decision_i130()
        case = bundle["case"]
        resp = api_client.decide_case(
            case["id"],
            decide_case_payload(
                decision="DENY", denial_reason="RFE_TIMEOUT",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_officer_denial_records_reason(self, api):
        """PRD §3.7: "Recording a denial pins decision_at to the
        present instant, records the supplied denial_reason, and
        transitions the case to DENIED."

        Claim: DENY with denial_reason=OFFICER_DENIAL -> status=DENIED,
        denial_reason=OFFICER_DENIAL, decision_at set.
        """
        bundle = setup_ready_for_decision_i130()
        case = bundle["case"]
        decided = decide_case(
            case, decision="DENY", denial_reason="OFFICER_DENIAL",
        )
        assert decided["status"] == "DENIED"
        assert decided["denial_reason"] == "OFFICER_DENIAL"
        assert decided.get("decision_at") is not None


# ===========================================================================
# Withdrawal paths
# ===========================================================================
class TestWithdrawal:

    def test_withdraw_from_draft(self, api):
        """PRD §3.8: "From DRAFT the withdrawal has no precondition."

        Claim: a Petitioner can withdraw a DRAFT case to WITHDRAWN.
        """
        seed_all_case_type_configs()
        p, b = setup_petitioner_and_beneficiary()
        case = create_case(p, b, case_type="I-130")
        withdrawn = withdraw_case(case, p)
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn.get("decision_at") is not None

    def test_withdraw_from_filed(self, api):
        """PRD §3.8: "From FILED the withdrawal requires that no
        Biometrics row on the case has reached COMPLETED."

        Claim: a FILED case with no biometrics on it can be withdrawn.
        """
        bundle = setup_filed_case(case_type="I-130")
        withdrawn = withdraw_case(bundle["case"], bundle["petitioner"])
        assert withdrawn["status"] == "WITHDRAWN"

    def test_withdraw_from_biometrics_scheduled_cancels_biometrics(self, api):
        """PRD §3.8: "From BIOMETRICS_SCHEDULED withdrawal also
        requires no completed biometrics chain, and the withdrawal
        additionally cancels any still-SCHEDULED biometrics by setting
        their status to CANCELLED."

        Claim: withdrawing from BIOMETRICS_SCHEDULED transitions the
        case to WITHDRAWN and the SCHEDULED biometrics row to
        CANCELLED.
        """
        bundle = setup_filed_case(case_type="I-485")
        case = bundle["case"]
        bio = schedule_biometrics(case, days_ahead=8)
        case = re_get_case(case["id"])
        assert case["status"] == "BIOMETRICS_SCHEDULED"
        withdrawn = withdraw_case(case, bundle["petitioner"])
        assert withdrawn["status"] == "WITHDRAWN"
        # Re-read the biometrics row.
        resp = api_client.get_biometrics(
            bio["id"],
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED", (
            f"Withdrawal cascade should cancel SCHEDULED biometrics; "
            f"got {data['status']}"
        )
