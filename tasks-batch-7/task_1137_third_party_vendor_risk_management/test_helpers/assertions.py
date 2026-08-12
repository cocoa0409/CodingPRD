"""Entity assertions and domain invariant checkers.

Each assert_* validates the shape a PRD reader can rely on: id is a UUID,
created_at is ISO 8601, status enums are in-range, and the common-field set
matches the entity class (full common fields vs append-only id+created_at).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AcknowledgementStatus,
    AssessmentStatus,
    AuditStatus,
    BCPTestStatus,
    BoardReportStatus,
    ContractStatus,
    CriticalityTier,
    DataAccessLevel,
    DataSensitivity,
    DDOutcome,
    DDPackageStatus,
    EngagementLifecycleStatus,
    GroupingDimension,
    HeadquartersRegion,
    IncidentStatus,
    IncidentType,
    MonitoringCycleStatus,
    RemediationPlanStatus,
    RiskAttentionState,
    ServiceCategory,
    Severity,
    TierPosture,
    VendorStatus,
)

_FULL_COMMON = ("id", "created_at", "updated_at", "version")


def _assert_uuid_and_created(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )


def _assert_full_common(data: dict, label: str):
    _assert_uuid_and_created(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_append_only(data: dict, label: str):
    """Append-only rows carry only id + created_at, never updated_at/version."""
    _assert_uuid_and_created(data, label)
    assert "updated_at" not in data, f"{label} must not expose updated_at"
    assert "version" not in data, f"{label} must not expose version"


def _assert_enum(data: dict, field: str, enum_cls, label: str):
    values = {e.value for e in enum_cls}
    assert data.get(field) in values, (
        f"{label}.{field} must be one of {sorted(values)}, got {data.get(field)!r}"
    )


# ---------------------------------------------------------------------------
# Full common-field entities
# ---------------------------------------------------------------------------

def assert_vendor(data: dict):
    _assert_full_common(data, "Vendor")
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    _assert_enum(data, "headquarters_region", HeadquartersRegion, "Vendor")
    _assert_enum(data, "service_category", ServiceCategory, "Vendor")
    _assert_enum(data, "criticality_tier", CriticalityTier, "Vendor")
    _assert_enum(data, "status", VendorStatus, "Vendor")
    _assert_enum(data, "tier_posture", TierPosture, "Vendor")
    assert isinstance(data.get("composite_risk_score"), (int, float))


def assert_vendor_engagement(data: dict):
    _assert_full_common(data, "VendorEngagement")
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert isinstance(data.get("engagement_code"), str) and len(data["engagement_code"]) > 0
    assert isinstance(data.get("annual_spend_cents"), int)
    _assert_enum(data, "data_sensitivity", DataSensitivity, "VendorEngagement")
    _assert_enum(data, "lifecycle_status", EngagementLifecycleStatus, "VendorEngagement")
    _assert_enum(data, "risk_attention_state", RiskAttentionState, "VendorEngagement")


def assert_dd_package(data: dict):
    _assert_full_common(data, "DueDiligencePackage")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    for f in ("financial_review_score", "security_review_score", "compliance_review_score"):
        assert isinstance(data.get(f), int) and 0 <= data[f] <= 100, (
            f"DueDiligencePackage.{f} must be an integer in 0..100"
        )
    _assert_enum(data, "status", DDPackageStatus, "DueDiligencePackage")
    _assert_enum(data, "dd_outcome", DDOutcome, "DueDiligencePackage")
    assert isinstance(data.get("review_round"), int) and data["review_round"] >= 1


def assert_contract(data: dict):
    _assert_full_common(data, "Contract")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    assert isinstance(data.get("contract_reference"), str) and len(data["contract_reference"]) > 0
    _assert_enum(data, "status", ContractStatus, "Contract")
    for f in ("has_right_to_audit_clause", "has_sla_terms", "has_exit_plan_section"):
        assert isinstance(data.get(f), bool), f"Contract.{f} must be boolean"


def assert_fourth_party(data: dict):
    _assert_full_common(data, "FourthParty")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    _assert_enum(data, "data_access_level", DataAccessLevel, "FourthParty")
    _assert_enum(data, "acknowledgement_status", AcknowledgementStatus, "FourthParty")


def assert_monitoring_cycle(data: dict):
    _assert_full_common(data, "MonitoringCycle")
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert isinstance(data.get("cycle_index"), int) and data["cycle_index"] >= 1
    assert isinstance(data.get("cadence_days"), int) and data["cadence_days"] >= 1
    _assert_enum(data, "status", MonitoringCycleStatus, "MonitoringCycle")


def assert_incident(data: dict):
    _assert_full_common(data, "Incident")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    _assert_enum(data, "incident_type", IncidentType, "Incident")
    _assert_enum(data, "severity", Severity, "Incident")
    _assert_enum(data, "status", IncidentStatus, "Incident")
    assert isinstance(data.get("reopen_count"), int) and data["reopen_count"] >= 0


def assert_remediation_plan(data: dict):
    _assert_full_common(data, "RemediationPlan")
    assert is_valid_uuid(data.get("incident_id", "")), "incident_id must be a UUID"
    assert isinstance(data.get("plan_summary"), str) and len(data["plan_summary"]) > 0
    _assert_enum(data, "status", RemediationPlanStatus, "RemediationPlan")


def assert_concentration_assessment(data: dict):
    _assert_full_common(data, "ConcentrationAssessment")
    _assert_enum(data, "grouping_dimension", GroupingDimension, "ConcentrationAssessment")
    _assert_enum(data, "status", AssessmentStatus, "ConcentrationAssessment")


def assert_bcp_test(data: dict):
    _assert_full_common(data, "BusinessContinuityTest")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    assert isinstance(data.get("rto_target_minutes"), int) and data["rto_target_minutes"] >= 1
    assert isinstance(data.get("rpo_target_minutes"), int) and data["rpo_target_minutes"] >= 0
    _assert_enum(data, "status", BCPTestStatus, "BusinessContinuityTest")


def assert_audit_exercise(data: dict):
    _assert_full_common(data, "AuditExercise")
    assert is_valid_uuid(data.get("engagement_id", "")), "engagement_id must be a UUID"
    _assert_enum(data, "status", AuditStatus, "AuditExercise")
    assert isinstance(data.get("findings_count"), int) and data["findings_count"] >= 0


def assert_board_report(data: dict):
    _assert_full_common(data, "BoardReport")
    _assert_enum(data, "status", BoardReportStatus, "BoardReport")


# ---------------------------------------------------------------------------
# Append-only entities (id + created_at only)
# ---------------------------------------------------------------------------

def assert_concentration_bucket(data: dict):
    _assert_append_only(data, "ConcentrationBucket")
    assert isinstance(data.get("bucket_key"), str) and len(data["bucket_key"]) > 0
    assert isinstance(data.get("total_spend_cents"), int)
    assert isinstance(data.get("share_pct"), (int, float))
    assert isinstance(data.get("is_breach"), bool)


def assert_audit_finding(data: dict):
    _assert_append_only(data, "AuditFinding")
    _assert_enum(data, "severity", Severity, "AuditFinding")
    assert isinstance(data.get("description"), str)


def assert_risk_tier_change_log(data: dict):
    _assert_append_only(data, "RiskTierChangeLog")
    _assert_enum(data, "from_tier", CriticalityTier, "RiskTierChangeLog")
    _assert_enum(data, "to_tier", CriticalityTier, "RiskTierChangeLog")
    assert isinstance(data.get("reason"), str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_vendor_risk_invariants(data: dict):
    """Vendor numeric invariants that must hold after any operation."""
    score = data.get("composite_risk_score")
    assert isinstance(score, (int, float)), "composite_risk_score must be numeric"
    assert 0 <= score <= 100, f"composite_risk_score {score} out of [0, 100]"
    posture = data.get("tier_posture")
    # Posture must agree with the score thresholds (70/40/15).
    if score >= 70:
        assert posture == TierPosture.BREACH.value, (
            f"score {score} >= 70 requires BREACH, got {posture}"
        )
    elif score >= 40:
        assert posture == TierPosture.ESCALATED.value, (
            f"score {score} >= 40 requires ESCALATED, got {posture}"
        )
    elif score >= 15:
        assert posture == TierPosture.WATCH.value, (
            f"score {score} >= 15 requires WATCH, got {posture}"
        )
    else:
        assert posture == TierPosture.CLEAN.value, (
            f"score {score} < 15 requires CLEAN, got {posture}"
        )
