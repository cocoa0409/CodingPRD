"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_timestamp_at(value, expected_prefix: str):
    """Pin a logical-clock-derived timestamp to an instant while tolerating
    the fractional-seconds rendering (PRD §2.4 mandates three fractional
    digits for created_at/updated_at; other clock stamps share the instant)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert value.startswith(expected_prefix), (
        f"expected timestamp at {expected_prefix}*, got {value!r}"
    )


def assert_carrier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dot_number"], str) and data["dot_number"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fleet_size"], int) and data["fleet_size"] >= 1
    assert data["safety_rating"] in ("NONE", "SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY")
    assert data["new_entrant_status"] in ("NOT_NEW_ENTRANT", "PENDING_AUDIT", "PASSED", "FAILED")
    assert data["posture"] in (
        "NORMAL", "INTERVENTION_WATCH", "INTERVENTION_PRIORITY", "OUT_OF_SERVICE_PROPOSED",
    )


def assert_driver(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert isinstance(data["cdl_number"], str) and data["cdl_number"]
    assert data["employment_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["risk_score"], int) and data["risk_score"] >= 0
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["coaching_strikes"], int) and data["coaching_strikes"] >= 0


def assert_category(data: dict):
    _assert_common_fields(data)
    assert data["category_code"] in (
        "UNSAFE_DRIVING", "HOURS_OF_SERVICE", "DRIVER_FITNESS",
        "CONTROLLED_SUBSTANCES_ALCOHOL", "VEHICLE_MAINTENANCE", "HAZMAT",
        "CRASH_INDICATOR",
    )
    assert 1 <= data["intervention_threshold"] <= 100
    assert data["benchmark_measure"] > 0


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert data["review_status"] in ("IMPORTED", "UNDER_REVIEW", "FINALIZED")
    assert isinstance(data["total_weighted_points"], int)
    assert data["total_weighted_points"] >= 0
    assert 1 <= data["inspection_level"] <= 3


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CHALLENGED", "REMOVED")
    assert 1 <= data["severity_weight"] <= 10
    assert data["time_weight_multiplier"] in (0, 1, 2, 3)
    assert data["weighted_points"] == (
        data["severity_weight"] * data["time_weight_multiplier"]
    )


def assert_challenge(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "REMANDED", "UPHELD", "OVERTURNED")
    assert isinstance(data["remand_count"], int) and 0 <= data["remand_count"] <= 2
    assert data["reason_code"] in (
        "INCORRECT_DATA", "WRONG_CARRIER", "WRONG_DRIVER", "DUPLICATE_REPORT", "OTHER",
    )


def assert_coaching(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "ASSIGNED", "IN_PROGRESS", "OVERDUE", "ESCALATED",
        "COMPLETED", "SUPERSEDED", "CANCELLED",
    )
    assert data["coaching_type"] in ("VERBAL_WARNING", "TRAINING_COURSE", "PROBATION")


def assert_drug_test(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("COLLECTED", "LAB_REPORTED", "MRO_VERIFIED", "CANCELLED")
    assert data["lab_result"] in (
        "PENDING", "NEGATIVE", "POSITIVE", "REFUSAL", "CANCELLED_BY_LAB",
    )
    assert data["mro_verdict"] in (
        "NONE", "VERIFIED_NEGATIVE", "VERIFIED_POSITIVE", "VERIFIED_REFUSAL", "CANCELLED",
    )
    assert data["test_type"] in (
        "PRE_EMPLOYMENT", "RANDOM", "POST_ACCIDENT",
        "REASONABLE_SUSPICION", "RETURN_TO_DUTY", "FOLLOW_UP",
    )
    assert data["substance"] in ("DRUG", "ALCOHOL")


def assert_accident(data: dict):
    _assert_common_fields(data)
    assert data["preventability_status"] in (
        "PENDING_REVIEW", "PREVENTABLE", "NOT_PREVENTABLE",
    )
    assert isinstance(data["dot_reportable"], bool)
    assert isinstance(data["crash_points"], int) and 0 <= data["crash_points"] <= 7


def assert_audit_case(data: dict):
    _assert_common_fields(data)
    assert data["audit_type"] in ("NEW_ENTRANT", "COMPLIANCE_REVIEW")
    assert data["status"] in (
        "SCHEDULED", "FIELD_WORK", "FINDINGS_ISSUED",
        "CORRECTIVE_ACTION_PHASE", "CLOSED_PASSED", "CLOSED_FAILED",
    )


def assert_upgrade_request(data: dict):
    _assert_common_fields(data)
    assert data["requested_rating"] in ("SATISFACTORY", "CONDITIONAL")
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_premium_model(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "QUOTED", "STALE", "BOUND")
    assert data["scenario"] in ("BASELINE", "PROJECTED")
    assert isinstance(data["computed_premium_cents"], int)
    assert data["computed_premium_cents"] >= 0
    assert isinstance(data["carrier_version_at_compute"], int)


def assert_document(data: dict):
    _assert_common_fields(data)
    assert data["document_type"] in (
        "INSPECTION_REPORT", "DQ_FILE", "DRUG_TEST_RECORD",
        "ALCOHOL_TEST_RECORD", "ACCIDENT_REGISTER_ENTRY", "TRAINING_CERTIFICATE",
    )
    assert data["status"] in ("RETAINED", "PURGE_ELIGIBLE", "PURGED")
    assert data["retention_months"] in (12, 36, 60)


def assert_period(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "CLOSED_COMPLIANT", "CLOSED_DEFICIENT")
    assert isinstance(data["required_drug_tests"], int)
    assert isinstance(data["required_alcohol_tests"], int)
    assert data["required_drug_tests"] >= 0 and data["required_alcohol_tests"] >= 0


def assert_snapshot(data: dict):
    """MeasurementSnapshot is append-only: id + created_at, but no
    updated_at and no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "snapshot must not carry updated_at"
    assert "version" not in data, "snapshot must not carry version"
    assert data["official_percentile"] >= 0 and data["provisional_percentile"] >= 0
    assert isinstance(data["alerted_official"], bool)
    assert isinstance(data["alerted_provisional"], bool)


def assert_risk_tier_for_score(score: int, tier: str):
    """PRD §3.2: LOW below 10, MEDIUM from 10 through 19, HIGH at 20 or above."""
    expected = "LOW" if score < 10 else ("MEDIUM" if score < 20 else "HIGH")
    assert tier == expected, f"risk_score {score} must map to {expected}, got {tier}"
