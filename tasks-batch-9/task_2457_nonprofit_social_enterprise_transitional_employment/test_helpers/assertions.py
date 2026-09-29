"""Per-entity shape checks and the domain's reconciliation invariants."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import HOURS_TOLERANCE, PER_HOUR_TOLERANCE, RATIO_TOLERANCE, SCORE_TOLERANCE
from .types import (
    BUSINESS_LINE_STATUSES,
    PARTICIPANT_STATUSES,
    REFERRAL_STATUSES,
    AllocationBasis,
    CheckpointStatus,
    CostCategory,
    CostClassification,
    CostEntryStatus,
    CustomerServiceStandard,
    EmploymentStatus,
    IntakePosture,
    MouStatus,
    MouTier,
    PartnershipStatus,
    PriorityBand,
    ReleasedReason,
    RetentionOutcome,
    ShiftAssignmentStatus,
    SubsidyPeriodStatus,
    SupportActivityStatus,
    SupportCategory,
    WageVerificationStatus,
    WorkShiftStatus,
)


def assert_common_fields(row: Dict[str, Any]) -> None:
    """Every persisted row carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id must be a server-minted UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int), "version must be an integer"
    assert row["version"] >= 1, "version starts at 1 and only increments"


def assert_ratio(value: Optional[float], expected: Optional[float], field: str) -> None:
    """Rates, shares and ratios carry four decimal places."""
    if expected is None:
        assert value is None, f"{field} must be null, got {value!r}"
        return
    assert value is not None, f"{field} must not be null"
    assert value == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_score(value: Optional[float], expected: Optional[float], field: str) -> None:
    """Scores carry two decimal places."""
    if expected is None:
        assert value is None, f"{field} must be null, got {value!r}"
        return
    assert value == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_hours(value: Optional[float], expected: Optional[float], field: str) -> None:
    """Hours carry three decimal places."""
    if expected is None:
        assert value is None, f"{field} must be null, got {value!r}"
        return
    assert value == pytest.approx(expected, abs=HOURS_TOLERANCE), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_per_hour_cents(
    value: Optional[float], expected: Optional[float], field: str
) -> None:
    """The two per-trainee-hour cost ratios carry two decimal places."""
    if expected is None:
        assert value is None, f"{field} must be null, got {value!r}"
        return
    assert value is not None, f"{field} must not be null"
    assert value == pytest.approx(expected, abs=PER_HOUR_TOLERANCE), (
        f"{field}: expected {expected}, got {value}"
    )


