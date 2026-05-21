"""Currently Not Collectible eligibility, lifecycle, and review-due
expiration. PRD §3.11.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CNC_MAX_MDI_CENTS,
    assert_cnc_status,
    create_cnc_payload,
    create_taxpayer,
    create_tax_liability,
    get_tax_liability,
    place_cnc,
    setup_two_taxpayers_for_cnc_mdi_boundary,
    validate_error,
    validate_success,
)


class TestCNCEligibilityBoundary:

    def test_cnc_at_mdi_zero_is_eligible_inclusive_boundary(self, api,
                                                            irs_officer_headers):
        """PRD §3.11: "the taxpayer's monthly_disposable_income_cents
        must be at most zero (inclusive — exactly zero is eligible,
        but one cent of disposable income fails the check)."

        Claim: MDI == 0 → CNC placement succeeds (boundary inclusive).

        # difficulty: boundary_precision_check/cnc_eligibility_mdi_zero_inclusive
        """
        a_zero, liab_a, b_above, liab_b = (
            setup_two_taxpayers_for_cnc_mdi_boundary()
        )
        payload = create_cnc_payload(
            a_zero["id"], [liab_a["id"]],
            hardship_reason="NEGATIVE_DISPOSABLE_INCOME",
        )
        resp = api.create_cnc_status(payload, irs_officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_cnc_status(data)
        assert data["status"] == "ACTIVE"

    def test_cnc_at_mdi_one_cent_is_ineligible(self, api,
                                               irs_officer_headers):
        """PRD §3.11: "exactly zero is eligible, but one cent of
        disposable income fails the check. A CNC placement that
        violates eligibility is rejected with ERR_CNC_NOT_ELIGIBLE."

        Claim: MDI == 1 → ERR_CNC_NOT_ELIGIBLE.

        # difficulty: boundary_precision_check/cnc_eligibility_mdi_zero_inclusive
        """
        a_zero, liab_a, b_above, liab_b = (
            setup_two_taxpayers_for_cnc_mdi_boundary()
        )
        payload = create_cnc_payload(
            b_above["id"], [liab_b["id"]],
            hardship_reason="NEGATIVE_DISPOSABLE_INCOME",
        )
        resp = api.create_cnc_status(payload, irs_officer_headers)
        validate_error(resp, ApiErrorId.ERR_CNC_NOT_ELIGIBLE.value)


class TestCNCSideEffects:

    def test_cnc_placement_moves_liability_to_cnc(self, api):
        """PRD §3.11: "Each covered liability transitions from OPEN to
        CNC."

        Claim: post-placement liability.status == CNC.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=0)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=500_000,
        )
        place_cnc(taxpayer["id"], [liability["id"]])
        refreshed = get_tax_liability(liability["id"])
        assert refreshed["status"] == "CNC"
