"""PMI removal request lifecycle: filing, approval, denial; LTV math.

Coverage targets (PRD §3.5):
- File request when pmi_status != ACTIVE -> ERR_INVALID_STATE.
- File transitions Loan.pmi_status to REMOVAL_REQUESTED.
- evaluated_ltv_bps math: floor(principal_balance * 10000 / basis).
- LTV thresholds: <= 8000 for BORROWER_REQUEST; <= 7800 for AUTO_TERMINATION.
- Approve when LTV above threshold -> ERR_PMI_LTV_TOO_HIGH.
- Approve sets pmi_status=REMOVED / AUTO_TERMINATED, pmi_monthly_cents=0.
- Deny reverts pmi_status to ACTIVE.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    PMI_AUTO_TERMINATION_LTV_BPS,
    PMI_BORROWER_REQUEST_LTV_BPS,
    approve_pmi_removal,
    create_pmi_removal_request,
    deny_pmi_removal,
    get_loan,
    setup_borrower_and_current_loan,
    setup_pmi_pending_borrower_request,
    validate_error,
    validate_success,
)


class TestPmiFilePreconditions:
    def test_file_on_inactive_pmi_rejected(self, api, servicer_headers):
        """PRD §3.5: "A request to remove PMI is filed against a loan
        whose pmi_status is currently ACTIVE; an attempt against any
        other status is rejected with ERR_INVALID_STATE."

        Claim: file PMI removal against pmi_status=REMOVED (from
        pmi_monthly_cents=0 at origination) -> ERR_INVALID_STATE.
        """
        b, loan = setup_borrower_and_current_loan(pmi_monthly_cents=0)
        # Loan starts with pmi_status=REMOVED.
        assert loan["pmi_status"] == "REMOVED"
        resp = api.create_pmi_removal_request(
            loan["id"],
            {"trigger": "BORROWER_REQUEST",
             "current_appraised_value_cents": 25_000_000},
            servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_file_transitions_pmi_to_removal_requested(
        self, api, servicer_headers,
    ):
        """PRD §3.5: "Filing transitions Loan.pmi_status to
        REMOVAL_REQUESTED and the PmiRemovalRequest is created with
        decision PENDING."

        Claim: after POST /pmi-removal-requests, Loan.pmi_status ==
        REMOVAL_REQUESTED and decision == PENDING.
        """
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
        )
        assert req["decision"] == "PENDING"
        loan_after = get_loan(loan["id"])
        assert loan_after["pmi_status"] == "REMOVAL_REQUESTED"


class TestPmiLtvComputation:
    def test_evaluated_ltv_floor_division(self, api, servicer_headers):
        """PRD §3.5: "evaluated_ltv_bps is the floor of
        principal_balance_cents multiplied by 10,000, divided by that
        basis value".

        Claim: for principal_balance=20_000_000, basis=25_000_000,
        evaluated_ltv_bps = floor(20_000_000 * 10000 / 25_000_000)
        = 8000.
        """
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
            current_appraised_value_cents=25_000_000,
            original_principal_cents=20_000_000,
            original_appraised_value_cents=25_000_000,
        )
        expected = (20_000_000 * 10_000) // 25_000_000
        assert int(req["evaluated_ltv_bps"]) == expected == 8_000

    def test_borrower_request_at_8000_bps_approves(
        self, api, pmi_underwriter_headers,
    ):
        """PRD §3.5: "evaluated_ltv_bps no greater than 8000 for
        BORROWER_REQUEST".

        Claim: at evaluated_ltv_bps == 8000 (exactly inclusive
        boundary), /approve succeeds — decision=APPROVED,
        pmi_status=REMOVED, pmi_monthly_cents=0.
        """
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
            current_appraised_value_cents=25_000_000,
            original_principal_cents=20_000_000,
        )
        assert req["evaluated_ltv_bps"] == 8_000
        approved = approve_pmi_removal(loan["id"], req["id"])
        assert approved["decision"] == "APPROVED"
        loan_after = get_loan(loan["id"])
        assert loan_after["pmi_status"] == "REMOVED"
        assert loan_after["pmi_monthly_cents"] == 0


class TestPmiApprovalGuards:
    def test_approve_with_ltv_above_threshold_rejected(
        self, api, pmi_underwriter_headers,
    ):
        """PRD §3.5: "Approval is only permitted when ... the LTV
        threshold is met (evaluated_ltv_bps no greater than 8000 for
        BORROWER_REQUEST ... otherwise the request is rejected with
        ERR_PMI_LTV_TOO_HIGH)".

        Claim: principal_balance=20_002_500, basis=25_000_000 ->
        ltv = floor(8001) = 8001 -> /approve fails with
        ERR_PMI_LTV_TOO_HIGH.
        """
        # Build a loan where principal_balance is 20_002_500 cents.
        # Use original_principal=20_002_500 so balance starts there.
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
            current_appraised_value_cents=25_000_000,
            original_principal_cents=20_002_500,
            original_appraised_value_cents=25_000_000,
        )
        assert int(req["evaluated_ltv_bps"]) == 8_001
        resp = api.approve_pmi_removal_request(
            loan["id"], req["id"], pmi_underwriter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PMI_LTV_TOO_HIGH.value)


class TestPmiDeny:
    def test_deny_reverts_pmi_status_to_active(
        self, api, pmi_underwriter_headers,
    ):
        """PRD §3.5: "the request's decision becomes DENIED,
        denial_reason is recorded on the request, and Loan.pmi_status
        reverts to ACTIVE."

        Claim: /deny -> request.decision=DENIED, Loan.pmi_status=ACTIVE.
        """
        b, loan, req = setup_pmi_pending_borrower_request(
            pmi_monthly_cents=8_000,
        )
        denied = deny_pmi_removal(loan["id"], req["id"],
                                  denial_reason="LTV_TOO_HIGH")
        assert denied["decision"] == "DENIED"
        assert denied["denial_reason"] == "LTV_TOO_HIGH"
        loan_after = get_loan(loan["id"])
        assert loan_after["pmi_status"] == "ACTIVE"
