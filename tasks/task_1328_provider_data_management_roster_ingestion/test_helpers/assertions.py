"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AttestationCampaignStatus,
    AttestationRequestStatus,
    AttributeConflictStatus,
    DistributionBatchStatus,
    DistributionTargetStatus,
    ProviderAttributeStatus,
    ProviderLifecycleStatus,
    RosterFileStatus,
    RosterSourceStatus,
)

SOURCE_FORMATS = ["CSV", "XLSX", "JSON", "FHIR", "FIXED_WIDTH"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Ledger records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_roster_source(data: dict):
    _assert_common(data)
    assert isinstance(data["source_code"], str) and data["source_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["format"] in SOURCE_FORMATS
    assert isinstance(data["precedence_rank"], int)
    assert isinstance(data["freshness_sla_days"], int) and data["freshness_sla_days"] >= 1
    assert data["status"] in [s.value for s in RosterSourceStatus]


def assert_roster_file(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["roster_source_id"])
    assert isinstance(data["external_file_ref"], str)
    assert isinstance(data["declared_row_count"], int) and data["declared_row_count"] >= 0
    assert data["status"] in [s.value for s in RosterFileStatus]


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["tin"], str) and data["tin"]
    assert isinstance(data["location_key"], str) and data["location_key"]
    assert data["lifecycle_status"] in [s.value for s in ProviderLifecycleStatus]
    assert isinstance(data["current_quality_score"], int)
    assert 0 <= data["current_quality_score"] <= 100
    assert isinstance(data["staleness_flag"], bool)


def assert_provider_attribute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert data["attribute_group"] in [
        "DEMOGRAPHIC",
        "SPECIALTY",
        "PRACTICE_ADDRESS",
        "CONTACT",
        "LICENSE",
    ]
    assert isinstance(data["attribute_key"], str) and data["attribute_key"]
    assert isinstance(data["attribute_value"], str)
    assert isinstance(data["effective_date"], str) and data["effective_date"]
    assert data.get("term_date") is None or isinstance(data["term_date"], str)
    assert data["status"] in [s.value for s in ProviderAttributeStatus]


def assert_attribute_conflict(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert data["status"] in [s.value for s in AttributeConflictStatus]
    assert data["resolution"] in [
        "PENDING",
        "KEEP_INCUMBENT",
        "ACCEPT_CHALLENGER",
        "MERGE_VALUES",
    ]


def assert_distribution_target(data: dict):
    _assert_common(data)
    assert data["target_code"] in ["CLAIMS", "DIRECTORY", "NETWORK"]
    assert isinstance(data["endpoint_uri"], str)
    assert isinstance(data["required_quality_floor"], int)
    assert 0 <= data["required_quality_floor"] <= 100
    assert data["status"] in [s.value for s in DistributionTargetStatus]


def assert_distribution_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["distribution_target_id"])
    assert data["status"] in [s.value for s in DistributionBatchStatus]
    assert isinstance(data.get("provider_count", 0), int)


def assert_distribution_item(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["distribution_batch_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["change_kind"] in ["ADD", "UPDATE", "TERM", "QUALITY_DROP_EXCLUDED"]
    assert isinstance(data["payload_hash"], str)


def assert_attestation_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["window_days"], int) and data["window_days"] >= 1
    assert data["status"] in [s.value for s in AttestationCampaignStatus]


def assert_attestation_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["attestation_campaign_id"])
    assert is_valid_uuid(data["provider_id"])
    assert data["status"] in [s.value for s in AttestationRequestStatus]


def assert_data_quality_score(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["provider_id"])
    for field in (
        "completeness_component",
        "freshness_component",
        "conflict_component",
        "attestation_component",
        "total_score",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert 0 <= data["completeness_component"] <= 40
    assert 0 <= data["freshness_component"] <= 30
    assert 0 <= data["conflict_component"] <= 20
    assert 0 <= data["attestation_component"] <= 10
    # "The total_score is the sum of the four components." (PRD §3.7)
    assert data["total_score"] == (
        data["completeness_component"]
        + data["freshness_component"]
        + data["conflict_component"]
        + data["attestation_component"]
    ), "total_score must equal the sum of the four components"


def assert_provider_merge_record(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["survivor_provider_id"])
    assert is_valid_uuid(data["merged_provider_id"])
    assert isinstance(data["decided_by_user_id"], str)
    assert isinstance(data["rationale"], str)


def active_intervals(attributes: list) -> list:
    """Filter an attribute listing to ACTIVE intervals."""
    return [a for a in attributes if a.get("status") == "ACTIVE"]


def assert_interval_set(attributes: list, expected: set):
    """Assert the ACTIVE intervals match {(effective_date, term_date, value)} exactly."""
    actual = {
        (a["effective_date"], a.get("term_date"), a["attribute_value"])
        for a in active_intervals(attributes)
    }
    assert actual == expected, f"ACTIVE interval set mismatch: expected {expected}, got {actual}"
