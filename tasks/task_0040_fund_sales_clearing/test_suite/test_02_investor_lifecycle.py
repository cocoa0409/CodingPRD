"""PRD §3.1: Investor onboarding -- creation, KYC approval, cash provisioning."""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    assert_investor,
    create_investor_payload,
    create_kyc_approved_investor,
    credit_cash_payload,
    create_investor_pending_kyc,
    validate_success,
)


class TestInvestorCreation:
    def test_new_investor_starts_pending_kyc_with_zero_cash(self, api):
        """PRD §3.1: "The new investor starts with `kyc_status` set to
        `PENDING` and `cash_balance_cents` set to 0."

        Claim: server-managed fields kyc_status and cash_balance_cents
        are not user inputs and default per PRD on creation.
        """
        res = api.create_investor(
            create_investor_payload(legal_name="Pending Cash"),
            TEST_USERS["platform_admin_headers"],
        )
        investor = validate_success(res, expected_status=201)
        assert_investor(investor)
        assert investor["kyc_status"] == "PENDING"
        assert investor["cash_balance_cents"] == 0


class TestKycApproval:
    def test_kyc_approval_flips_pending_to_approved(self, api):
        """PRD §3.1: "KYC approval by a `ComplianceReviewer` flips
        `kyc_status` from `PENDING` to `APPROVED`."

        Claim: POST /investors/{id}/approve-kyc transitions kyc_status to
        APPROVED.
        """
        investor = create_investor_pending_kyc()
        assert investor["kyc_status"] == "PENDING"
        res = api.approve_kyc(
            investor["id"],
            TEST_USERS["compliance_reviewer_headers"],
        )
        approved = validate_success(res)
        assert approved["kyc_status"] == "APPROVED"


class TestCreditCash:
    def test_credit_cash_increases_balance(self, api):
        """PRD §3.1: "A test-driving capability available to `PlatformAdmin`
        lets the operator credit a positive integer `amount_cents` to an
        investor's `cash_balance_cents`, simulating an inbound bank
        deposit."

        Claim: POST /investors/{id}/credit-cash with amount_cents=N
        increases cash_balance_cents by exactly N.
        """
        investor = create_investor_pending_kyc()
        before = investor["cash_balance_cents"]
        res = api.credit_cash(
            investor["id"],
            credit_cash_payload(amount_cents=12_345_67),
            TEST_USERS["platform_admin_headers"],
        )
        after = validate_success(res)
        assert after["cash_balance_cents"] == before + 12_345_67

    def test_credit_cash_increments_version(self, api):
        """PRD §2.8: "Any operation that mutates a resource refreshes the
        resource's `updated_at` timestamp and increments its `version` by
        1."

        Claim: a cash credit (which mutates cash_balance_cents) bumps
        version by exactly 1.
        """
        investor = create_kyc_approved_investor(cash_cents=0)
        v0 = investor["version"]
        res = api.credit_cash(
            investor["id"],
            credit_cash_payload(amount_cents=100),
            TEST_USERS["platform_admin_headers"],
        )
        after = validate_success(res)
        assert after["version"] == v0 + 1
