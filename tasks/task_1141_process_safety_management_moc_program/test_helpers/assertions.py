"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActionItemSource,
    ActionItemStatus,
    AuditFindingStatus,
    AuditStatus,
    ChangeClass,
    ExtensionStatus,
    FindingSeverity,
    IncidentStatus,
    MocStatus,
    PhaStudyStatus,
    Posture,
    Priority,
    ProcedureUpdateStatus,
    PssrStatus,
    RevalidationStatus,
    ReviewStatus,
    RiskRank,
    SeverityClass,
    TrainingAssignmentStatus,
    Verdict,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_enum(data: dict, field: str, enum_cls, entity: str):
    values = {e.value for e in enum_cls}
    assert data.get(field) in values, f"{entity}.{field} must be one of {sorted(values)}, got {data.get(field)!r}"


def assert_unit(data: dict):
    _assert_common_fields(data, "PlantUnit")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert isinstance(data["pha_cycle_months"], int)
    assert isinstance(data["open_action_count"], int) and data["open_action_count"] >= 0
    assert isinstance(data["overdue_action_count"], int) and data["overdue_action_count"] >= 0
    assert isinstance(data["process_safety_index"], (int, float))
    _assert_enum(data, "psm_posture", Posture, "PlantUnit")


def assert_personnel(data: dict):
    _assert_common_fields(data, "Personnel")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert isinstance(data["qualifications"], list)
    assert isinstance(data["active"], bool)


def assert_moc(data: dict):
    _assert_common_fields(data, "MocRequest")
    assert is_valid_uuid(data.get("unit_id", "")), "MocRequest.unit_id must be a UUID"
    _assert_enum(data, "status", MocStatus, "MocRequest")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    if data.get("change_class") is not None:
        _assert_enum(data, "change_class", ChangeClass, "MocRequest")
    if data.get("risk_rank") is not None:
        _assert_enum(data, "risk_rank", RiskRank, "MocRequest")


def assert_review(data: dict):
    _assert_common_fields(data, "TechnicalReview")
    _assert_enum(data, "status", ReviewStatus, "TechnicalReview")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    if data.get("verdict") is not None:
        _assert_enum(data, "verdict", Verdict, "TechnicalReview")


def assert_pha_study(data: dict):
    _assert_common_fields(data, "PhaStudy")
    _assert_enum(data, "status", PhaStudyStatus, "PhaStudy")
    assert isinstance(data["revalidation_count"], int) and data["revalidation_count"] >= 0


def assert_revalidation(data: dict):
    _assert_common_fields(data, "PhaRevalidation")
    _assert_enum(data, "status", RevalidationStatus, "PhaRevalidation")


def assert_pssr(data: dict):
    _assert_common_fields(data, "Pssr")
    _assert_enum(data, "status", PssrStatus, "Pssr")
    assert isinstance(data["punch_open_count"], int) and data["punch_open_count"] >= 0


def assert_action_item(data: dict):
    _assert_common_fields(data, "ActionItem")
    _assert_enum(data, "status", ActionItemStatus, "ActionItem")
    _assert_enum(data, "source_type", ActionItemSource, "ActionItem")
    _assert_enum(data, "priority", Priority, "ActionItem")
    assert isinstance(data["evidence_count"], int) and data["evidence_count"] >= 0
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_evidence_item(data: dict):
    """Append-only evidence: id + created_at, and neither updated_at nor version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "EvidenceItem.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "EvidenceItem.created_at must be ISO 8601"
    assert "updated_at" not in data, "EvidenceItem must not expose updated_at"
    assert "version" not in data, "EvidenceItem must not expose version"


def assert_incident(data: dict):
    _assert_common_fields(data, "IncidentInvestigation")
    _assert_enum(data, "status", IncidentStatus, "IncidentInvestigation")
    _assert_enum(data, "severity_class", SeverityClass, "IncidentInvestigation")
    assert isinstance(data["feeds_pha"], bool)


def assert_audit(data: dict):
    _assert_common_fields(data, "Audit")
    _assert_enum(data, "status", AuditStatus, "Audit")
    assert isinstance(data["open_finding_count"], int) and data["open_finding_count"] >= 0


def assert_audit_finding(data: dict):
    _assert_common_fields(data, "AuditFinding")
    _assert_enum(data, "status", AuditFindingStatus, "AuditFinding")
    _assert_enum(data, "severity", FindingSeverity, "AuditFinding")


def assert_procedure_update(data: dict):
    _assert_common_fields(data, "ProcedureUpdate")
    _assert_enum(data, "status", ProcedureUpdateStatus, "ProcedureUpdate")


def assert_training_assignment(data: dict):
    _assert_common_fields(data, "TrainingAssignment")
    _assert_enum(data, "status", TrainingAssignmentStatus, "TrainingAssignment")


def assert_extension_request(data: dict):
    _assert_common_fields(data, "ExtensionRequest")
    _assert_enum(data, "status", ExtensionStatus, "ExtensionRequest")
    assert isinstance(data["requested_days"], int) and data["requested_days"] >= 1


def assert_unit_index_invariants(data: dict):
    """Domain invariants on the unit safety index (PRD §2.10): 0..100 banded posture."""
    index = data["process_safety_index"]
    assert 0 <= index <= 100, f"index {index} out of 0..100"
    posture = data["psm_posture"]
    if index < 40:
        assert posture == "NORMAL", f"index {index} must be NORMAL, got {posture}"
    elif index < 70:
        assert posture == "RESTRICTED", f"index {index} must be RESTRICTED, got {posture}"
    else:
        assert posture == "FROZEN", f"index {index} must be FROZEN, got {posture}"
    assert data["overdue_action_count"] <= data["open_action_count"]
