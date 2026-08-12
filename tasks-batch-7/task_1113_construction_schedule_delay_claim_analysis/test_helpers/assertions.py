"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ProjectStatus,
    ScheduleVersionStatus,
    ScheduleVersionKind,
    RelationshipType,
    ProgressUpdateStatus,
    DelayEventStatus,
    Causation,
    FloatOwnershipPolicy,
    EotStatus,
    AccelerationDirectiveStatus,
    RecoveryVariant,
    LdaStatus,
)


def _assert_primary_common_fields(data: dict, label: str):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def _assert_light_common_fields(data: dict, label: str):
    """Activity relationships and progress entries carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{label} must not expose updated_at (PRD §2.5)"
    assert "version" not in data, f"{label} must not expose version (PRD §2.5)"


def assert_construction_project(data: dict):
    _assert_primary_common_fields(data, "ConstructionProject")
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert is_iso8601_timestamp(data["contract_start_date"])
    assert is_iso8601_timestamp(data["contract_completion_date"])
    assert isinstance(data["liquidated_damages_daily_rate_cents"], int)
    assert isinstance(data["ld_cap_cents"], int)
    assert data["float_ownership_policy"] in [e.value for e in FloatOwnershipPolicy]
    assert isinstance(data["notice_window_days"], int)
    assert data["status"] in [e.value for e in ProjectStatus]


def assert_schedule_version(data: dict):
    _assert_primary_common_fields(data, "ScheduleVersion")
    assert data["kind"] in [e.value for e in ScheduleVersionKind]
    assert is_iso8601_timestamp(data["data_date"])
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["status"] in [e.value for e in ScheduleVersionStatus]


def assert_activity(data: dict):
    _assert_primary_common_fields(data, "Activity")
    assert isinstance(data["activity_code"], str) and data["activity_code"]
    assert isinstance(data["description"], str)
    assert isinstance(data["original_duration_days"], int)
    assert data["original_duration_days"] >= 1, "original_duration_days must be at least one day"
    assert isinstance(data["remaining_duration_days"], int)
    assert 0 <= data["percent_complete"] <= 100, "percent_complete ranges 0..100 inclusive"


def assert_activity_relationship(data: dict):
    _assert_light_common_fields(data, "ActivityRelationship")
    assert is_valid_uuid(data["predecessor_activity_id"])
    assert is_valid_uuid(data["successor_activity_id"])
    assert data["relationship_type"] in [e.value for e in RelationshipType]
    assert isinstance(data["lag_days"], int)


def assert_progress_update(data: dict):
    _assert_primary_common_fields(data, "ProgressUpdate")
    assert is_iso8601_timestamp(data["reporting_period_end"])
    assert isinstance(data["submitted_by_contractor_user_id"], str)
    assert data["status"] in [e.value for e in ProgressUpdateStatus]


def assert_progress_entry(data: dict):
    _assert_light_common_fields(data, "ProgressEntry")
    assert is_valid_uuid(data["activity_id"])
    assert 0 <= data["percent_complete"] <= 100
    assert isinstance(data["remaining_duration_days"], int)


def assert_delay_event(data: dict):
    _assert_primary_common_fields(data, "DelayEvent")
    assert isinstance(data["title"], str) and data["title"]
    assert data["causation"] in [e.value for e in Causation]
    assert is_iso8601_timestamp(data["event_start_date"])
    assert data["status"] in [e.value for e in DelayEventStatus]


def assert_time_extension_request(data: dict):
    _assert_primary_common_fields(data, "TimeExtensionRequest")
    assert is_valid_uuid(data["delay_event_id"])
    assert isinstance(data["requested_days"], int) and data["requested_days"] >= 1
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 1
    assert data["status"] in [e.value for e in EotStatus]


def assert_acceleration_directive(data: dict):
    _assert_primary_common_fields(data, "AccelerationDirective")
    assert isinstance(data["directive_reference"], str) and data["directive_reference"]
    assert is_iso8601_timestamp(data["directed_completion_date"])
    assert data["status"] in [e.value for e in AccelerationDirectiveStatus]
    if data.get("recovery_variant") is not None:
        assert data["recovery_variant"] in [e.value for e in RecoveryVariant]


def assert_ld_assessment(data: dict):
    _assert_primary_common_fields(data, "LiquidatedDamagesAssessment")
    assert is_iso8601_timestamp(data["assessment_period_start"])
    assert is_iso8601_timestamp(data["assessment_period_end"])
    assert data["status"] in [e.value for e in LdaStatus]


def assert_project_invariants(data: dict):
    """Domain invariants that must hold after any project operation (PRD §2.8, §2.10)."""
    assert isinstance(data["liquidated_damages_daily_rate_cents"], int)
    assert isinstance(data["ld_cap_cents"], int)
    assert data["liquidated_damages_daily_rate_cents"] >= 0
    assert data["ld_cap_cents"] >= 0
    assert isinstance(data["notice_window_days"], int) and data["notice_window_days"] >= 0
