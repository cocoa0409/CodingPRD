"""Resource assertions and domain invariant checkers for the rehabilitation API."""

from datetime import datetime, timezone
from typing import Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    PERFORMANCE_SCORE_MAX,
    PERFORMANCE_SCORE_MIN,
)


# ---------------------------------------------------------------------------
# Shared record properties (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict) -> None:
    """Every persisted resource carries a UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC: {data.get('created_at')!r}"


def assert_versioned_fields(data: dict) -> None:
    """Twelve of the thirteen resource types also carry `updated_at` and `version`."""
    assert_common_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


# ---------------------------------------------------------------------------
# Per-resource assertions
# ---------------------------------------------------------------------------


def assert_program_year(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["fiscal_year"], int)
    for money in (
        "ami_median_income_cents",
        "max_loan_amount_cents",
        "allocation_budget_cents",
        "committed_amount_cents",
        "disbursed_amount_cents",
        "program_income_balance_cents",
        "uncommitted_amount_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer of cents"
    assert_program_year_ledger_conserved(data)


def assert_applicant(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert 1 <= data["household_size"] <= 8
    assert data["income_calc_method"] in ("PART_5_ANNUAL", "IRS_1040_ADJUSTED")
    assert data["eligibility_status"] in ("APPLIED", "INCOME_VERIFIED", "INELIGIBLE")
    if data.get("income_category") is not None:
        assert data["income_category"] in (
            "EXTREMELY_LOW",
            "VERY_LOW",
            "LOW",
            "OVER_INCOME",
        )
    if data.get("ami_percent") is not None:
        assert_ami_percent_precision(data["ami_percent"])


def assert_rehab_application(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["workflow_state"] in (
        "INTAKE",
        "OWNERSHIP_VERIFIED",
        "INSPECTED",
        "WRITEUP_APPROVED",
        "BID_OPEN",
        "BID_FAILED",
        "AWARDED",
        "UNDER_CONSTRUCTION",
        "CONSTRUCTION_COMPLETE",
        "CLOSED",
        "DENIED",
    )
    assert data["compliance_posture"] in (
        "CLEAR",
        "LEAD_HOLD",
        "HISTORIC_HOLD",
        "DUAL_HOLD",
        "CLEARED_WITH_PROTOCOL",
        "ADVERSE_EFFECT_BLOCKED",
    )
    assert data["ownership_verification_status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert isinstance(data["lead_review_required"], bool)
    assert isinstance(data["historic_review_required"], bool)
    assert isinstance(data["lead_hazard_detected"], bool)
    assert data["lead_hazard_control_method"] in (
        "NONE",
        "INTERIM_CONTROLS",
        "ABATEMENT",
    )
    assert 1850 <= data["year_built"] <= 2026


def assert_property_inspection(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["inspection_type"] in ("INITIAL_STANDARDS", "DRAW", "FINAL")
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert isinstance(data["performed_by_user_id"], str) and data[
        "performed_by_user_id"
    ]
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert isinstance(data["deficiency_count"], int) and data["deficiency_count"] >= 0
    assert isinstance(data["lead_hazard_present"], bool)
    if data.get("result") is not None:
        assert data["result"] in ("PASS", "FAIL")


def assert_work_write_up(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["state"] in (
        "DRAFT",
        "SUBMITTED",
        "REVISION_REQUESTED",
        "APPROVED",
        "SUPERSEDED",
    )
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    for money in (
        "base_estimate_cents",
        "contingency_cents",
        "total_estimate_cents",
        "priority_repair_total_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0
    assert isinstance(data["work_item_count"], int) and data["work_item_count"] >= 0
    assert_write_up_roll_up(data)


def assert_work_item(data: dict) -> None:
    """A repair line carries only `id` and `created_at` — no `updated_at`, no `version`."""
    assert_common_fields(data)
    assert "updated_at" not in data, "a repair line has no updated_at field"
    assert "version" not in data, "a repair line has no version field"
    assert data["category"] in (
        "ROOF",
        "ELECTRICAL",
        "PLUMBING",
        "HVAC",
        "LEAD_HAZARD_CONTROL",
        "ACCESSIBILITY",
        "WINDOWS",
        "STRUCTURAL",
    )
    assert data["priority_class"] in (
        "HEALTH_SAFETY",
        "CODE",
        "INCIPIENT",
        "GENERAL_PROPERTY_IMPROVEMENT",
    )
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] > 0
    assert isinstance(data["is_lead_hazard_reduction"], bool)
    assert isinstance(data["is_historic_sensitive"], bool)


def assert_contractor(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["approved_list_status"] in (
        "APPROVED",
        "PROBATION",
        "SUSPENDED",
        "REMOVED",
    )
    assert isinstance(data["lead_safe_certified"], bool)
    assert isinstance(data["historic_qualified"], bool)
    assert_performance_score_clamped(data["performance_score"])
    for counter in (
        "open_complaint_count",
        "sanction_count",
        "on_time_completion_count",
        "active_award_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_bid_solicitation(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("OPEN", "TABULATED", "AWARDED", "FAILED")
    assert 1 <= data["min_bids_required"] <= 5
    assert isinstance(data["independent_cost_estimate_cents"], int)
    assert data["responsive_floor_cents"] <= data["responsive_ceiling_cents"]
    for counter in ("bid_count", "responsive_bid_count", "reopen_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_bid(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in (
        "SUBMITTED",
        "RESPONSIVE",
        "NON_RESPONSIVE",
        "AWARDED",
        "REJECTED",
        "WITHDRAWN_BY_PROGRAM",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["proposed_end_date"] >= data["proposed_start_date"]
    if data.get("non_responsive_reason") is not None:
        assert data["non_responsive_reason"] in (
            "OVER_CEILING",
            "UNDER_FLOOR",
            "CONTRACTOR_NOT_APPROVED",
            "NOT_LEAD_CERTIFIED",
        )


def assert_rehab_loan(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["structure_type"] in ("DEFERRED", "FORGIVABLE", "AMORTIZING")
    assert data["status"] in (
        "STRUCTURED",
        "LIEN_RECORDED",
        "DISBURSING",
        "FULLY_DISBURSED",
        "SERVICING",
        "RECAPTURED",
        "FORGIVEN",
    )
    for money in (
        "awarded_bid_amount_cents",
        "approved_project_cost_cents",
        "lien_recording_fee_cents",
        "principal_cents",
        "monthly_payment_cents",
        "contract_earned_cents",
        "disbursed_cents",
        "retainage_held_cents",
        "forgiven_cents",
        "principal_repaid_cents",
        "unforgiven_balance_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer of cents"
        assert data[money] >= 0, f"{money} must not be negative"


def assert_draw_request(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in (
        "SUBMITTED",
        "INSPECTION_PASSED",
        "INSPECTION_FAILED",
        "APPROVED",
        "PAID",
    )
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] > 0
    assert isinstance(data["is_final_draw"], bool)


def assert_change_order(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED")
    assert isinstance(data["amount_delta_cents"], int)
    assert data["amount_delta_cents"] != 0
    assert isinstance(data["justification"], str) and data["justification"]
    assert isinstance(data["affects_lead_hazard_work"], bool)
    assert_cumulative_delta_precision(data["cumulative_delta_pct"])


def assert_complaint_case(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in (
        "FILED",
        "CONTRACTOR_NOTIFIED",
        "REMEDIED",
        "DISMISSED",
        "ESCALATED",
        "SANCTIONED",
    )
    assert data["defect_category"] in (
        "WORKMANSHIP",
        "INCOMPLETE_WORK",
        "MATERIAL_DEFECT",
        "WARRANTY_REFUSAL",
    )
    assert is_iso8601_timestamp(data["filed_at"])
    if data.get("sanction_level") is not None:
        assert data["sanction_level"] in ("PROBATION", "SUSPENSION", "REMOVAL")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_program_year_ledger_conserved(program_year: dict) -> None:
    """`allocation_budget_cents` + `program_income_balance_cents` equals the triad."""
    left = (
        program_year["allocation_budget_cents"]
        + program_year["program_income_balance_cents"]
    )
    right = (
        program_year["uncommitted_amount_cents"]
        + program_year["committed_amount_cents"]
        + program_year["disbursed_amount_cents"]
    )
    assert left == right, (
        "Program-year ledger is not conserved: "
        f"allocation {program_year['allocation_budget_cents']} + program income "
        f"{program_year['program_income_balance_cents']} = {left}, but uncommitted "
        f"{program_year['uncommitted_amount_cents']} + committed "
        f"{program_year['committed_amount_cents']} + disbursed "
        f"{program_year['disbursed_amount_cents']} = {right}"
    )
    assert program_year["uncommitted_amount_cents"] >= 0, (
        "uncommitted_amount_cents may never be negative"
    )
    assert program_year["committed_amount_cents"] >= 0, (
        "committed_amount_cents may never be negative"
    )


def assert_construction_identity_conserved(loan: dict) -> None:
    """`contract_earned_cents` + `lien_recording_fee_cents` == `disbursed_cents` + `retainage_held_cents`."""
    left = loan["contract_earned_cents"] + loan["lien_recording_fee_cents"]
    right = loan["disbursed_cents"] + loan["retainage_held_cents"]
    assert left == right, (
        "Construction money identity broken: contract_earned "
        f"{loan['contract_earned_cents']} + fee {loan['lien_recording_fee_cents']} "
        f"= {left}, but disbursed {loan['disbursed_cents']} + retainage_held "
        f"{loan['retainage_held_cents']} = {right}"
    )


def assert_settlement_identity_conserved(loan: dict) -> None:
    """`forgiven` + `principal_repaid` + `recapture_amount` + `shortfall_forgiven` == `principal`."""
    total = (
        loan["forgiven_cents"]
        + loan["principal_repaid_cents"]
        + (loan["recapture_amount_cents"] or 0)
        + (loan["shortfall_forgiven_cents"] or 0)
    )
    assert total == loan["principal_cents"], (
        "Settlement identity broken: forgiven "
        f"{loan['forgiven_cents']} + repaid {loan['principal_repaid_cents']} + "
        f"recapture {loan['recapture_amount_cents']} + shortfall "
        f"{loan['shortfall_forgiven_cents']} = {total}, principal "
        f"{loan['principal_cents']}"
    )


def assert_write_up_roll_up(write_up: dict) -> None:
    """`total_estimate_cents` is `base_estimate_cents` plus `contingency_cents`."""
    assert (
        write_up["total_estimate_cents"]
        == write_up["base_estimate_cents"] + write_up["contingency_cents"]
    ), (
        "total_estimate_cents must equal base_estimate_cents + contingency_cents: "
        f"{write_up['total_estimate_cents']} != {write_up['base_estimate_cents']} + "
        f"{write_up['contingency_cents']}"
    )
    assert write_up["priority_repair_total_cents"] <= write_up["base_estimate_cents"], (
        "priority_repair_total_cents is a subset sum of base_estimate_cents"
    )


def assert_ami_percent_precision(ami_percent: float) -> None:
    """`ami_percent` is rounded half up to one decimal place."""
    assert round(float(ami_percent), 1) == pytest.approx(float(ami_percent)), (
        f"ami_percent {ami_percent} carries more than one decimal place"
    )


def assert_cumulative_delta_precision(cumulative_delta_pct: float) -> None:
    """`cumulative_delta_pct` is rounded half up to two decimal places."""
    assert round(float(cumulative_delta_pct), 2) == pytest.approx(
        float(cumulative_delta_pct)
    ), f"cumulative_delta_pct {cumulative_delta_pct} carries more than two decimals"


def assert_performance_score_clamped(performance_score: int) -> None:
    """`performance_score` is an integer confined to the closed range 0 to 100."""
    assert isinstance(performance_score, int), "performance_score must be an integer"
    assert PERFORMANCE_SCORE_MIN <= performance_score <= PERFORMANCE_SCORE_MAX, (
        f"performance_score {performance_score} is outside the closed range 0..100"
    )


def assert_money_cents(value, field_name: str = "amount") -> None:
    """All monetary amounts are integers denominated in cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer number of cents, got {value!r}"
    )


