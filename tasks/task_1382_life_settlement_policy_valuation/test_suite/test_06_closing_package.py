"""Closing package workflow: signature loop, deficiency revert, approval gates
(PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_broker_headers, make_compliance_headers,
    setup_case_in_closing, setup_package_compliance_review, setup_package_approved,
    set_clock, sign_documents,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
CO_1 = make_compliance_headers("co_1")


class TestDeficiencyRevert:
    def test_closing_package_deficiency_revert_branch(self, api):
        """PRD §3.4: "A deficiency return names `deficient_doc_types` and optional
        `deficiency_notes`; every named type must correspond to a checklist row
        (otherwise `ERR_INVALID_REQUEST`); the named rows are reset to unsigned
        with `signed_at` cleared, the notes are stored, and the package returns
        from `COMPLIANCE_REVIEW` to `OUT_FOR_SIGNATURE`."
        PRD §3.4: "Approval stamps the package's `approved_by_user_id` with the
        caller's `X-User-ID` — the segregation-of-duties anchor referenced again at
        escrow release."
        PRD §2.7: "7. From-state validity for the attempted trigger
        (`ERR_INVALID_STATE_TRANSITION`, HTTP 409, and its domain variants
        `ERR_CASE_NOT_MARKETED`, `ERR_CASE_HAS_ACTIVE_CLOSING`,
        `ERR_ESCROW_NOT_FUNDED`, `ERR_POLICY_NOT_ACQUIRED`)."

        Design: Difficulty/non_linear_state_machine/closing_package_deficiency_revert_branch
        """
        ctx = setup_package_compliance_review()
        pkg = ctx["package"]
        assert pkg["status"] == "COMPLIANCE_REVIEW"

        back = validate_success(api.return_deficiency(
            pkg["id"],
            {"deficient_doc_types": ["CHANGE_OF_OWNERSHIP", "TAX_DISCLOSURE"],
             "deficiency_notes": "notary seal illegible"},
            CO_1,
        ))
        assert back["status"] == "OUT_FOR_SIGNATURE"
        docs = {row["doc_type"]: row for row in back["documents"]}
        assert docs["CHANGE_OF_OWNERSHIP"]["signed"] is False
        assert docs["CHANGE_OF_OWNERSHIP"]["signed_at"] is None
        assert docs["TAX_DISCLOSURE"]["signed"] is False
        assert docs["TAX_DISCLOSURE"]["signed_at"] is None
        for other in ("CHANGE_OF_BENEFICIARY", "COMPENSATION_DISCLOSURE",
                      "ALTERNATIVES_DISCLOSURE", "PRIVACY_NOTICE", "RESCISSION_NOTICE"):
            assert docs[other]["signed"] is True, f"{other} must remain signed"
        assert back["deficiency_notes"] == "notary seal illegible"

        # Approve is not valid from OUT_FOR_SIGNATURE.
        resp = api.approve_package(pkg["id"], CO_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        validate_success(api.record_signature(pkg["id"], {"doc_type": "CHANGE_OF_OWNERSHIP"}, CM))
        validate_success(api.record_signature(pkg["id"], {"doc_type": "TAX_DISCLOSURE"}, CM))
        review2 = validate_success(api.submit_review(pkg["id"], CM))
        assert review2["status"] == "COMPLIANCE_REVIEW"
        approved = validate_success(api.approve_package(pkg["id"], CO_1))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "co_1"

    def test_closing_package_approve_path_stamps_approver(self, api):
        """PRD §3.4: "Approval, by contrast, runs three checks in order. First,
        business safety: the case's `hold_status` must be `CLEAR`
        (`ERR_CASE_ON_COMPLIANCE_HOLD`). Second, license posture: a governing
        `StateLicense` for the insured's `state_code` must exist, be `ACTIVE`, and
        reach at least thirty days beyond the current clock date — a missing or
        suspended license is rejected with `ERR_STATE_LICENSE_NOT_ACTIVE`
        (HTTP 409), and one whose `expiry_date` falls within the thirty-day horizon
        is rejected with `ERR_LICENSE_EXPIRING_SOON` (HTTP 409). Third,
        completeness: every required document must be signed
        (`ERR_CLOSING_DOCS_INCOMPLETE`, HTTP 422). Approval stamps the package's
        `approved_by_user_id` with the caller's `X-User-ID` — the
        segregation-of-duties anchor referenced again at escrow release."

        Design: Difficulty/non_linear_state_machine/closing_package_deficiency_revert_branch
        """
        ctx = setup_package_compliance_review()
        approved = validate_success(api.approve_package(ctx["package"]["id"], CO_1))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "co_1"
        assert all(row["signed"] is True for row in approved["documents"])
        assert all(row["signed_at"] is not None for row in approved["documents"])


class TestApprovalGates:
    def test_docs_incomplete_at_approve(self, api):
        """PRD §3.4: "Submission for compliance review moves the package from
        `OUT_FOR_SIGNATURE` to `COMPLIANCE_REVIEW` and requires at least one
        document signed — completeness is deliberately not required at this gate,
        because completeness is enforced at approval instead"
        PRD §3.4: "Third, completeness: every required document must be signed
        (`ERR_CLOSING_DOCS_INCOMPLETE`, HTTP 422)."

        Design: Corner/validations/docs_incomplete_at_approve
        """
        ctx = setup_package_compliance_review(exclude_docs=["RESCISSION_NOTICE"])
        pkg = ctx["package"]
        resp = api.approve_package(pkg["id"], CO_1)
        validate_error(resp, ApiErrorId.ERR_CLOSING_DOCS_INCOMPLETE)

        validate_success(api.return_deficiency(pkg["id"], {"deficient_doc_types": ["RESCISSION_NOTICE"]}, CO_1))
        validate_success(api.record_signature(pkg["id"], {"doc_type": "RESCISSION_NOTICE"}, CM))
        validate_success(api.submit_review(pkg["id"], CM))
        approved = validate_success(api.approve_package(pkg["id"], CO_1))
        assert approved["status"] == "APPROVED"

    def test_approve_rejected_when_license_expired(self, api):
        """PRD §3.4: "Second, license posture: a governing `StateLicense` for the
        insured's `state_code` must exist, be `ACTIVE`, and reach at least thirty
        days beyond the current clock date — a missing or suspended license is
        rejected with `ERR_STATE_LICENSE_NOT_ACTIVE` (HTTP 409)"
        PRD §2.8: "expiry is automatic when the clock date passes `expiry_date`,
        from either `ACTIVE` or `SUSPENDED`."
        PRD §2.8: "When that governing license transitions `ACTIVE` to `SUSPENDED`
        while the case is `MARKETED` or `IN_CLOSING`, the case's `hold_status`
        moves from `CLEAR` to `COMPLIANCE_HOLD` as a direct cascade of the
        suspension."

        Design: Corner/validations/approve_rejected_when_license_expired
        """
        ctx = setup_package_compliance_review(
            license_overrides={"expiry_date": "2026-12-31"},
            offer_extra={"expires_in_days": 30},
        )
        pkg, lic, case = ctx["package"], ctx["license"], ctx["case"]
        set_clock("2027-01-01T00:00:00Z")
        lic_after = validate_success(api.get_license(lic["id"], CM))
        assert lic_after["status"] == "EXPIRED"
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["hold_status"] == "CLEAR", "expiry does not cascade a hold"
        resp = api.approve_package(pkg["id"], CO_1)
        validate_error(resp, ApiErrorId.ERR_STATE_LICENSE_NOT_ACTIVE)

    def test_license_expiring_soon_boundary(self, api):
        """PRD §3.4: "a governing `StateLicense` for the insured's `state_code` must
        exist, be `ACTIVE`, and reach at least thirty days beyond the current clock
        date — a missing or suspended license is rejected with
        `ERR_STATE_LICENSE_NOT_ACTIVE` (HTTP 409), and one whose `expiry_date`
        falls within the thirty-day horizon is rejected with
        `ERR_LICENSE_EXPIRING_SOON` (HTTP 409)."
        PRD §3.4: "One row is state-dependent: STATE_SUPPLEMENT is required exactly
        when the insured's `state_code` is CA or NY."

        Design: Corner/validations/license_expiring_soon_boundary
        """
        from test_helpers import CA_REQUIRED_DOC_TYPES
        # Case A: TX insured, license expiry exactly clock + 30 days -> passes.
        ctx_a = setup_package_compliance_review(
            license_overrides={"expiry_date": "2026-08-31"},
        )
        approved_a = validate_success(api.approve_package(ctx_a["package"]["id"], CO_1))
        assert approved_a["status"] == "APPROVED", "expiry == clock + 30 days passes (inclusive)"
        assert len(approved_a["documents"]) == 7

        # Case B: CA insured, license expiry at clock + 29 days -> rejected.
        validate_success(api.create_license(
            {"state_code": "CA", "license_number": "LIC-CA-1",
             "effective_date": "2026-01-01", "expiry_date": "2026-08-30"}, ADMIN),
            expected_status=201)
        ctx_b = setup_package_compliance_review(
            with_license=False, state="CA",
            broker_overrides={"license_number": "BR-2"},
            insured_overrides={"full_name": "Q", "gender": "F", "ssn_last4": "4321"},
            policy_overrides={"policy_number": "P-B"},
            signed_docs=CA_REQUIRED_DOC_TYPES,
        )
        pkg_b = ctx_b["package"]
        assert len(pkg_b["documents"]) == 8, "CA insured requires STATE_SUPPLEMENT"
        supplement = [r for r in pkg_b["documents"] if r["doc_type"] == "STATE_SUPPLEMENT"]
        assert len(supplement) == 1 and supplement[0]["required"] is True

        resp = api.approve_package(pkg_b["id"], CO_1)
        validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRING_SOON)

    def test_submit_carrier_before_funding_rejected(self, api):
        """PRD §3.4: "An approved package is submitted to the carrier, moving from
        `APPROVED` to `CARRIER_SUBMITTED`; this step requires the case's escrow
        account to be `FUNDED` already, and is rejected with `ERR_ESCROW_NOT_FUNDED`
        (HTTP 409) otherwise."

        Design: Corner/validations/submit_carrier_before_funding_rejected
        """
        ctx = setup_package_approved()
        resp = api.submit_carrier(ctx["package"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_ESCROW_NOT_FUNDED)
        pkg_after = validate_success(api.get_closing_package(ctx["package"]["id"], CM))
        assert pkg_after["status"] == "APPROVED"

    def test_case_manager_cannot_approve_package(self, api):
        """PRD §2.1: "If the role is recognized but does not appear in the
        endpoint's authorized role list, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST | /api/closing-packages/{id}/approve | Compliance approval
        of the closing package | ComplianceOfficer"

        Design: Corner/rbac/case_manager_cannot_approve_package
        """
        ctx = setup_package_compliance_review()
        resp = api.approve_package(ctx["package"]["id"], CM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        pkg_after = validate_success(api.get_closing_package(ctx["package"]["id"], CM))
        assert pkg_after["status"] == "COMPLIANCE_REVIEW"

    def test_withdraw_rejected_while_in_closing(self, api):
        """PRD §3.1: "Withdrawal is never permitted while the case is `IN_CLOSING`;
        that attempt is always rejected with `ERR_CASE_HAS_ACTIVE_CLOSING`
        (HTTP 409)."

        Design: Corner/validations/withdraw_rejected_while_in_closing
        """
        ctx = setup_case_in_closing(portfolio=False)
        case, broker = ctx["case"], ctx["broker"]
        resp = api.withdraw_case(case["id"], make_broker_headers(broker["id"]))
        validate_error(resp, ApiErrorId.ERR_CASE_HAS_ACTIVE_CLOSING)
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "IN_CLOSING"
