"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "INTAKE", "TRIAGED", "PLANNING", "FIELDWORK", "FINDINGS",
        "DISPOSITION", "REMEDIATION", "CLOSED", "DISMISSED",
    ]
    assert isinstance(data["case_number"], str) and data["case_number"].startswith("INV-")
    assert isinstance(data["pattern_escalated"], bool)
    assert isinstance(data["case_priority_score"], int)
    assert data["priority_tier"] in ["ROUTINE", "ELEVATED", "URGENT"]
    assert isinstance(data["active_privileged_artifact_count"], int)
    assert isinstance(data["open_remediation_count"], int)


def assert_allegation(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "TRIAGED", "LINKED", "DISMISSED"]
    assert data["reporter_channel"] in [
        "HOTLINE", "EMAIL", "MANAGER_REFERRAL", "ANONYMOUS_PORTAL", "EXTERNAL"
    ]
    assert isinstance(data["is_anonymous"], bool)


def assert_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
    assert isinstance(data["plan_version"], int) and data["plan_version"] >= 1


def assert_subject(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "CLEARED", "SEPARATED"]
    assert data["role_in_case"] in ["PRIMARY", "ACCESSORY", "PERSON_OF_INTEREST"]


def assert_notice(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "ACKNOWLEDGED", "RELEASED"]
    assert data["scope"] in ["EMAIL", "DEVICES", "CHAT", "FILES", "ALL_DATA"]
    assert isinstance(data["is_regulator_ordered"], bool)


def assert_scope(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "APPROVED", "IN_PROGRESS", "COLLECTED", "WITHDRAWN"]
    assert data["data_source"] in ["EMAIL", "DEVICE", "CHAT", "FILES"]
    assert isinstance(data["collected_item_count"], int)
    assert isinstance(data["collected_bytes"], int)


def assert_evidence(data: dict):
    _assert_common(data)
    assert data["status"] in ["LOGGED", "UNDER_REVIEW", "ADMITTED", "EXCLUDED"]
    assert isinstance(data["size_bytes"], int) and data["size_bytes"] > 0


def assert_interview(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SCHEDULED", "UPJOHN_DELIVERED", "COMPLETED", "NO_SHOW", "CANCELLED",
    ]
    assert isinstance(data["no_show_count"], int)


def assert_designation(data: dict):
    _assert_common(data)
    assert data["status"] in ["DESIGNATED", "CONFIRMED", "CHALLENGED", "WAIVED"]
    assert data["target_type"] in ["EVIDENCE_ITEM", "INTERVIEW", "CASE_REPORT"]
    assert data["privilege_type"] in ["ACP", "WORK_PRODUCT"]


def assert_finding(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "CALIBRATED", "FINAL", "CHALLENGED"]


def assert_recommendation(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "RECALLED"]
    assert isinstance(data["prior_history_count"], int)
    assert isinstance(data["index_policy_matrix"], int)
    assert isinstance(data["index_calibrated"], int)
    assert data["suggested_action"] in ["COACHING", "WARNING", "SUSPENSION", "TERMINATION"]


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "LEGAL_REVIEW", "DISTRIBUTION_APPROVED", "DISTRIBUTED",
        "RECALLED", "SUPERSEDED",
    ]
    assert data["distribution_tier"] in ["RESTRICTED", "LEGAL_CONFIDENTIAL", "BOARD"]


def assert_disclosure(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "DECIDED", "FILED", "OVERRIDDEN", "SUPERSEDED"]
    assert data["regulator"] in ["SEC", "DOJ", "DOL", "FINRA", "DATA_PROTECTION"]


def assert_remediation(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OPEN", "IN_PROGRESS", "AWAITING_VERIFICATION", "VERIFIED", "WAIVED",
    ]
    assert data["action_type"] in [
        "POLICY_UPDATE", "TRAINING", "PROCESS_CHANGE", "CONTROL_IMPLEMENTATION", "MONITORING",
    ]
    assert isinstance(data["is_overdue"], bool)


def assert_pattern_alert(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "ESCALATED", "DISMISSED"]
    assert data["alert_type"] in [
        "REPEAT_SUBJECT", "CATEGORY_SPIKE", "DEPARTMENT_CLUSTER", "RETALIATION_RISK",
    ]
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]
