"""Boundary-precision checks on different metrics/endpoints.

Creditor 120-day window: strict-> rejected; exactly-at boundary accepted.
Empty designation set on finalize-plan: count==0 ≠ 10000 → reject.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    ApiErrorId,
    bootstrap_estate_in_administration,
    bootstrap_estate_in_draft,
    create_decedent,
    create_estate,
    create_asset,
    create_creditor_claim,
    make_creditor_headers,
    make_planner_headers,
)


class TestCreditorWindowStrictAt120Days:
    """PRD §3.6: at exactly 120 days the claim is accepted; one second past,
    rejected."""

    def test_claim_filed_exactly_at_120_days_accepted(self, api):
        """PRD §3.6: "a claim filed exactly at the one-hundred-twenty-day
        mark is still accepted, but a claim filed even one second beyond
        that point is rejected with ERR_CREDITOR_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/creditor_window_strict_at_120_days
        """
        # Probate opened on 2026-01-01; 120-day window expires 2026-05-01.
        ctx = bootstrap_estate_in_administration(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-01T00:00:00Z",
            asset_value_cents=1000000,
            domicile_state_code="FL",
        )
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_creditor_claim(
            {
                "estate_id": ctx["estate"]["id"],
                "creditor_name": "JustInTime",
                "amount_cents": 10000,
                "claim_class": "UNSECURED",
                "filed_at": "2026-05-01T00:00:00Z",
            },
            make_creditor_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "FILED", (
            f"Claim filed at exact 120-day boundary should be FILED, "
            f"got {data['status']!r}"
        )

    def test_claim_filed_one_second_late_rejected(self, api):
        """PRD §3.6: "a claim filed exactly at the one-hundred-twenty-day
        mark is still accepted, but a claim filed even one second beyond
        that point is rejected with ERR_CREDITOR_WINDOW_CLOSED."

        Design: Difficulty/boundary_precision_check/creditor_window_strict_at_120_days
        """
        ctx = bootstrap_estate_in_administration(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-01T00:00:00Z",
            asset_value_cents=1000000,
            domicile_state_code="FL",
        )
        set_clock("2026-05-01T00:00:01Z")
        resp = api.create_creditor_claim(
            {
                "estate_id": ctx["estate"]["id"],
                "creditor_name": "OneSecLate",
                "amount_cents": 10000,
                "claim_class": "UNSECURED",
                "filed_at": "2026-05-01T00:00:01Z",
            },
            make_creditor_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CREDITOR_WINDOW_CLOSED)


class TestEmptyDesignationSetOnFinalize:
    """PRD §3.1: finalize requires sum of share_basis_points being promoted
    to ACTIVE equals exactly 10000 — zero designations means sum==0≠10000."""

    def test_finalize_with_zero_designations_rejected(self, api):
        """PRD §3.1: "the sum of share_basis_points across all designations
        being promoted to ACTIVE must equal exactly 10000 (not merely at
        most 10000 — partial allocation is rejected with
        ERR_SHARE_NOT_FULLY_ALLOCATED)"

        Design: Difficulty/boundary_precision_check/empty_designation_set_on_finalize_plan
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Quinn Rojas",
            domicile_state_code="TX", ssn_last4="8888",
        )
        estate = create_estate(dec["id"])
        # Add asset only — no designations.
        create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
        resp = api.finalize_plan(estate["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_SHARE_NOT_FULLY_ALLOCATED)

    def test_finalize_with_partial_allocation_rejected(self, api):
        """PRD §3.1: "the sum of share_basis_points across all designations
        being promoted to ACTIVE must equal exactly 10000 (not merely at
        most 10000 — partial allocation is rejected with
        ERR_SHARE_NOT_FULLY_ALLOCATED)"

        Design: Difficulty/boundary_precision_check/empty_designation_set_on_finalize_plan
        """
        # Boundary variant: still rejecting non-exact 10000.
        from test_helpers import create_designation
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Half Allocator",
            domicile_state_code="TX", ssn_last4="8889",
        )
        estate = create_estate(dec["id"])
        create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
        # Only 5000bp.
        create_designation(estate["id"], "Heir Half", "CHILD", 5000)
        resp = api.finalize_plan(estate["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_SHARE_NOT_FULLY_ALLOCATED)
