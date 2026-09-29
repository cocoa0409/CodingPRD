"""Shape checkers and domain invariant checkers.

The per-record checkers assert the presence and primitive type of every field
the contract declares for that record type. The two append-only record types
additionally assert the *absence* of ``updated_at`` and ``version``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentReviewStatus,
    AssignmentStaffingStatus,
    EngagementStatus,
    PhaseStaffingStatus,
    RateModel,
    ReschedulePlanStatus,
    RestrictionStatus,
    ScheduleRiskBand,
    TurnoverRiskBand,
    WaiverStatus,
    WorkloadStatus,
)

MONEY_TOLERANCE = 0.01
HOURS_TOLERANCE = 0.01
PCT_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def assert_common_fields(record: Dict[str, Any]) -> None:
    """Identifier, both timestamps and the mutation counter."""

    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert is_iso8601_timestamp(record["updated_at"]), record["updated_at"]
    assert isinstance(record["version"], int)
    assert record["version"] >= 1


def assert_append_only_fields(record: Dict[str, Any]) -> None:
    """Only an identifier and a creation stamp; no mutation metadata."""

    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "append-only record exposed updated_at"
    assert "version" not in record, "append-only record exposed version"


def assert_money(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=MONEY_TOLERANCE)


def assert_hours(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=HOURS_TOLERANCE)


def assert_pct(value: Any, expected: float) -> None:
    assert value == pytest.approx(expected, abs=PCT_TOLERANCE)


def assert_is_date(value: Any) -> None:
    assert isinstance(value, str) and len(value) == 10, f"not a date: {value!r}"
    assert value[4] == "-" and value[7] == "-", f"not a date: {value!r}"


def _assert_enum(value: Any, enum_cls: Any, field: str) -> None:
    allowed = [member.value for member in enum_cls]
    assert value in allowed, f"{field} {value!r} is outside {allowed}"


# ---------------------------------------------------------------------------
# Record checkers
# ---------------------------------------------------------------------------


def assert_client(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert isinstance(record["name"], str) and record["name"]
    assert isinstance(record["industry_code"], str)
    assert isinstance(record["public_interest_entity"], bool)
    assert_is_date(record["fiscal_year_end"])
    assert isinstance(record["partner_rotation_limit_years"], int)
    assert isinstance(record["engagement_count"], int)
    assert record["engagement_count"] >= 0


def assert_staff_member(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert isinstance(record["full_name"], str) and record["full_name"]
    assert record["level"] in ("STAFF", "SENIOR", "MANAGER", "PARTNER")
    assert record["service_center"] in ("DOMESTIC", "OFFSHORE")
    assert isinstance(record["industry_specialization"], str)
    assert isinstance(record["cpa_licensed"], bool)
    assert isinstance(record["base_weekly_cap_hours"], (int, float))
    assert isinstance(record["hourly_bill_rate"], (int, float))
    assert isinstance(record["review_capable"], bool)
    assert isinstance(record["committed_hours_current_week"], (int, float))
    assert isinstance(record["effective_weekly_cap_hours"], (int, float))
    assert isinstance(record["daily_capacity_hours"], (int, float))
    _assert_enum(record["workload_status"], WorkloadStatus, "workload_status")
    assert isinstance(record["burnout_risk_score_actual"], (int, float))
    assert isinstance(record["burnout_risk_score_committed"], (int, float))
    _assert_enum(record["turnover_risk_band"], TurnoverRiskBand, "turnover_risk_band")


def assert_engagement(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["client_id"])
    assert is_valid_uuid(record["engagement_partner_staff_id"])
    assert record["service_line"] in ("AUDIT", "TAX", "ADVISORY")
    assert isinstance(record["busy_season_year"], int)
    assert_is_date(record["deadline_date"])
    assert isinstance(record["budget_fee_amount"], (int, float))
    _assert_enum(record["status"], EngagementStatus, "status")
    if record.get("pre_block_status") is not None:
        assert record["pre_block_status"] in ("SCHEDULED", "IN_FIELDWORK")
    assert isinstance(record["client_block_count"], int)
    assert isinstance(record["scope_change_count"], int)
    assert isinstance(record["staffing_completion_pct"], (int, float))
    _assert_enum(record["schedule_risk_band"], ScheduleRiskBand, "schedule_risk_band")
    assert isinstance(record["realization_pct_provisional"], (int, float))
    assert isinstance(record["realization_pct_final"], (int, float))


def assert_engagement_phase(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["engagement_id"])
    assert record["phase_type"] in ("PLANNING", "INTERIM", "FIELDWORK", "REVIEW", "WRAP_UP")
    assert isinstance(record["expected_hours"], (int, float))
    assert_is_date(record["window_start_date"])
    assert_is_date(record["window_end_date"])
    assert record["required_level"] in ("STAFF", "SENIOR", "MANAGER", "PARTNER")
    assert isinstance(record["requires_cpa_licensed"], bool)
    _assert_enum(record["staffing_status"], PhaseStaffingStatus, "staffing_status")
    assert isinstance(record["staffed_hours"], (int, float))
    assert isinstance(record["unstaffed_hours"], (int, float))


def assert_assignment(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["engagement_phase_id"])
    assert is_valid_uuid(record["staff_member_id"])
    assert_is_date(record["start_date"])
    assert_is_date(record["end_date"])
    assert isinstance(record["allocated_hours"], (int, float))
    assert isinstance(record["daily_hours"], (int, float))
    assert isinstance(record["calendar_day_count"], int)
    _assert_enum(record["rate_model"], RateModel, "rate_model")
    assert isinstance(record["review_hours_charged"], (int, float))
    assert isinstance(record["fit_score"], (int, float))
    _assert_enum(
        record["staffing_status"], AssignmentStaffingStatus, "staffing_status"
    )
    _assert_enum(record["review_status"], AssignmentReviewStatus, "review_status")
    assert isinstance(record["rework_cycles"], int)


def assert_availability_exception(record: Dict[str, Any]) -> None:
    assert_append_only_fields(record)
    assert is_valid_uuid(record["staff_member_id"])
    assert record["exception_type"] in (
        "PTO",
        "LICENSURE_STUDY_LEAVE",
        "TRAINING",
        "FIRM_HOLIDAY",
    )
    assert_is_date(record["start_date"])
    assert_is_date(record["end_date"])
    assert isinstance(record["available_hours_per_day"], (int, float))


def assert_time_entry(record: Dict[str, Any]) -> None:
    assert_append_only_fields(record)
    assert is_valid_uuid(record["assignment_id"])
    assert_is_date(record["work_date"])
    assert isinstance(record["hours"], (int, float))
    assert record["entry_type"] in ("EXECUTION", "REVIEW", "REWORK")


def assert_independence_restriction(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["client_id"])
    assert is_valid_uuid(record["staff_member_id"])
    assert record["restriction_type"] in (
        "FINANCIAL_INTEREST",
        "EMPLOYMENT_NEGOTIATION",
        "ROTATION_COOLING_OFF",
        "RELATIVE_EMPLOYED",
    )
    assert_is_date(record["effective_start_date"])
    assert_is_date(record["effective_end_date"])
    _assert_enum(record["status"], RestrictionStatus, "status")
    assert isinstance(record["released_assignment_count"], int)


def assert_review_capacity_window(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["reviewer_staff_id"])
    assert_is_date(record["week_start_date"])
    assert isinstance(record["review_capacity_hours"], (int, float))
    assert isinstance(record["committed_review_hours"], (int, float))
    assert isinstance(record["remaining_review_hours"], (int, float))


def assert_reschedule_plan(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["engagement_id"])
    assert record["trigger_reason"] in (
        "CLIENT_READINESS_SLIP",
        "SCOPE_EXPANSION",
        "STAFF_ATTRITION",
    )
    assert isinstance(record["shift_days"], int)
    _assert_enum(record["status"], ReschedulePlanStatus, "status")
    assert isinstance(record["simulation_stale"], bool)


def assert_workload_waiver(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert is_valid_uuid(record["staff_member_id"])
    assert is_valid_uuid(record["engagement_id"])
    assert_is_date(record["week_start_date"])
    assert isinstance(record["extra_hours_allowance"], (int, float))
    _assert_enum(record["status"], WaiverStatus, "status")
    if record.get("expiry_reason") is not None:
        assert record["expiry_reason"] in ("ENGAGEMENT_BLOCKED", "RESTRICTION_IMPOSED")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_phase_hours_partition(phase: Dict[str, Any]) -> None:
    """Staffed plus unstaffed hours reconstitute the phase's expected hours.

    Over-staffed phases clamp the unstaffed figure at zero, so the sum can
    exceed the expected total but never fall short of it.
    """

    total = phase["staffed_hours"] + phase["unstaffed_hours"]
    assert total >= pytest.approx(phase["expected_hours"], abs=HOURS_TOLERANCE)
    assert phase["unstaffed_hours"] >= 0.0
    if phase["staffed_hours"] <= phase["expected_hours"]:
        assert_hours(total, phase["expected_hours"])


def assert_workload_remaining_consistent(workload: Dict[str, Any]) -> None:
    """Remaining hours are the effective cap less the committed hours."""

    assert_hours(
        workload["remaining_week_hours"],
        workload["effective_weekly_cap_hours"] - workload["committed_hours"],
    )


def assert_review_window_remaining_consistent(window: Dict[str, Any]) -> None:
    """Remaining review hours are the capacity less the committed hours."""

    assert_hours(
        window["remaining_review_hours"],
        window["review_capacity_hours"] - window["committed_review_hours"],
    )


def assert_daily_capacity_consistent(staff: Dict[str, Any]) -> None:
    """Daily capacity spreads the effective weekly cap over five working days."""

    assert_hours(
        staff["daily_capacity_hours"], round(staff["effective_weekly_cap_hours"] / 5, 2)
    )


def assert_clean_workload_slate(staff: Dict[str, Any]) -> None:
    """A freshly registered staff member carries no commitments and no risk."""

    assert_hours(staff["committed_hours_current_week"], 0.00)
    assert staff["workload_status"] == "GREEN"
    assert_hours(staff["burnout_risk_score_actual"], 0.00)
    assert_hours(staff["burnout_risk_score_committed"], 0.00)
    assert staff["turnover_risk_band"] == "LOW"


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_total: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """The envelope's meta object carries the four pagination figures."""

    assert isinstance(meta["limit"], int)
    assert isinstance(meta["offset"], int)
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_total is not None:
        assert meta["total_count"] == expected_total
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None


__all__ = [
    "MONEY_TOLERANCE",
    "HOURS_TOLERANCE",
    "PCT_TOLERANCE",
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_money",
    "assert_hours",
    "assert_pct",
    "assert_is_date",
    "assert_client",
    "assert_staff_member",
    "assert_engagement",
    "assert_engagement_phase",
    "assert_assignment",
    "assert_availability_exception",
    "assert_time_entry",
    "assert_independence_restriction",
    "assert_review_capacity_window",
    "assert_reschedule_plan",
    "assert_workload_waiver",
    "assert_phase_hours_partition",
    "assert_workload_remaining_consistent",
    "assert_review_window_remaining_consistent",
    "assert_daily_capacity_consistent",
    "assert_clean_workload_slate",
    "assert_pagination_meta",
    "find_by_id",
]
