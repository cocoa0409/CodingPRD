"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ONBOARDING_STATUSES = {
    "CREATED", "SECTION1_COMPLETE", "SECTION2_COMPLETE", "EVERIFY_PENDING",
    "AUTHORIZED", "TERMINATED_NONCONFIRMED", "REVERIFICATION_DUE", "EXPIRED_UNAUTHORIZED",
}
CITIZENSHIP_STATUSES = {"US_CITIZEN", "NONCITIZEN_NATIONAL", "LPR", "ALIEN_AUTHORIZED"}
I9FORM_STATUSES = {"SECTION1_PENDING", "SECTION1_DONE", "SECTION2_DONE", "REVERIFIED"}
DOCUMENT_PATHS = {"LIST_A", "LIST_B_AND_C", "UNSET"}
LIST_CATEGORIES = {"LIST_A", "LIST_B", "LIST_C"}
DOCUMENT_STATUSES = {"PRESENTED", "ACCEPTED", "SUPERSEDED"}
EVERIFY_STATUSES = {
    "DRAFT", "SUBMITTED", "TNC_ISSUED", "REFERRED",
    "EMPLOYMENT_AUTHORIZED", "FINAL_NONCONFIRMATION",
}
TNC_TYPES = {"NONE", "SSA_TNC", "DHS_TNC"}
WORKAUTH_TYPES = {"EAD", "F1_OPT", "F1_STEM_OPT", "TPS", "OTHER"}
WORKAUTH_STATUSES = {"ACTIVE", "EXTENDED", "EXPIRED", "SUPERSEDED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_onboarding(data: dict):
    _assert_common(data)
    assert data["status"] in ONBOARDING_STATUSES, f"unexpected status {data['status']}"
    assert data["citizenship_status"] in CITIZENSHIP_STATUSES
    assert isinstance(data["employee_full_name"], str) and data["employee_full_name"]
    assert isinstance(data["employee_email"], str) and data["employee_email"]
    assert is_iso8601_timestamp(data["section2_deadline"]), "section2_deadline must be ISO 8601"
    assert isinstance(data["is_overdue"], bool), "is_overdue must be a boolean"
    assert isinstance(data["requires_everify"], bool), "requires_everify must be a boolean"


def assert_i9_form(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["onboarding_id"])
    assert data["status"] in I9FORM_STATUSES
    assert data["chosen_document_path"] in DOCUMENT_PATHS
    assert isinstance(data["current_section3_count"], int)


def assert_identity_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["onboarding_id"])
    assert data["list_category"] in LIST_CATEGORIES
    assert data["status"] in DOCUMENT_STATUSES
    assert isinstance(data["is_receipt"], bool)
    assert isinstance(data["accepted_for_section2"], bool)


def assert_everify_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["onboarding_id"])
    assert is_valid_uuid(data["i9_form_id"])
    assert data["status"] in EVERIFY_STATUSES
    assert data["tnc_type"] in TNC_TYPES
    assert isinstance(data["was_late"], bool)
    assert is_iso8601_timestamp(data["everify_deadline"]), "everify_deadline must be ISO 8601"


def assert_work_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["onboarding_id"])
    assert data["auth_type"] in WORKAUTH_TYPES
    assert data["status"] in WORKAUTH_STATUSES
    assert isinstance(data["cap_gap_days"], int)
    assert is_iso8601_timestamp(data["effective_valid_until"])


def assert_reverification_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["i9_form_id"])
    assert is_valid_uuid(data["work_authorization_id"])
    assert data["status"] == "RECORDED"


def assert_audit_entry_is_append_only(data: dict):
    """An AuditEntry carries id + created_at only — no version, no updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "audit entry id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "AuditEntry must NOT expose a version field"
    assert "updated_at" not in data, "AuditEntry must NOT expose an updated_at field"


def assert_risk_summary(data: dict):
    assert isinstance(data["risk_score"], int), "risk_score must be an integer"
    assert 0 <= data["risk_score"] <= 100, "risk_score must be in [0, 100]"
    assert isinstance(data["is_overdue"], bool)
    assert isinstance(data["open_tnc"], bool)
