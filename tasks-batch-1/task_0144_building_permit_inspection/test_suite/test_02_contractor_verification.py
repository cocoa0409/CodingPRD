"""Contractor verification posture: independent license and bond legs, the
$15,000 bond floor, the strict license-expiry boundary at issue, and the
SUSPENDED-license gate on issuance.

PRD §2.10 (verification posture), §3.6 (issuance gates).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_contractor,
    create_jurisdiction,
    create_approved_permit,
    pay_in_full,
    current_version,
    set_clock,
    make_clerk_headers,
)


class TestVerificationPostureLegs:
    def test_bond_below_floor_scores_failed(self, api):
        """PRD §2.10: "The bond leg holds when `bond_status` is `VERIFIED` and
        `bond_amount` is at least the required bond floor of $15,000; a bond of
        exactly $15,000 satisfies the floor, while any lesser amount, or a
        `bond_status` of `UNVERIFIED` or `REVOKED`, fails the bond leg."

        Design: Difficulty/dual_variant_calc/contractor_verification_posture_license_vs_bond
        """
        con = create_contractor(license_status="ACTIVE",
                                license_expiry="2030-01-01T00:00:00Z",
                                bond_amount=14999, bond_status="VERIFIED")
        assert con["verification_status"] == "FAILED"

    def test_bond_at_floor_scores_verified(self, api):
        """PRD §2.10: "a bond of exactly $15,000 satisfies the floor" ... "only
        when both hold does the contractor read `VERIFIED`."

        Design: Difficulty/dual_variant_calc/contractor_verification_posture_license_vs_bond
        """
        con = create_contractor(license_status="ACTIVE",
                                license_expiry="2030-01-01T00:00:00Z",
                                bond_amount=15000, bond_status="VERIFIED")
        assert con["verification_status"] == "VERIFIED"


class TestLicenseExpiryBoundaryAtIssue:
    def test_clock_equal_to_license_expiry_fails_issue(self, api):
        """PRD §2.10: "The license leg holds when `license_status` is `ACTIVE` and
        the current clock instant is strictly before `license_expiry` — a
        contractor whose clock has reached or passed `license_expiry` fails the
        license leg even if the status still reads `ACTIVE`".
        PRD §3.6: "The referenced contractor's `verification_status` must be
        `VERIFIED` — license active and current and bond verified and sufficient —
        or the request is rejected with `ERR_CONTRACTOR_UNVERIFIED`."

        Design: Difficulty/boundary_precision_check/license_expiry_strict_less_than_at_issue
        """
        set_clock("2026-06-30T00:00:00Z")
        jur = create_jurisdiction()
        con = create_contractor(license_status="ACTIVE",
                                license_expiry="2026-06-30T00:00:00Z",
                                bond_amount=20000, bond_status="VERIFIED")
        # Re-read confirms the verification flips FAILED at clock == expiry.
        con_read = validate_success(api.get_contractor(con["id"], make_clerk_headers()))
        assert con_read["verification_status"] == "FAILED"

        permit, _review, _rev = create_approved_permit(
            jurisdiction_id=jur["id"], contractor_id=con["id"],
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_UNVERIFIED.value)


    def test_clock_one_second_before_expiry_keeps_license_current(self, api):
        """PRD §2.10: "The license leg holds when `license_status` is `ACTIVE` and
        the current clock instant is strictly before `license_expiry`".

        Design: Difficulty/boundary_precision_check/license_expiry_strict_less_than_at_issue
        """
        # Clock strictly before expiry: the X-1 side of the strict-< boundary.
        set_clock("2026-06-29T23:59:59Z")
        con = create_contractor(license_status="ACTIVE",
                                license_expiry="2026-06-30T00:00:00Z",
                                bond_amount=20000, bond_status="VERIFIED")
        con_read = validate_success(api.get_contractor(con["id"], make_clerk_headers()))
        assert con_read["verification_status"] == "VERIFIED"


class TestContractorUnverifiedGatesIssue:
    def test_suspended_license_blocks_issue(self, api):
        """PRD §2.10: "any contractor whose `license_status` is `SUSPENDED` or
        `EXPIRED`" fails the license leg.
        PRD §3.6: "The referenced contractor's `verification_status` must be
        `VERIFIED` — license active and current and bond verified and sufficient —
        or the request is rejected with `ERR_CONTRACTOR_UNVERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_depends_on_contractor_verification
        """
        jur = create_jurisdiction()
        con = create_contractor(license_status="SUSPENDED",
                                license_expiry="2030-01-01T00:00:00Z",
                                bond_amount=20000, bond_status="VERIFIED")
        assert con["verification_status"] == "FAILED"

        permit, _review, _rev = create_approved_permit(
            jurisdiction_id=jur["id"], contractor_id=con["id"],
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_UNVERIFIED.value)
        # The permit transition is gated — it stays APPROVED.
        permit_read = validate_success(api.get_permit(permit["id"], make_clerk_headers()))
        assert permit_read["status"] == "APPROVED"

    def test_unverified_contractor_blocks_issue_second_scenario(self, api):
        """PRD §3.6: "The referenced contractor's `verification_status` must be
        `VERIFIED` — license active and current and bond verified and sufficient —
        or the request is rejected with `ERR_CONTRACTOR_UNVERIFIED`."

        Design: Difficulty/cross_entity_state_dependency/permit_issue_depends_on_contractor_verification
        """
        jur = create_jurisdiction()
        con = create_contractor(license_status="ACTIVE",
                                license_expiry="2030-01-01T00:00:00Z",
                                bond_amount=10000, bond_status="VERIFIED")
        assert con["verification_status"] == "FAILED"

        permit, _review, _rev = create_approved_permit(
            jurisdiction_id=jur["id"], contractor_id=con["id"],
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        pv = current_version(permit["id"])
        resp = api.issue_permit(permit["id"],
                                {"expected_permit_application_version": pv},
                                make_clerk_headers())
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_UNVERIFIED.value)
