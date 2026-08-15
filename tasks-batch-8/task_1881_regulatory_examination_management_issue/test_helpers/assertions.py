"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agency_code"], str) and 1 <= len(data["agency_code"]) <= 20
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert data["jurisdiction"] in ["FEDERAL", "STATE", "FOREIGN"]
    assert isinstance(data["escalation_threshold_days"], int)
    assert 1 <= data["escalation_threshold_days"] <= 730
    assert isinstance(data["repeat_finding_multiplier_bp"], int)
    assert 10000 <= data["repeat_finding_multiplier_bp"] <= 40000
    assert isinstance(data["active"], bool)


def assert_examination(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "SCHEDULED", "FIRST_DAY_ISSUED", "FIELDWORK", "FINDINGS_DELIVERED",
        "REMEDIATION", "VALIDATION", "CLOSED", "CANCELLED",
    ]
    assert data["posture"] in ["NORMAL", "RESTRICTED", "FROZEN"]
    assert isinstance(data["overdue_item_count"], int) and data["overdue_item_count"] >= 0
    assert isinstance(data["repeat_finding_risk_score_bp"], int)
    assert 0 <= data["repeat_finding_risk_score_bp"] <= 100000
    assert data["exam_type"] in ["SAFETY_SOUNDNESS", "COMPLIANCE", "IT", "TRUST", "SPECIALTY"]


def assert_first_day_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "SUBMITTED", "WAIVED"]
    assert isinstance(data["request_ref"], str) and data["request_ref"]
    assert isinstance(data["due_date"], str) and data["due_date"]


def assert_document_submission(data: dict):
    _assert_common_fields(data)
    assert data["quality_status"] in ["PENDING_REVIEW", "ACCEPTED", "REJECTED"]
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 1
    assert isinstance(data["page_count_total"], int) and data["page_count_total"] >= 0
    assert isinstance(data["document_manifest"], list) and len(data["document_manifest"]) >= 1


def assert_examiner_meeting(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert isinstance(data["attendees"], list)
    assert isinstance(data["minutes_summary"], str)


def assert_informal_finding(data: dict):
    _assert_common_fields(data)
    assert data["severity_hint"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert isinstance(data["finding_text"], str)


def assert_issue(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "OPEN", "REMEDIATION_PLANNED", "IN_PROGRESS", "VALIDATION_SUBMITTED",
        "CLOSED", "OVERDUE",
    ]
    assert data["classification"] in ["MRA", "MRIA"]
    assert data["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert isinstance(data["is_repeat_finding"], bool)
    assert isinstance(data["escalated_to_board"], bool)


def assert_remediation_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "ACTIVE", "COMPLETE", "REJECTED", "SUPERSEDED",
    ]
    assert isinstance(data["plan_version"], int) and data["plan_version"] >= 1
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]


def assert_remediation_milestone(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "IN_PROGRESS", "COMPLETE", "OVERDUE"]
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1


def assert_validation_evidence(data: dict):
    _assert_common_fields(data)
    assert data["review_status"] in ["PENDING", "SUFFICIENT", "INSUFFICIENT"]
    assert data["evidence_type"] in [
        "DOCUMENT_PACKAGE", "TEST_RESULTS", "INTERNAL_AUDIT_REPORT", "THIRD_PARTY_ATTESTATION",
    ]
    assert isinstance(data["artifact_manifest"], list)


def assert_closure_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]
    assert isinstance(data["request_round"], int) and data["request_round"] >= 1
    assert isinstance(data["validation_evidence_id"], str) and data["validation_evidence_id"]


def assert_board_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert isinstance(data["open_issue_count"], int) and data["open_issue_count"] >= 0
    assert isinstance(data["overdue_issue_count"], int) and data["overdue_issue_count"] >= 0
    assert isinstance(data["escalated_issue_count"], int) and data["escalated_issue_count"] >= 0
    assert isinstance(data["total_repeat_finding_risk_bp"], int)


def assert_commitment(data: dict):
    """CommitmentLogEntry is append-only (PRD §2.4): id + created_at only,
    no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only commitment must not carry version"
    assert "updated_at" not in data, "append-only commitment must not carry updated_at"
    assert isinstance(data["commitment_text"], str) and data["commitment_text"]
    assert "fulfilled_at" in data


def assert_bank_officer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["active"], bool)


def assert_compliance_reviewer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification_level"] in ["L1", "L2", "L3"]
    assert isinstance(data["active"], bool)
