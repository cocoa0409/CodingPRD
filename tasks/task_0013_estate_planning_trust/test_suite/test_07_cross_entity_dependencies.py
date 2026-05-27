"""Cross-entity state dependencies.

Estate.finalize depends on aggregate of BeneficiaryDesignation.share_basis_points;
OPEN_PROBATE entry depends on Executor.is_also_beneficiary plus
CONFIRM_EXECUTOR companion order.
"""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    ApiErrorId,
    bootstrap_executor_with_beneficiary_flag,
    create_decedent,
    create_estate,
    create_asset,
    create_designation,
    create_executor,
    accept_executor,
    make_planner_headers,
    make_judge_headers,
)


class TestEstateFinalizeDependsOnDesignationSum:
    """PRD §3.1: cross-entity gate Estate.DRAFT->ALIVE blocked by sibling
    BeneficiaryDesignation aggregate."""

    def test_finalize_blocked_when_shares_under_10000(self, api):
        """PRD §3.1: "the sum of share_basis_points across all designations
        being promoted to ACTIVE must equal exactly 10000 (not merely at
        most 10000 — partial allocation is rejected with
        ERR_SHARE_NOT_FULLY_ALLOCATED)"

        Design: Difficulty/cross_entity_state_dependency/estate_finalize_depends_on_designation_sum
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Rita Suh",
            domicile_state_code="CA", ssn_last4="9999",
        )
        estate = create_estate(dec["id"])
        create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
        # Under-allocated: only 5000bp instead of 10000bp.
        create_designation(estate["id"], "Heir R", "CHILD", 5000)
        resp = api.finalize_plan(estate["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_SHARE_NOT_FULLY_ALLOCATED)

    def test_finalize_blocked_when_no_designations(self, api):
        """PRD §3.1: "the sum of share_basis_points across all designations
        being promoted to ACTIVE must equal exactly 10000 (not merely at
        most 10000 — partial allocation is rejected with
        ERR_SHARE_NOT_FULLY_ALLOCATED)"

        Design: Difficulty/cross_entity_state_dependency/estate_finalize_depends_on_designation_sum
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Rita Suh",
            domicile_state_code="CA", ssn_last4="9990",
        )
        estate = create_estate(dec["id"])
        create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
        # Zero designations means sum=0 ≠ 10000 — still
        # ERR_SHARE_NOT_FULLY_ALLOCATED.
        resp = api.finalize_plan(estate["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_SHARE_NOT_FULLY_ALLOCATED)


class TestOpenProbateDependsOnExecutorStatus:
    """PRD §3.2/§3.5: OPEN_PROBATE entry checks Executor.is_also_beneficiary;
    if true, requires CONFIRM_EXECUTOR companion order ENTERED."""

    def test_open_probate_rejects_when_executor_is_also_beneficiary_without_waiver(self, api):
        """PRD §3.5: "The entry itself enforces the executor-beneficiary
        safety rule: if the confirmed executor's is_also_beneficiary flag is
        true, then a separate CONFIRM_EXECUTOR order must already be ENTERED
        on the same estate (the court waiver); absent that companion order,
        the open-probate entry is rejected with
        ERR_EXECUTOR_BENEFICIARY_CONFLICT."

        Design: Difficulty/cross_entity_state_dependency/open_probate_depends_on_executor_status
        """
        ctx = bootstrap_executor_with_beneficiary_flag(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            is_also_beneficiary=True,
        )
        # Try to enter OPEN_PROBATE without a CONFIRM_EXECUTOR companion.
        resp = api.enter_probate_order(
            ctx["open_order"]["id"], make_judge_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_EXECUTOR_BENEFICIARY_CONFLICT)

    def test_open_probate_succeeds_when_executor_not_beneficiary(self, api):
        """PRD §3.5: "The entry itself enforces the executor-beneficiary
        safety rule: if the confirmed executor's is_also_beneficiary flag is
        true, then a separate CONFIRM_EXECUTOR order must already be ENTERED
        on the same estate (the court waiver); absent that companion order,
        the open-probate entry is rejected with
        ERR_EXECUTOR_BENEFICIARY_CONFLICT."

        Design: Difficulty/cross_entity_state_dependency/open_probate_depends_on_executor_status
        """
        # Inverse case: when is_also_beneficiary=false, no companion needed.
        from test_helpers import bootstrap_estate_in_probate_open
        ctx = bootstrap_estate_in_probate_open(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-15T00:00:00Z",
            executor_is_also_beneficiary=False,
        )
        # Already in PROBATE_OPEN; assert the success path completed.
        assert ctx["estate"]["status"] == "PROBATE_OPEN"
