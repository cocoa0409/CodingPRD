"""Domain assertion helpers.

These wrap the repeated shapes of assertion the PRD's own narratives describe:
the four system-managed properties every resource carries, the fee chain, the
penalty derivation, the load assessment answer, facility inspection currency,
pagination metadata, and the "nothing was persisted" check that the rejection
ladder promises.
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_TOLERANCE = 0
PCT_TOLERANCE = 0.01
LOAD_TOLERANCE = 0.0001


# --------------------------------------------------------------------------
# Common resource properties (PRD §2.4)
# --------------------------------------------------------------------------


def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every stored resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID without prefix: {resource['id']!r}"
    assert is_iso8601_timestamp(
        resource["created_at"]
    ), f"created_at is not an ISO 8601 UTC timestamp: {resource['created_at']!r}"
    assert is_iso8601_timestamp(
        resource["updated_at"]
    ), f"updated_at is not an ISO 8601 UTC timestamp: {resource['updated_at']!r}"
    assert isinstance(resource["version"], int), "version must be an integer"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_version_advanced_by(before: Dict[str, Any], after: Dict[str, Any], steps: int) -> None:
    """version increments by one on every mutation of the row."""
    assert after["version"] == before["version"] + steps, (
        f"expected version to advance by {steps} from {before['version']}, "
        f"got {after['version']}"
    )


def assert_row_unchanged(before: Dict[str, Any], after: Dict[str, Any], label: str = "row") -> None:
    """A rejected write persists nothing: no field moved and no version bump."""
    assert after == before, f"{label} changed despite a rejected request"


# --------------------------------------------------------------------------
# Numeric precision (PRD §2.7)
# --------------------------------------------------------------------------


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    assert isinstance(actual, int), f"{label} must be an integer number of cents, got {actual!r}"
    assert actual == expected, f"expected {label} of {expected} cents, got {actual}"


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=0.01), (
        f"expected {label} of {expected}, got {actual}"
    )


def assert_four_dp(actual: Any, expected: float, label: str = "value") -> None:
    assert actual == pytest.approx(expected, abs=0.0001), (
        f"expected {label} of {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Permit term posture census (PRD §3.1)
# --------------------------------------------------------------------------


def assert_posture(
    term: Dict[str, Any],
    posture: str,
    behind_measure_count: Optional[int] = None,
    exceeding_outfall_count: Optional[int] = None,
) -> None:
    if behind_measure_count is not None:
        assert term["behind_measure_count"] == behind_measure_count, (
            f"expected behind_measure_count {behind_measure_count}, "
            f"got {term['behind_measure_count']}"
        )
    if exceeding_outfall_count is not None:
        assert term["exceeding_outfall_count"] == exceeding_outfall_count, (
            f"expected exceeding_outfall_count {exceeding_outfall_count}, "
            f"got {term['exceeding_outfall_count']}"
        )
    assert term["compliance_posture"] == posture, (
        f"expected compliance_posture {posture}, got {term['compliance_posture']}"
    )


def assert_measure_attainment(
    measure: Dict[str, Any],
    attainment_pct: float,
    goal_status: str,
) -> None:
    assert_two_dp(measure["attainment_pct"], attainment_pct, "attainment_pct")
    assert measure["goal_status"] == goal_status, (
        f"expected goal_status {goal_status} at attainment {measure['attainment_pct']}, "
        f"got {measure['goal_status']}"
    )


# --------------------------------------------------------------------------
# Utility fee chain (PRD §3.8)
# --------------------------------------------------------------------------


def assert_fee_chain(
    account: Dict[str, Any],
    eru_units: float,
    gross_fee_cents: int,
    class_surcharge_cents: int,
    gross_billable_cents: int,
    total_credit_pct: Optional[float] = None,
    current_net_fee_cents: Optional[int] = None,
) -> None:
    assert_two_dp(account["eru_units"], eru_units, "eru_units")
    assert_cents(account["gross_fee_cents"], gross_fee_cents, "gross_fee_cents")
    assert_cents(account["class_surcharge_cents"], class_surcharge_cents, "class_surcharge_cents")
    assert_cents(account["gross_billable_cents"], gross_billable_cents, "gross_billable_cents")
    assert account["gross_billable_cents"] == (
        account["gross_fee_cents"] + account["class_surcharge_cents"]
    ), "gross_billable_cents must be gross_fee_cents plus class_surcharge_cents"
    if total_credit_pct is not None:
        assert_four_dp(account["total_credit_pct"], total_credit_pct, "total_credit_pct")
    if current_net_fee_cents is not None:
        assert_cents(
            account["current_net_fee_cents"], current_net_fee_cents, "current_net_fee_cents"
        )


# --------------------------------------------------------------------------
# Penalty derivation (PRD §3.6)
# --------------------------------------------------------------------------


def assert_penalty_derivation(
    action: Dict[str, Any],
    action_type: str,
    billable_violation_days: int,
    prior_assessed_total_cents: int,
    escalation_multiplier: float,
    penalty_cents: int,
) -> None:
    assert action["action_type"] == action_type, (
        f"expected action_type {action_type}, got {action['action_type']}"
    )
    assert action["billable_violation_days"] == billable_violation_days, (
        f"expected billable_violation_days {billable_violation_days}, "
        f"got {action['billable_violation_days']}"
    )
    assert_cents(
        action["prior_assessed_total_cents"],
        prior_assessed_total_cents,
        "prior_assessed_total_cents",
    )
    assert_two_dp(
        action["escalation_multiplier"], escalation_multiplier, "escalation_multiplier"
    )
    assert_cents(action["penalty_cents"], penalty_cents, "penalty_cents")


# --------------------------------------------------------------------------
# Inspection score (PRD §3.5)
# --------------------------------------------------------------------------


def assert_deficiency_score(
    inspection: Dict[str, Any], deficiency_score: int, escalation_triggered: bool
) -> None:
    assert isinstance(inspection["deficiency_score"], int), "deficiency_score must be an integer"
    assert inspection["deficiency_score"] == deficiency_score, (
        f"expected deficiency_score {deficiency_score}, got {inspection['deficiency_score']}"
    )
    assert inspection["escalation_triggered"] is escalation_triggered, (
        f"expected escalation_triggered {escalation_triggered} at score "
        f"{inspection['deficiency_score']}, got {inspection['escalation_triggered']}"
    )


# --------------------------------------------------------------------------
# Load assessment answer (PRD §3.7)
# --------------------------------------------------------------------------


def assert_load_assessment(
    assessment: Dict[str, Any],
    variant: str,
    gross_load_lb: float,
    sweeping_credit_lb: float,
    net_load_lb: float,
    tmdl_status: str,
    validated_sample_count: Optional[int] = None,
    projected_sample_count: Optional[int] = None,
) -> None:
    assert assessment["variant"] == variant, (
        f"expected variant {variant}, got {assessment['variant']}"
    )
    if validated_sample_count is not None:
        assert assessment["validated_sample_count"] == validated_sample_count, (
            f"expected validated_sample_count {validated_sample_count}, "
            f"got {assessment['validated_sample_count']}"
        )
    if projected_sample_count is not None:
        assert assessment["projected_sample_count"] == projected_sample_count, (
            f"expected projected_sample_count {projected_sample_count}, "
            f"got {assessment['projected_sample_count']}"
        )
    assert_two_dp(assessment["gross_load_lb"], gross_load_lb, "gross_load_lb")
    assert_two_dp(assessment["sweeping_credit_lb"], sweeping_credit_lb, "sweeping_credit_lb")
    assert_two_dp(assessment["net_load_lb"], net_load_lb, "net_load_lb")
    assert assessment["tmdl_status"] == tmdl_status, (
        f"expected tmdl_status {tmdl_status} at net load {assessment['net_load_lb']}, "
        f"got {assessment['tmdl_status']}"
    )


# --------------------------------------------------------------------------
# Facility inspection currency (PRD §3.5)
# --------------------------------------------------------------------------


def assert_facility_currency(
    facility: Dict[str, Any],
    agreement_status: str,
    months_since_last_inspection: int,
    inspection_overdue: bool,
    credit_eligible: bool,
) -> None:
    assert facility["agreement_status"] == agreement_status, (
        f"expected agreement_status {agreement_status}, got {facility['agreement_status']}"
    )
    assert facility["months_since_last_inspection"] == months_since_last_inspection, (
        f"expected months_since_last_inspection {months_since_last_inspection}, "
        f"got {facility['months_since_last_inspection']}"
    )
    assert facility["inspection_overdue"] is inspection_overdue, (
        f"expected inspection_overdue {inspection_overdue}, got {facility['inspection_overdue']}"
    )
    assert facility["credit_eligible"] is credit_eligible, (
        f"expected credit_eligible {credit_eligible}, got {facility['credit_eligible']}"
    )


# --------------------------------------------------------------------------
# Annual report invalidation (PRD §2.8)
# --------------------------------------------------------------------------


def assert_report_invalidated(
    report: Dict[str, Any], invalidated_reason: str, invalidation_count: int
) -> None:
    assert report["status"] == "DRAFT", (
        f"an invalidated report must be driven back to DRAFT, got {report['status']}"
    )
    assert report["invalidation_count"] == invalidation_count, (
        f"expected invalidation_count {invalidation_count}, got {report['invalidation_count']}"
    )
    assert report["invalidated_reason"] == invalidated_reason, (
        f"expected invalidated_reason {invalidated_reason}, got {report['invalidated_reason']}"
    )
    for field in (
        "compiled_at",
        "compiled_by_user_id",
        "certified_at",
        "certified_by_user_id",
        "certification_statement",
    ):
        assert report[field] is None, f"invalidation must clear {field}, got {report[field]!r}"


# --------------------------------------------------------------------------
# Pagination metadata (PRD §2.3)
# --------------------------------------------------------------------------


def assert_page_meta(
    meta: Dict[str, Any],
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, f"expected has_more {has_more}, got {meta['has_more']}"
