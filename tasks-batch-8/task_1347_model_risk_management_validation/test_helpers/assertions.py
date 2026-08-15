"""Entity assertions and domain invariant checkers for the MRM API.

Timestamps are compared as instants (parsed), never as raw strings: the PRD pins
the instant each rule produces and specifies ISO 8601 UTC rendering with three
fractional digits, so instant comparison is the uniquely derivable assertion.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def parse_instant(value) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str) and value, f"expected ISO 8601 timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual, expected_iso: str, label: str = "timestamp"):
    """Assert two timestamps denote the same instant, regardless of whether the
    fractional-seconds component is rendered."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_dt.isoformat()}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Entity shape assertions
# ---------------------------------------------------------------------------

def _assert_common_mutable(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_model(data: dict):
    _assert_common_mutable(data, "Model")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["business_unit"], str) and data["business_unit"]
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert isinstance(data["is_vendor_model"], bool)
    assert data["declared_complexity"] in ("LOW", "MEDIUM", "HIGH")
    assert data.get("assessed_complexity") in (None, "LOW", "MEDIUM", "HIGH")
    assert data["usage_scope"] in ("SINGLE_DESK", "MULTI_DESK", "ENTERPRISE")
    assert isinstance(data["exposure_amount"], int) and data["exposure_amount"] >= 0
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert data["risk_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["status"] in ("REGISTERED", "APPROVED_FOR_USE", "SUSPENDED", "RETIRED")
    assert data["monitoring_posture"] in ("NORMAL", "BREACHED")
    assert isinstance(data["open_findings_count"], int) and data["open_findings_count"] >= 0


def assert_documentation(data: dict):
    _assert_common_mutable(data, "ModelDocumentation")
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert isinstance(data["version_label"], str)
    assert isinstance(data["has_development_evidence"], bool)
    assert isinstance(data["has_testing_evidence"], bool)
    assert isinstance(data["has_data_lineage"], bool)
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_change_request(data: dict):
    _assert_common_mutable(data, "ChangeRequest")
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert data["change_type"] in ("MINOR", "MAJOR")
    assert isinstance(data["description"], str)
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_engagement(data: dict):
    _assert_common_mutable(data, "ValidationEngagement")
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert isinstance(data["validator_user_id"], str) and data["validator_user_id"]
    assert isinstance(data["scope_conceptual_soundness"], bool)
    assert isinstance(data["scope_outcomes_analysis"], bool)
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert data["status"] in ("TESTING", "COMPLETED")
    assert data.get("outcome") in (None, "EFFECTIVE", "EFFECTIVE_WITH_FINDINGS", "INEFFECTIVE")


def assert_finding(data: dict):
    _assert_common_mutable(data, "Finding")
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert data["source"] in ("VALIDATION", "MONITORING")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["raised_by_user_id"], str) and data["raised_by_user_id"]
    assert data["status"] in ("OPEN", "OVERDUE", "ESCALATED", "CLOSED")
    assert is_iso8601_timestamp(data.get("remediation_due_at", "")), "remediation_due_at must be ISO 8601"


def assert_metric(data: dict):
    _assert_common_mutable(data, "MonitoringMetric")
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert isinstance(data["metric_name"], str) and data["metric_name"]
    assert data["direction"] in ("ABOVE_IS_BREACH", "BELOW_IS_BREACH")
    assert isinstance(data["threshold_value"], (int, float))
    assert data["status"] in ("ACTIVE", "PAUSED", "DECOMMISSIONED")
    assert isinstance(data["consecutive_breach_count"], int) and data["consecutive_breach_count"] >= 0


def assert_reading(data: dict):
    """Metric readings are the append-only exception: id + created_at only, with
    no updated_at and no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "MetricReading.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "MetricReading.created_at must be ISO 8601"
    assert "updated_at" not in data, "readings carry no updated_at (append-only)"
    assert "version" not in data, "readings carry no version (append-only)"
    assert is_valid_uuid(data.get("metric_id", "")), "metric_id must be a valid UUID"
    assert isinstance(data["value"], (int, float))
    assert is_iso8601_timestamp(data.get("observed_at", "")), "observed_at must be ISO 8601"
    assert isinstance(data["is_breach"], bool)


def assert_breach_event(data: dict):
    _assert_common_mutable(data, "BreachEvent")
    assert is_valid_uuid(data.get("metric_id", "")), "metric_id must be a valid UUID"
    assert isinstance(data["metric_name"], str) and data["metric_name"]
    assert is_valid_uuid(data.get("reading_id", "")), "reading_id must be a valid UUID"
    assert isinstance(data["breach_value"], (int, float))
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_vendor_assessment(data: dict):
    _assert_common_mutable(data, "VendorTransparencyAssessment")
    assert is_valid_uuid(data.get("model_id", "")), "model_id must be a valid UUID"
    assert isinstance(data["completeness_score"], int) and 0 <= data["completeness_score"] <= 100
    assert isinstance(data["valid_months"], int) and data["valid_months"] >= 1
    assert is_iso8601_timestamp(data.get("assessed_at", "")), "assessed_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be ISO 8601"
    assert data["status"] in ("CURRENT", "EXPIRED")


def assert_report(data: dict):
    _assert_common_mutable(data, "RegulatoryReport")
    assert data["report_type"] in ("BOARD_QUARTERLY", "REGULATOR_ANNUAL")
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert data["aggregation_method"] in ("EQUAL_WEIGHTED", "EXPOSURE_WEIGHTED")
    assert data["status"] in ("DRAFT", "SUBMITTED")
    for field in (
        "total_models",
        "tier_1_count",
        "open_findings_total",
        "open_critical_count",
        "breach_event_count",
        "overdue_validation_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"
    assert isinstance(data["inventory_risk_index"], (int, float))


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_model_invariants(data: dict):
    """Invariants that must hold for any model read."""
    score = data["risk_score"]
    tier = data["risk_tier"]
    assert 0 <= score <= 100, "risk_score is capped at 100"
    if score >= 70:
        assert tier == "TIER_1", f"score {score} must be TIER_1"
    elif score >= 40:
        assert tier == "TIER_2", f"score {score} must be TIER_2"
    else:
        assert tier == "TIER_3", f"score {score} must be TIER_3"
    assert data["open_findings_count"] >= 0
