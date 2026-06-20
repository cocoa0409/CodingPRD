"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "program id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("current_date", "")), "current_date must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_jurisdiction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "jurisdiction id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fips_code"], str)
    assert isinstance(data["active_monitoring_count"], int)
    assert data["active_monitoring_count"] >= 0, "active_monitoring_count must be non-negative"


def assert_condition(data: dict):
    assert is_valid_uuid(data.get("id", "")), "condition id must be a valid UUID"
    assert isinstance(data["condition_code"], str) and len(data["condition_code"]) > 0
    assert isinstance(data["display_name"], str)
    for day_field in (
        "presymptomatic_days", "infectious_tail_days", "quarantine_days",
        "test_based_release_days", "isolation_min_days", "fever_free_days",
    ):
        assert isinstance(data[day_field], int) and data[day_field] >= 0, (
            f"{day_field} must be a non-negative integer"
        )


def assert_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "case id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["patient_reference"], str)
    assert data["status"] in [
        "OPEN", "UNDER_INVESTIGATION", "CLASSIFIED", "CLOSED", "REOPENED", "TRANSFER_PENDING",
    ], f"unexpected case status {data['status']}"
    assert data["classification"] in [
        "SUSPECT", "PROBABLE", "CONFIRMED", "NOT_A_CASE",
    ], f"unexpected classification {data['classification']}"
    assert isinstance(data["interview_completed"], bool)
    assert isinstance(data["completeness_score"], int)
    assert 0 <= data["completeness_score"] <= 100, "completeness_score must be in [0,100]"
    assert isinstance(data["contact_count"], int) and data["contact_count"] >= 0
    assert isinstance(data["linked_positive_count"], int) and data["linked_positive_count"] >= 0
    assert isinstance(data.get("version"), int)


def assert_lab_result(data: dict):
    assert is_valid_uuid(data.get("id", "")), "lab result id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["result_value"] in ["POSITIVE", "NEGATIVE", "INDETERMINATE"]
    assert data["status"] in ["RECEIVED", "LINKED", "UNLINKED", "SUPERSEDED"]


def assert_contact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "contact id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["exposure_setting"] in [
        "HOUSEHOLD", "HEALTHCARE", "WORKPLACE", "SOCIAL", "COMMUNITY",
    ]
    assert data["status"] in [
        "ELICITED", "NOTIFICATION_PENDING", "NOTIFIED", "NOTIFICATION_FAILED",
        "MONITORING_ACTIVE", "MONITORING_COMPLETE", "PROMOTED_TO_CASE", "VOIDED",
    ], f"unexpected contact status {data['status']}"
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= 100, "priority_score must be in [0,100]"
    assert data["priority_band"] in ["HIGH", "MEDIUM", "LOW"]
    assert data["quarantine_release_basis"] in ["STANDARD", "TEST_BASED"]
    assert isinstance(data["notification_attempts"], int) and data["notification_attempts"] >= 0


def assert_exposure_event(data: dict):
    """Append-only record: id + created_at only — no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "exposure event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ExposureEvent is append-only and must carry no version"
    assert "updated_at" not in data, "ExposureEvent is append-only and must carry no updated_at"


def assert_monitoring_period(data: dict):
    assert is_valid_uuid(data.get("id", "")), "monitoring period id must be a valid UUID"
    assert data["monitoring_type"] in ["QUARANTINE", "ISOLATION"]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "RELEASED_EARLY"]


def assert_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "transfer id must be a valid UUID"
    assert data["status"] in ["REQUESTED", "ACCEPTED", "REJECTED"]


def assert_cluster(data: dict):
    assert is_valid_uuid(data.get("id", "")), "cluster id must be a valid UUID"
    assert data["status"] in ["ACTIVE", "CLOSED"]
    assert isinstance(data["member_case_count"], int) and data["member_case_count"] >= 0


def assert_export(data: dict):
    assert is_valid_uuid(data.get("id", "")), "export id must be a valid UUID"
    assert data["status"] in ["GENERATED", "TRANSMITTED", "VOIDED"]
    assert data["snapshot_classification"] in ["CONFIRMED", "PROBABLE"]
