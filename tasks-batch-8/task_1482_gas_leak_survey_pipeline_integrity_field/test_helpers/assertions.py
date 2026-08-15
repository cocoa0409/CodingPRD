"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional seconds)."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"Not a valid ISO 8601 timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_timestamp_eq(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two timestamps denote the same instant (second precision)."""
    actual_dt = parse_ts(actual)
    expected_dt = parse_ts(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_pipe_segment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_code"], str) and data["segment_code"]
    assert isinstance(data["install_year"], int)
    assert data["material"] in ["STEEL", "CAST_IRON", "PLASTIC_PE", "PLASTIC_PVC", "COPPER"]
    assert data["pressure_class"] in ["DISTRIBUTION", "TRANSMISSION", "SERVICE"]
    assert isinstance(data["is_high_consequence_area"], bool)
    assert data["status"] in ["ACTIVE", "OUT_OF_SERVICE", "ABANDONED"]
    assert data["posture"] in ["NORMAL", "ELEVATED", "CRITICAL"]
    for counter in ("open_grade1_count", "open_grade2_count", "open_grade3_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_instrument(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["instrument_type"] in [
        "FLAME_IONIZATION", "CGI", "OMD", "AERIAL_LIDAR", "CP_VOLTMETER",
    ]
    assert data["status"] in ["IN_SERVICE", "OUT_OF_CALIBRATION", "RETIRED"]


def assert_calibration(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["instrument_id"], str)
    assert isinstance(data["reference_gas_ppm"], (int, float))
    assert isinstance(data["observed_ppm"], (int, float))
    assert isinstance(data["drift_pct"], (int, float))
    assert data["outcome"] in ["PASS", "FAIL"]


def assert_survey_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert data["survey_method"] in ["WALKING", "MOBILE", "AERIAL", "PATROL"]
    assert data["status"] in ["PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "ABORTED"]


def assert_survey_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["instrument_id"], str)
    assert isinstance(data["technician_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_leak(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_id"], str)
    assert isinstance(data["survey_run_id"], str)
    assert data["grade"] in ["G1", "G2", "G3"]
    assert data["status"] in [
        "OPEN", "REPAIR_SCHEDULED", "UNDER_REPAIR",
        "REPAIRED_PENDING_VERIFICATION", "VERIFIED_CLEARED", "ABANDONED_SEGMENT",
    ]
    assert isinstance(data["regrade_count"], int) and data["regrade_count"] >= 0


def assert_repair_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["leak_id"], str)
    assert data["priority"] in ["P1_EMERGENCY", "P2_URGENT", "P3_ROUTINE"]
    assert data["dispatch_status"] in [
        "PENDING_DISPATCH", "DISPATCHED", "ON_SITE", "WORK_COMPLETE", "CANCELLED",
    ]
    assert data["excavation_permit_status"] in [
        "NOT_REQUIRED", "PERMIT_REQUIRED", "PERMIT_APPLIED",
        "PERMIT_GRANTED", "PERMIT_DENIED", "PERMIT_EXPIRED",
    ]


def assert_excavation_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["repair_order_id"], str)
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert data["status"] in ["APPLIED", "GRANTED", "DENIED", "EXPIRED"]


def assert_repair_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["open_order_count"], int) and data["open_order_count"] >= 0
    assert isinstance(data["max_concurrent_orders"], int)
    assert data["status"] in ["AVAILABLE", "AT_CAPACITY", "OFF_DUTY"]


def assert_cp_reading(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["segment_id"], str)
    assert isinstance(data["is_anomalous"], bool)
    assert data["anomaly_status"] in ["NONE", "OPEN", "ACKNOWLEDGED", "RESOLVED"]


def assert_risk_model_snapshot(data: dict):
    _assert_common_fields(data)
    assert data["snapshot_kind"] in ["LEAK_SECTION", "CP_SECTION", "FULL"]
    assert data["status"] in ["STALE", "CURRENT", "PINNED"]


def assert_compliance_report(data: dict):
    _assert_common_fields(data)
    assert data["regulator"] in ["PHMSA", "STATE_PUC", "LOCAL_FIRE_MARSHAL"]
    assert data["status"] in [
        "DRAFT", "PENDING_REVIEW", "SUBMITTED", "ACCEPTED",
        "REJECTED_BY_REGULATOR", "RESUBMISSION_REQUIRED",
    ]


def assert_regrade_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["leak_id"], str)
    assert data["previous_grade"] in ["G1", "G2", "G3"]
    assert data["new_grade"] in ["G1", "G2", "G3"]
    assert isinstance(data["performed_by_user_id"], str)


def assert_risk_score(value: float):
    """risk_score is on a 0-100 scale rounded to 2 decimal places (PRD §3.8)."""
    assert isinstance(value, (int, float)), f"risk_score must be numeric, got {value!r}"
    assert 0.0 <= value <= 100.0, f"risk_score {value} out of [0, 100]"
    assert round(value, 2) == pytest.approx(value), (
        f"risk_score {value} has more than 2 decimal places"
    )
