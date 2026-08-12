"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_ts(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected timestamp string, got {type(value)}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_ts_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two timestamps denote the same instant regardless of formatting."""
    assert parse_ts(actual) == parse_ts(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    """PRD §2.5: id UUID; created_at/updated_at ISO 8601; version integer."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"


def _assert_append_only_fields(data: dict):
    """PRD §2.5: immutable ledgers carry only id + created_at of the common set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only resource must not carry updated_at"
    assert "version" not in data, "append-only resource must not carry version"


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["owner_account_id"], str) and data["owner_account_id"]
    assert data["fund_program_election"] in ("PER_OCCURRENCE", "AGGREGATE")
    assert data["status"] in ("REGISTERED", "ACTIVE", "CLOSED")
    assert_facility_invariants(data)


def assert_facility_invariants(data: dict):
    """PRD §2.9: score 0..100 and the label follows the score bands."""
    score = data["posture_score"]
    assert isinstance(score, int), "posture_score must be an integer"
    assert 0 <= score <= 100, "posture_score is clamped to [0, 100]"
    label = data["compliance_posture"]
    if score >= 85:
        assert label == "COMPLIANT", f"score {score} must label COMPLIANT, got {label}"
    elif score >= 60:
        assert label == "DEFICIENT", f"score {score} must label DEFICIENT, got {label}"
    else:
        assert label == "NON_COMPLIANT", f"score {score} must label NON_COMPLIANT, got {label}"
    assert isinstance(data["fund_cap_remaining_cents"], int)
    assert isinstance(data["fund_year_deductible_remaining_cents"], int)


def assert_tank_system(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert isinstance(data["tank_tag"], str) and data["tank_tag"]
    assert data["substance"] in ("GASOLINE", "DIESEL", "KEROSENE", "USED_OIL")
    assert isinstance(data["capacity_gallons"], int)
    assert data["tank_construction"] in ("STEEL", "FRP", "COMPOSITE")
    assert data["piping_type"] in ("PRESSURIZED", "SUCTION", "GRAVITY")
    assert data["release_detection_mode"] in (
        "INTERSTITIAL_MONITORING", "ATG_INVENTORY", "MANUAL_GAUGING"
    )
    assert data["status"] in (
        "REGISTERED", "IN_SERVICE", "TEMPORARILY_CLOSED", "PERMANENTLY_CLOSED"
    )


def assert_component(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tank_system_id", "")), "tank_system_id must be a UUID"
    assert data["component_type"] in (
        "SPILL_BUCKET", "OVERFILL_DEVICE", "LINE_LEAK_DETECTOR", "CATHODIC_PROTECTION"
    )
    assert data["status"] in ("IN_SERVICE", "DEFICIENT", "OUT_OF_SERVICE")


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["endorsements"], list)
    for e in data["endorsements"]:
        assert e in ("TIGHTNESS_TESTER", "LLD_TESTER", "CP_TESTER", "INSPECTOR")
    assert isinstance(data["trainer"], bool)
    assert isinstance(data["active"], bool)


def assert_service_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert is_valid_uuid(data.get("tank_system_id", "")), "tank_system_id must be a UUID"
    assert data["service_type"] in (
        "TANK_TIGHTNESS", "LINE_TIGHTNESS", "LLD_FUNCTION", "CP_SURVEY",
        "SPILL_OVERFILL_INSPECTION",
    )
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "IN_PROGRESS", "UNDER_REVIEW", "CERTIFIED", "CANCELLED"
    )
    assert data["result_outcome"] in ("NONE", "PASS", "FAIL", "INCONCLUSIVE")
    assert isinstance(data["quote_total_cents"], int)


def assert_result_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("service_order_id", "")), "service_order_id must be a UUID"
    assert isinstance(data["readings"], dict)
    assert data["outcome"] in ("PASS", "FAIL", "INCONCLUSIVE")
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"


def assert_deficiency(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert is_valid_uuid(data.get("tank_system_id", "")), "tank_system_id must be a UUID"
    assert data["origin"] in ("TEST_FAILURE", "CLOSE_SWEEP")
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert data["status"] in (
        "OPEN", "CORRECTION_ORDERED", "CORRECTED", "RE_TEST_SCHEDULED",
        "ESCALATED", "VERIFIED_CLOSED",
    )
    assert is_iso8601_timestamp(data.get("correction_deadline", "")), (
        "correction_deadline must be ISO 8601"
    )


def assert_submission(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["submission_type"] in (
        "MONTHLY_RELEASE_DETECTION", "TEST_REPORT", "RELEASE_NOTIFICATION"
    )
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["is_late"], bool)


def assert_release_detection_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tank_system_id", "")), "tank_system_id must be a UUID"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["method"] in ("INTERSTITIAL_MONITORING", "ATG_INVENTORY", "MANUAL_GAUGING")
    assert data["status"] in ("RECORDED", "SUBMITTED", "ACCEPTED")


def assert_operator(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["operator_class"] in ("A", "B", "C")
    assert data["status"] in ("DESIGNATED", "ACTIVE", "LAPSED", "REVOKED")


def assert_training_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("operator_id", "")), "operator_id must be a UUID"
    assert data["course_class"] in ("A", "B", "C")
    assert is_iso8601_timestamp(data.get("completed_at", "")), "completed_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_release_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert is_iso8601_timestamp(data.get("discovered_at", "")), "discovered_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("report_deadline", "")), "report_deadline must be ISO 8601"
    assert data["status"] in (
        "SUSPECTED", "CONFIRMED", "CLEANUP_IN_PROGRESS", "CLOSED", "DISMISSED"
    )
    assert isinstance(data["late_notification"], bool)


def assert_fund_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert is_valid_uuid(data.get("release_event_id", "")), "release_event_id must be a UUID"
    assert isinstance(data["expense_lines"], list) and len(data["expense_lines"]) > 0
    for field in (
        "deductible_applied_cents", "eligible_amount_cents", "payable_amount_cents"
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DENIED", "WITHDRAWN"
    )