def assert_business_line(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in BUSINESS_LINE_STATUSES, row["status"]
    assert row["intake_posture"] in (IntakePosture.OPEN, IntakePosture.CLOSED)
    assert isinstance(row["training_slots_total"], int)
    assert isinstance(row["training_slots_filled"], int)
    assert isinstance(row["supervisor_capacity"], int)
    assert isinstance(row["subsidy_cap_cents"], int)
    assert isinstance(row["cumulative_subsidy_cents"], int)
    assert isinstance(row["quality_incident_count"], int)


def assert_referral_partner(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["mou_tier"] in (MouTier.TIER_1, MouTier.TIER_2, MouTier.TIER_3)
    assert row["mou_status"] in (MouStatus.ACTIVE, MouStatus.LAPSED)
    assert isinstance(row["referral_quota_per_period"], int)
    assert isinstance(row["referrals_submitted_count"], int)
    assert isinstance(row["enrolled_referral_count"], int)


def assert_referral(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in REFERRAL_STATUSES, row["status"]
    assert isinstance(row["declared_barrier_codes"], list)
    assert isinstance(row["verified_barrier_codes"], list)
    if row.get("priority_band") is not None:
        assert row["priority_band"] in (
            PriorityBand.BAND_A,
            PriorityBand.BAND_B,
            PriorityBand.BAND_C,
        )


def assert_participant(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in PARTICIPANT_STATUSES, row["status"]
    assert isinstance(row["wage_cents_per_hour"], int)
    assert isinstance(row["re_entry_count"], int)
    assert isinstance(row["support_activity_minutes"], int)
    assert isinstance(row["delivered_coaching_count"], int)


def assert_work_shift(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        WorkShiftStatus.SCHEDULED,
        WorkShiftStatus.CLOSED,
        WorkShiftStatus.CANCELLED,
    )
    assert row["customer_service_standard"] in (
        CustomerServiceStandard.STANDARD,
        CustomerServiceStandard.PREMIUM,
    )
    assert isinstance(row["trainee_capacity"], int)
    assert isinstance(row["assigned_count"], int)
    assert isinstance(row["quality_defect_count"], int)
    assert isinstance(row["customer_complaint_count"], int)


def assert_shift_assignment(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        ShiftAssignmentStatus.ASSIGNED,
        ShiftAssignmentStatus.COMPLETED,
        ShiftAssignmentStatus.RELEASED,
    )
    if row.get("released_reason") is not None:
        assert row["released_reason"] in (
            ReleasedReason.MANUAL_RELEASE,
            ReleasedReason.SHIFT_CANCELLED,
            ReleasedReason.PARTICIPANT_EXITED,
        )


def assert_support_activity(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        SupportActivityStatus.PLANNED,
        SupportActivityStatus.DELIVERED,
        SupportActivityStatus.VOIDED,
    )
    assert row["category"] in (
        SupportCategory.JOB_COACHING,
        SupportCategory.CASE_MANAGEMENT,
        SupportCategory.TRANSPORT_VOUCHER,
        SupportCategory.CHILDCARE_VOUCHER,
    )
    assert isinstance(row["duration_minutes"], int)
    assert isinstance(row["cost_cents"], int)


def assert_employer(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["partnership_status"] in (
        PartnershipStatus.ACTIVE,
        PartnershipStatus.PROBATION,
        PartnershipStatus.TERMINATED,
    )
    assert isinstance(row["placement_count"], int)
    assert isinstance(row["failed_retention_count"], int)
    assert isinstance(row["confirmed_retention_count"], int)


def assert_placement(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["employment_status"] in (
        EmploymentStatus.ACTIVE,
        EmploymentStatus.SEPARATED_VOLUNTARY,
        EmploymentStatus.SEPARATED_INVOLUNTARY,
    )
    assert row["wage_verification_status"] in (
        WageVerificationStatus.UNVERIFIED,
        WageVerificationStatus.VERIFIED,
        WageVerificationStatus.DISPUTED,
    )
    assert row["retention_outcome"] in (
        RetentionOutcome.PENDING,
        RetentionOutcome.FAILED_EARLY,
        RetentionOutcome.FAILED_LATE,
        RetentionOutcome.RETAINED_180,
    )
    assert isinstance(row["at_risk_flag"], bool)


def assert_retention_checkpoint(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in (
        CheckpointStatus.SCHEDULED,
        CheckpointStatus.CONFIRMED,
        CheckpointStatus.MISSED,
        CheckpointStatus.VOIDED,
    )
    assert row["interval_days"] in (30, 90, 180, 365)
    assert is_iso8601_timestamp(row["due_date"]), row["due_date"]


def assert_subsidy_period(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in (SubsidyPeriodStatus.OPEN, SubsidyPeriodStatus.CLOSED)
    assert row["allocation_basis"] in (AllocationBasis.HOURS, AllocationBasis.REVENUE)
    for money_field in (
        "mission_cost_cents",
        "business_operating_cost_cents",
        "total_cost_cents",
    ):
        assert isinstance(row[money_field], int), f"{money_field} must be integer cents"


def assert_cost_entry(row: Dict[str, Any]) -> None:
    assert_common_fields(row)
    assert row["status"] in (CostEntryStatus.POSTED, CostEntryStatus.VOIDED)
    assert row["category"] in (
        CostCategory.TRAINEE_WAGES,
        CostCategory.SUPERVISION,
        CostCategory.MATERIALS,
        CostCategory.COACHING,
        CostCategory.SUPPORT_SERVICE,
        CostCategory.OVERHEAD,
    )
    assert row["classification"] in (
        CostClassification.MISSION,
        CostClassification.BUSINESS,
        CostClassification.SHARED,
    )
    assert isinstance(row["amount_cents"], int)
    assert isinstance(row["allocated_mission_cents"], int)
    assert isinstance(row["allocated_business_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_ledger_reconciles(period: Dict[str, Any]) -> None:
    """mission_cost_cents plus business_operating_cost_cents equals total_cost_cents."""
    assert (
        period["mission_cost_cents"] + period["business_operating_cost_cents"]
        == period["total_cost_cents"]
    ), (
        f"ledger does not reconcile: {period['mission_cost_cents']} + "
        f"{period['business_operating_cost_cents']} != {period['total_cost_cents']}"
    )


def assert_entry_allocation_complements(entry: Dict[str, Any]) -> None:
    """A posted entry's two allocations always sum back to its amount_cents."""
    assert (
        entry["allocated_mission_cents"] + entry["allocated_business_cents"]
        == entry["amount_cents"]
    ), (
        f"entry allocation does not reconcile: {entry['allocated_mission_cents']} + "
        f"{entry['allocated_business_cents']} != {entry['amount_cents']}"
    )


def assert_period_ledger(
    period: Dict[str, Any],
    mission_cost_cents: int,
    business_operating_cost_cents: int,
    total_cost_cents: int,
    mission_share: Optional[float] = None,
) -> None:
    """Assert the whole mission/business split of a period at once."""
    assert period["mission_cost_cents"] == mission_cost_cents
    assert period["business_operating_cost_cents"] == business_operating_cost_cents
    assert period["total_cost_cents"] == total_cost_cents
    assert_ledger_reconciles(period)
    if mission_share is not None:
        assert_ratio(period["mission_share"], mission_share, "mission_share")


def assert_zeroed_progress_metrics(participant: Dict[str, Any]) -> None:
    """A freshly enrolled or re-entered participant carries zero progress."""
    assert_hours(
        participant["transitional_hours_worked"], 0.000, "transitional_hours_worked"
    )
    assert_hours(
        participant["scheduled_hours_current_week"], 0.000, "scheduled_hours_current_week"
    )
    assert participant["support_activity_minutes"] == 0
    assert participant["delivered_coaching_count"] == 0


def assert_previous_cycle_cleared(participant: Dict[str, Any]) -> None:
    """Re-entry clears every trace of the previous cycle."""
    for field in (
        "readiness_certified_by_user_id",
        "readiness_certified_at",
        "graduated_at",
        "graduation_wage_cents_per_hour",
        "eligible_re_entry_at",
    ):
        assert participant[field] is None, f"{field} must be null after re-entry"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and fractional digits."""
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: Optional[str], field: str) -> None:
    """Compare two ISO 8601 UTC instants by value rather than by spelling."""
    if expected is None:
        assert actual is None, f"{field} must be null, got {actual!r}"
        return
    assert actual is not None, f"{field} must not be null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected {expected}, got {actual}"
    )


def assert_whole_day_instant(value: str, field: str) -> None:
    """Retention dates and period boundaries sit at 00:00:00Z."""
    parsed = parse_instant(value)
    assert (parsed.hour, parsed.minute, parsed.second, parsed.microsecond) == (
        0,
        0,
        0,
        0,
    ), f"{field} must land on 00:00:00Z, got {value}"


def assert_checkpoint_schedule(checkpoints: list, hire_date: Optional[str] = None) -> None:
    """A placement's four checkpoints, listed in ascending interval order."""
    assert len(checkpoints) == 4, f"expected four checkpoints, got {len(checkpoints)}"
    assert [c["interval_days"] for c in checkpoints] == [30, 90, 180, 365]
    for checkpoint in checkpoints:
        assert_retention_checkpoint(checkpoint)
        assert_whole_day_instant(checkpoint["due_date"], "due_date")
        if hire_date is not None:
            expected_due = parse_instant(hire_date) + timedelta(
                days=checkpoint["interval_days"]
            )
            assert parse_instant(checkpoint["due_date"]) == expected_due, (
                f"{checkpoint['interval_days']}-day due_date: expected {expected_due}, "
                f"got {checkpoint['due_date']}"
            )
