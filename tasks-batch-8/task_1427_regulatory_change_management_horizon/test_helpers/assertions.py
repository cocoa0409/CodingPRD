"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(ts, str), f"Expected ISO timestamp string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_common_fields(data: dict):
    """Fields every primary resource carries (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_business_owner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["department"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["active_assessment_count"], int)
    assert isinstance(data["open_escalation_count"], int)
    assert isinstance(data["assignment_suspended"], bool)


def assert_regulatory_change(data: dict):
    assert_common_fields(data)
    assert isinstance(data["citation"], str) and data["citation"]
    assert data["feed_source"] in ["FED_REGISTER", "STATE_BULLETIN", "INT_JOURNAL", "MANUAL_ENTRY"]
    assert data["severity_hint"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in [
        "PENDING_TRIAGE", "TRIAGED_APPLICABLE", "TRIAGED_NOT_APPLICABLE", "CLOSED", "SUPERSEDED",
    ]
    assert data["applicability"] in ["UNDETERMINED", "APPLICABLE", "NOT_APPLICABLE"]
    assert isinstance(data["triage_round"], int)


def assert_obligation(data: dict):
    assert_common_fields(data)
    assert isinstance(data["obligation_code"], str) and data["obligation_code"]
    assert data["criticality"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_control(data: dict):
    assert_common_fields(data)
    assert isinstance(data["control_code"], str) and data["control_code"]
    assert isinstance(data["review_frequency_days"], int) and data["review_frequency_days"] > 0
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["policy_version"], int)
    assert isinstance(data["effectiveness_factor"], (int, float))


def assert_mapping(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("obligation_id", ""))
    assert is_valid_uuid(data.get("control_id", ""))
    assert isinstance(data["coverage_weight"], int)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "RETIRED"]


def assert_register(data: dict):
    assert_common_fields(data)
    assert isinstance(data["current_version_number"], int)
    assert data["singleton_note"] == "SINGLETON"


def assert_register_version(data: dict):
    # Append-only snapshot: updated_at and version are absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "ObligationRegisterVersion must not carry updated_at"
    assert "version" not in data, "ObligationRegisterVersion must not carry version"
    assert isinstance(data["version_number"], int)
    assert is_iso8601_timestamp(data.get("published_at", ""))
    assert isinstance(data["obligation_codes"], list)
    assert isinstance(data["obligation_count"], int)
    assert isinstance(data["register_checksum"], str) and len(data["register_checksum"]) == 64


def assert_impact_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("regulatory_change_id", ""))
    assert is_valid_uuid(data.get("business_owner_id", ""))
    assert data["status"] in [
        "ASSIGNED", "IN_PROGRESS", "SUBMITTED", "RETURNED", "ACCEPTED", "SUPERSEDED",
    ]
    assert isinstance(data["return_count"], int)
    assert isinstance(data["sla_breached"], bool)


def assert_gap_analysis(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("impact_assessment_id", ""))
    assert is_valid_uuid(data.get("obligation_id", ""))
    assert isinstance(data["requirement_points"], int)
    assert isinstance(data["covered_points"], (int, float))
    assert isinstance(data["residual_gap_points"], (int, float))
    assert data["status"] in ["OPEN", "IN_REVIEW", "CONFIRMED"]


def assert_implementation_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("gap_analysis_id", ""))
    assert data["execution_status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "IN_EXECUTION", "COMPLETED", "VERIFIED",
    ]
    assert data["deadline_posture"] in ["ON_TRACK", "AT_RISK", "OVERDUE"]
    assert isinstance(data["extension_count"], int)


def assert_policy_update(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("control_id", ""))
    assert data["status"] in [
        "DRAFTING", "PENDING_APPROVAL", "APPROVED", "REJECTED", "PUBLISHED", "RETRACTED",
    ]


def assert_training_rollout(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("policy_update_id", ""))
    assert isinstance(data["assigned_count"], int)
    assert isinstance(data["completed_count"], int)
    assert isinstance(data["completion_pct"], (int, float))
    assert isinstance(data["past_due"], bool)
    assert data["status"] in ["IN_PROGRESS", "COMPLETED", "CLOSED_WITH_EXCEPTIONS", "CANCELLED"]


def assert_evidence_package(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("implementation_plan_id", ""))
    assert isinstance(data["artifacts"], list)
    assert isinstance(data["artifact_count"], int)
    assert data["artifact_count"] == len(data["artifacts"])
    assert data["status"] in ["ASSEMBLING", "SEALED", "SUBMITTED_TO_EXAMINER"]


def assert_escalation(data: dict):
    assert_common_fields(data)
    assert data["target_type"] in ["IMPLEMENTATION_PLAN", "OBLIGATION"]
    assert data["trigger_rule"] in ["DEADLINE_BREACH", "ZERO_COVERAGE"]
    assert isinstance(data["level"], int)
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "RESOLVED"]


def assert_committee_report(data: dict):
    assert_common_fields(data)
    assert data["committee_name"] in [
        "BOARD_RISK_COMMITTEE", "AUDIT_COMMITTEE", "EXECUTIVE_COMPLIANCE_COMMITTEE",
    ]
    assert data["status"] in ["DRAFT", "FINALIZED", "PRESENTED"]


def assert_audit_event(data: dict):
    # Append-only: no updated_at / version (PRD §2.5).
    assert is_valid_uuid(data.get("id", ""))
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)
    assert isinstance(data["prev_event_hash"], str)
    assert isinstance(data["event_hash"], str) and len(data["event_hash"]) == 64