def assert_instant(data: dict, field_name: str, expected: str) -> None:
    """Assert a timestamp field carries an expected instant, whatever its rendering.

    PRD §2.5 fixes the three-fractional-digit rendering for `created_at` and
    `updated_at` only, so business timestamps such as `scheduled_start_at`,
    `bid_due_at`, `filed_at` and `resolved_at` may legitimately be serialised
    either with or without fractional digits. The instant they denote is what the
    PRD specifies, so it is the instant that is compared here.
    """
    actual = data.get(field_name)
    assert actual is not None, f"{field_name} should be set, got {actual!r}"
    assert is_iso8601_timestamp(actual), (
        f"{field_name} must be an ISO 8601 UTC timestamp, got {actual!r}"
    )
    assert _instant(actual) == _instant(expected), (
        f"Expected {field_name} at {expected}, got {actual}"
    )


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, with or without fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_unset(data: dict, field_name: str) -> None:
    """A field the PRD describes as unset is either absent or null."""
    assert data.get(field_name) is None, (
        f"{field_name} should still be unset, got {data.get(field_name)!r}"
    )


def assert_two_axes(
    application: dict,
    workflow_state: str,
    compliance_posture: Optional[str] = None,
) -> None:
    """Assert one or both of the application's two independent state axes."""
    assert application["workflow_state"] == workflow_state, (
        f"Expected workflow_state {workflow_state}, got "
        f"{application['workflow_state']}"
    )
    if compliance_posture is not None:
        assert application["compliance_posture"] == compliance_posture, (
            f"Expected compliance_posture {compliance_posture}, got "
            f"{application['compliance_posture']}"
        )
