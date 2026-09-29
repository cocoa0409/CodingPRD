"""Entity assertions and governance invariant checkers."""

from datetime import datetime, timezone
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    FROZEN_THRESHOLD,
    HIGH_CONFIDENCE_FLOOR,
    MEDIUM_CONFIDENCE_FLOOR,
    RESTRICTED_THRESHOLD,
)


def _assert_common(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_two_decimal_places(value: float, label: str = "value") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_domain(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["code"] in ["CUSTOMER", "PRODUCT", "VENDOR", "LOCATION"]
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ["DRAFT", "ACTIVE"]
    assert data["governance_posture"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert data["classification_level"] in [
        "PUBLIC",
        "INTERNAL",
        "CONFIDENTIAL",
        "RESTRICTED",
    ]
    assert isinstance(data["sensitive_handling_required"], bool)
    assert isinstance(data["notification_lead_days_floor"], int)
    assert isinstance(data["expected_attribute_count"], int)
    assert_two_decimal_places(data["open_finding_weight"], "open_finding_weight")
    assert isinstance(data["scorecard_run_seq"], int)
    assert isinstance(data["reference_data_revision"], int)
    assert isinstance(data["published_master_record_count"], int)
    assert isinstance(data["scheduled_change_count"], int)
    assert_domain_invariants(data)


def assert_domain_invariants(data: Dict[str, Any]) -> None:
    """Invariants that must hold on a domain after any operation."""
    assert data["open_finding_weight"] >= 0, "open_finding_weight is never negative"
    assert data["published_master_record_count"] >= 0
    assert data["scheduled_change_count"] >= 0
    assert data["reference_data_revision"] >= 0
    assert data["scorecard_run_seq"] >= 0
    expected_sensitive = data["classification_level"] in ["CONFIDENTIAL", "RESTRICTED"]
    assert data["sensitive_handling_required"] is expected_sensitive, (
        "sensitive_handling_required must be true exactly for CONFIDENTIAL and "
        f"RESTRICTED, got {data['sensitive_handling_required']} for "
        f"{data['classification_level']}"
    )
    if data["governance_posture"] == "OPEN":
        assert data["open_finding_weight"] < RESTRICTED_THRESHOLD, (
            "an OPEN posture requires an open finding weight below the "
            f"restricted threshold, got {data['open_finding_weight']}"
        )
    if data["open_finding_weight"] >= FROZEN_THRESHOLD:
        assert data["governance_posture"] == "FROZEN"


def assert_source_system(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["trust_tier"], int) and 1 <= data["trust_tier"] <= 5
    assert data["status"] in ["REGISTERED", "CERTIFIED", "DECERTIFIED"]


def assert_steward(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["certification_level"] in ["JUNIOR", "SENIOR", "PRINCIPAL"]
    assert isinstance(data["open_finding_load"], int) and data["open_finding_load"] >= 0


def assert_source_registration(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert is_valid_uuid(data["source_system_id"])
    assert data["role"] in ["AUTHORITATIVE", "CONTRIBUTING", "CONSUMING"]
    assert isinstance(data["trust_rank"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "REVOKED"]


def assert_steward_assignment(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert is_valid_uuid(data["steward_id"])
    assert data["steward_role"] in ["DATA_OWNER", "DATA_STEWARD", "CUSTODIAN"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_quality_rule(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert is_valid_uuid(data["owner_steward_id"])
    assert isinstance(data["rule_code"], str) and 1 <= len(data["rule_code"]) <= 20
    assert data["dimension"] in [
        "COMPLETENESS",
        "VALIDITY",
        "UNIQUENESS",
        "TIMELINESS",
        "CONSISTENCY",
    ]
    assert isinstance(data["weight_points"], int) and 1 <= data["weight_points"] <= 100
    assert_two_decimal_places(data["threshold_pct"], "threshold_pct")
    assert 0.00 <= data["threshold_pct"] <= 100.00
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_scorecard_run(data: Dict[str, Any]) -> None:
    """A scorecard run is immutable: only an id and a created_at accompany it."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an immutable scorecard run carries no updated_at"
    assert "version" not in data, "an immutable scorecard run carries no version"
    assert is_valid_uuid(data["domain_id"])
    assert isinstance(data["run_seq"], int) and data["run_seq"] >= 1
    assert data["basis"] in ["PROVISIONAL", "CERTIFIED"]
    assert is_iso8601_timestamp(data["measured_at"])
    assert_two_decimal_places(data["weighted_score"], "weighted_score")
    assert isinstance(data["rules_evaluated_count"], int)
    assert isinstance(data["rules_failed_count"], int)
    assert isinstance(data["findings_created_count"], int)
    assert data["posture_before"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert data["posture_after"] in ["OPEN", "RESTRICTED", "FROZEN"]
    assert_two_decimal_places(
        data["posture_multiplier_applied"], "posture_multiplier_applied"
    )
    assert data["rules_failed_count"] <= data["rules_evaluated_count"]
    assert data["findings_created_count"] <= data["rules_failed_count"]


def assert_quality_finding(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["scorecard_run_id"])
    assert is_valid_uuid(data["quality_rule_id"])
    assert data["status"] in ["OPEN", "REMEDIATION_PLANNED", "RESOLVED", "WAIVED"]
    assert_two_decimal_places(data["severity_weight"], "severity_weight")
    assert_two_decimal_places(data["measured_pct"], "measured_pct")
    assert_two_decimal_places(data["gap_pct"], "gap_pct")
    assert data["gap_pct"] >= 0, "gap_pct is never negative"
    assert is_iso8601_timestamp(data["opened_at"])


def assert_master_record(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert is_valid_uuid(data["source_system_id"])
    assert isinstance(data["natural_key"], str) and len(data["natural_key"]) > 0
    assert isinstance(data["attributes"], dict)
    assert_two_decimal_places(data["completeness_pct"], "completeness_pct")
    assert 0.00 <= data["completeness_pct"] <= 100.00
    assert is_iso8601_timestamp(data["last_verified_at"])
    assert data["curation_status"] in [
        "CANDIDATE",
        "CURATED",
        "MERGED_AWAY",
        "QUARANTINED",
    ]
    assert data["publication_status"] in ["UNPUBLISHED", "PUBLISHED", "RETRACTED"]
    assert_two_decimal_places(data["survivorship_score"], "survivorship_score")


def assert_merge_proposal(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert is_valid_uuid(data["survivor_master_record_id"])
    assert is_valid_uuid(data["duplicate_master_record_id"])
    assert_two_decimal_places(data["name_similarity_pct"], "name_similarity_pct")
    assert_two_decimal_places(data["key_overlap_pct"], "key_overlap_pct")
    assert_two_decimal_places(data["match_score"], "match_score")
    assert data["match_confidence"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in [
        "PROPOSED",
        "UNDER_REVIEW",
        "MERGED",
        "REJECTED",
        "REWORK",
    ]
    assert isinstance(data["survivor_swapped"], bool)
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert_match_confidence_consistent(data)


def assert_match_confidence_consistent(data: Dict[str, Any]) -> None:
    score = data["match_score"]
    if score >= HIGH_CONFIDENCE_FLOOR:
        expected = "HIGH"
    elif score >= MEDIUM_CONFIDENCE_FLOOR:
        expected = "MEDIUM"
    else:
        expected = "LOW"
    assert data["match_confidence"] == expected, (
        f"match_score {score} must yield confidence {expected}, got "
        f"{data['match_confidence']}"
    )


def assert_change_request(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert is_valid_uuid(data["requester_steward_id"])
    assert data["change_type"] in [
        "REFERENCE_VALUE_ADD",
        "HIERARCHY_RESTRUCTURE",
        "CLASSIFICATION_UPLIFT",
    ]
    assert isinstance(data["structural"], bool)
    expected_structural = data["change_type"] != "REFERENCE_VALUE_ADD"
    assert data["structural"] is expected_structural, (
        "structural must be true for every change type other than a reference "
        f"value addition, got {data['structural']} for {data['change_type']}"
    )
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["proposed_values"], dict)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "CHANGES_REQUESTED",
        "APPROVED",
        "REJECTED",
        "SCHEDULED",
        "APPLIED",
        "WITHDRAWN",
    ]
    assert isinstance(data["impact_consumer_count"], int)
    assert isinstance(data["required_lead_days"], int)
    assert isinstance(data["revision_cycle_count"], int)


def assert_consumer_subscription(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["domain_id"])
    assert isinstance(data["consumer_code"], str) and len(data["consumer_code"]) > 0
    assert isinstance(data["reporting_asset_key"], str)
    assert data["clearance_level"] in [
        "PUBLIC",
        "INTERNAL",
        "CONFIDENTIAL",
        "RESTRICTED",
    ]
    assert data["criticality"] in ["TIER1", "TIER2", "TIER3"]
    assert isinstance(data["required_lead_days"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["lineage_status"] in ["UNDOCUMENTED", "DOCUMENTED", "STALE"]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the trailing Z form and any
    number of fractional digits."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Assert a server-stamped instant names exactly the expected UTC moment."""
    assert actual is not None, f"{label} must be stamped, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} must be {expected}, got {actual}"
    )


def assert_freeze_window_released(data: Dict[str, Any]) -> None:
    assert data["freeze_window_start"] is None, (
        f"freeze_window_start must be null, got {data['freeze_window_start']!r}"
    )
    assert data["freeze_window_end"] is None, (
        f"freeze_window_end must be null, got {data['freeze_window_end']!r}"
    )
