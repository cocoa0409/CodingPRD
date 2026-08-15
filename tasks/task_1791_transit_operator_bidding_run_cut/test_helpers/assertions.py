"""Entity assertions and domain invariant checkers.

Each assert_{entity} verifies the common system-managed properties (id as
UUID, ISO 8601 timestamps, integer version) plus the entity's own fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AbsenceCaseStatus,
    AbsenceReasonCode,
    AssignmentSource,
    BidEntryStatus,
    DailyAssignmentStatus,
    ExtraBoardSlotStatus,
    GrievanceCaseStatus,
    GrievanceCategory,
    OperatorStatus,
    PayRecordVariant,
    PayStatus,
    RunStatus,
    SignUpPeriodStatus,
    VacationSlotStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_sign_up_period(data: dict):
    _assert_common(data, "SignUpPeriod")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["effective_start_date"], str)
    assert isinstance(data["effective_end_date"], str)
    assert isinstance(data["spread_limit_minutes"], int)
    assert isinstance(data["paid_break_minutes"], int)
    assert isinstance(data["daily_ot_threshold_minutes"], int)
    assert isinstance(data["weekly_ot_threshold_minutes"], int)
    assert isinstance(data["extra_board_ratio_pct"], int)
    assert isinstance(data["schedule_revision"], int) and data["schedule_revision"] >= 1
    assert data["status"] in [s.value for s in SignUpPeriodStatus]
    assert isinstance(data["picked_through_rank"], int) and data["picked_through_rank"] >= 0


def assert_run(data: dict):
    _assert_common(data, "Run")
    assert isinstance(data["sign_up_period_id"], str)
    assert isinstance(data["schedule_revision"], int) and data["schedule_revision"] >= 1
    assert isinstance(data["run_number"], str) and data["run_number"]
    assert isinstance(data["service_date"], str)
    assert isinstance(data["pieces"], list) and len(data["pieces"]) >= 1
    for piece in data["pieces"]:
        assert piece["release_minutes"] > piece["report_minutes"], (
            "each piece must have release_minutes > report_minutes"
        )
    assert isinstance(data["spread_minutes"], int)
    assert isinstance(data["platform_minutes"], int)
    assert isinstance(data["paid_minutes"], int)
    assert data["status"] in [s.value for s in RunStatus]


def assert_operator(data: dict):
    _assert_common(data, "Operator")
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["hire_date"], str)
    assert isinstance(data["seniority_rank"], int) and data["seniority_rank"] >= 1
    assert data["status"] in [s.value for s in OperatorStatus]
    assert isinstance(data["weekly_ot_minutes_accum"], int)
    assert isinstance(data["vacation_hours_balance"], int)


def assert_bid_entry(data: dict):
    _assert_common(data, "BidEntry")
    assert isinstance(data["sign_up_period_id"], str)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["run_id"], str)
    assert isinstance(data["preference_rank"], int) and data["preference_rank"] >= 1
    assert data["status"] in [s.value for s in BidEntryStatus]


def assert_extra_board_slot(data: dict):
    _assert_common(data, "ExtraBoardSlot")
    assert isinstance(data["sign_up_period_id"], str)
    assert isinstance(data["slot_index"], int) and data["slot_index"] >= 1
    assert data["status"] in [s.value for s in ExtraBoardSlotStatus]


def assert_daily_assignment(data: dict):
    _assert_common(data, "DailyAssignment")
    assert isinstance(data["sign_up_period_id"], str)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["service_date"], str)
    assert data["source"] in [s.value for s in AssignmentSource]
    assert isinstance(data["scheduled_minutes"], int)
    assert data["status"] in [s.value for s in DailyAssignmentStatus]
    assert data["pay_status"] in [s.value for s in PayStatus]


def assert_absence_case(data: dict):
    _assert_common(data, "AbsenceCase")
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["absence_date"], str)
    assert data["reason_code"] in [s.value for s in AbsenceReasonCode]
    assert data["status"] in [s.value for s in AbsenceCaseStatus]


def assert_pay_record(data: dict):
    _assert_common(data, "PayRecord")
    assert isinstance(data["daily_assignment_id"], str)
    assert isinstance(data["straight_minutes"], int) and data["straight_minutes"] >= 0
    assert isinstance(data["overtime_minutes"], int) and data["overtime_minutes"] >= 0
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert data["variant"] in [s.value for s in PayRecordVariant]


def assert_vacation_slot(data: dict):
    _assert_common(data, "VacationSlot")
    assert isinstance(data["sign_up_period_id"], str)
    assert isinstance(data["week_start_date"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["allocated_count"], int) and data["allocated_count"] >= 0
    assert data["allocated_count"] <= data["capacity"], (
        f"allocated_count {data['allocated_count']} exceeds capacity {data['capacity']}"
    )
    assert data["status"] in [s.value for s in VacationSlotStatus]


def assert_grievance_case(data: dict):
    _assert_common(data, "GrievanceCase")
    assert isinstance(data["filed_by_operator_id"], str)
    assert isinstance(data["sign_up_period_id"], str)
    assert data["category"] in [s.value for s in GrievanceCategory]
    assert isinstance(data["detail"], str)
    assert data["status"] in [s.value for s in GrievanceCaseStatus]
    assert isinstance(data["remedy_minutes"], int) and data["remedy_minutes"] >= 0
