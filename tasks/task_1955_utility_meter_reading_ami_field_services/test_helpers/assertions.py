"""Entity assertions and domain invariant checkers.

Each assert_* validates the structural contract of one resource type:
common quartet shape (PRD section 2.5) plus enum membership and field
types named in the PRD narratives.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AccountStatus,
    CampaignStatus,
    EndpointCommsStatus,
    EnrollmentStatus,
    EstimationMethod,
    FlagStatus,
    HazardType,
    IndicationType,
    InvestigationStatus,
    MeterStatus,
    MeterType,
    PeriodStatus,
    ReadSource,
    ReadStatus,
    RouteShift,
    RouteStatus,
    Severity,
    SnapshotStatus,
    StopStatus,
    TamperStatus,
    TechnicianStatus,
    WorkOrderStatus,
    WorkOrderType,
)


def _assert_common(data: dict):
    """Common resource quartet per PRD section 2.5."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_optional_ts(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def assert_iso_instant_equal(actual: str, expected_iso: str):
    """Assert an ISO 8601 timestamp string denotes exactly the expected instant.

    Compares parsed instants (UTC) so serialization-detail differences such as
    a trailing 'Z' versus '+00:00' do not matter; the instant itself is pinned.
    """
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 UTC timestamp: {actual!r}"
    actual_dt = datetime.fromisoformat(actual.replace("Z", "+00:00")).astimezone(timezone.utc)
    expected_dt = datetime.fromisoformat(expected_iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert actual_dt == expected_dt, (
        f"expected instant {expected_dt.isoformat()}, got {actual_dt.isoformat()}"
    )


def assert_field_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["technician_status"] in [s.value for s in TechnicianStatus]


def assert_service_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["service_address"], str)
    assert isinstance(data["billing_cycle_code"], str)
    assert data["estimation_method"] in [s.value for s in EstimationMethod]
    assert data["account_status"] in [s.value for s in AccountStatus]
    assert data.get("current_meter_id") is None or is_valid_uuid(data["current_meter_id"])
    assert data.get("last_validated_read_value") is None or isinstance(
        data["last_validated_read_value"], int
    )
    _assert_optional_ts(data, "last_validated_read_at")
    assert isinstance(data["estimated_read_streak"], int) and data["estimated_read_streak"] >= 0


def assert_meter(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["meter_type"] in [s.value for s in MeterType]
    assert data["meter_status"] in [s.value for s in MeterStatus]
    assert data["endpoint_comms_status"] in [s.value for s in EndpointCommsStatus]
    assert data["tamper_status"] in [s.value for s in TamperStatus]
    assert data.get("installed_service_account_id") is None or is_valid_uuid(
        data["installed_service_account_id"]
    )
    assert isinstance(data["consecutive_missed_days"], int)
    _assert_optional_ts(data, "non_communicating_since")


def assert_billing_cycle_period(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_code"], str) and data["cycle_code"]
    for field in (
        "period_start_date",
        "period_end_date",
        "read_window_open_date",
        "read_window_close_date",
        "bill_run_date",
    ):
        assert isinstance(data[field], str) and len(data[field]) == 10, (
            f"{field} must be a YYYY-MM-DD date, got {data[field]!r}"
        )
    assert data["period_status"] in [s.value for s in PeriodStatus]
    assert isinstance(data["unresolved_stop_count"], int) and data["unresolved_stop_count"] >= 0


def assert_route(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["billing_cycle_period_id"])
    assert isinstance(data["scheduled_date"], str) and len(data["scheduled_date"]) == 10
    assert data["route_shift"] in [s.value for s in RouteShift]
    assert isinstance(data["two_person_crew"], bool)
    assert data.get("technician_id") is None or isinstance(data["technician_id"], str)
    assert data["route_status"] in [s.value for s in RouteStatus]
    assert isinstance(data["stops_total"], int) and data["stops_total"] >= 0
    assert isinstance(data["captured_stop_count"], int) and data["captured_stop_count"] >= 0


def assert_route_stop(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["service_account_id"])
    assert is_valid_uuid(data["billing_cycle_period_id"])
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert data["stop_status"] in [s.value for s in StopStatus]


def assert_meter_read(data: dict):
    _assert_common(data)
    assert data.get("route_stop_id") is None or is_valid_uuid(data["route_stop_id"])
    assert is_valid_uuid(data["service_account_id"])
    assert is_valid_uuid(data["meter_id"])
    assert isinstance(data["read_value"], int) and data["read_value"] >= 0
    assert is_iso8601_timestamp(data["read_at"])
    assert data["read_source"] in [s.value for s in ReadSource]
    assert data["read_status"] in [s.value for s in ReadStatus]
    assert isinstance(data["tamper_indication"], bool)
    assert isinstance(data["is_billable"], bool)


def assert_hazard_flag(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_account_id"])
    assert data["hazard_type"] in [s.value for s in HazardType]
    assert data["severity"] in [s.value for s in Severity]
    assert data["flag_status"] in [s.value for s in FlagStatus]
    assert isinstance(data["reported_by_technician_id"], str)
    assert is_iso8601_timestamp(data["reported_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["renewed_count"], int) and data["renewed_count"] >= 0


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["work_order_type"] in [s.value for s in WorkOrderType]
    assert is_valid_uuid(data["service_account_id"])
    assert isinstance(data["scheduled_date"], str) and len(data["scheduled_date"]) == 10
    assert data["work_shift"] in [s.value for s in RouteShift]
    assert data["work_order_status"] in [s.value for s in WorkOrderStatus]
    _assert_optional_ts(data, "completed_at")


def assert_investigation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_account_id"])
    assert is_valid_uuid(data["meter_id"])
    assert data["indication_type"] in [s.value for s in IndicationType]
    assert data["investigation_status"] in [s.value for s in InvestigationStatus]
    assert isinstance(data["opened_by_user_id"], str)
    assert isinstance(data["evidence_notes"], list)


def assert_replacement_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_name"], str) and data["campaign_name"]
    assert isinstance(data["quota"], int) and data["quota"] >= 1
    assert data["campaign_status"] in [s.value for s in CampaignStatus]
    for field in ("enrolled_count", "replaced_count", "withdrawn_count"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_campaign_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["campaign_id"])
    assert is_valid_uuid(data["meter_id"])
    assert data["enrollment_status"] in [s.value for s in EnrollmentStatus]


def assert_ops_snapshot(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["snapshot_at"])
    assert data["snapshot_status"] in [s.value for s in SnapshotStatus]
    for field in (
        "eligible_stop_count",
        "covered_stop_count",
        "backlog_count",
        "backlog_aged_7plus_count",
        "estimated_read_count",
        "validated_read_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data[field]!r}"
        )


def assert_campaign_count_invariants(campaign: dict):
    """Campaign counters partition its enrollments by terminal/non-terminal state."""
    assert campaign["enrolled_count"] >= 0
    assert campaign["replaced_count"] >= 0
    assert campaign["withdrawn_count"] >= 0
    assert campaign["enrolled_count"] <= campaign["quota"], (
        "enrolled_count must never exceed the campaign quota"
    )


def assert_route_counter_invariants(route: dict):
    """Route counters: captured stops can never exceed the non-cancelled total."""
    assert route["stops_total"] >= 0
    assert 0 <= route["captured_stop_count"] <= max(route["stops_total"], 0)
