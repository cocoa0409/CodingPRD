"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601 UTC"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601 UTC"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            "version must be an integer starting at 1"
        )
    else:
        assert "updated_at" not in data, (
            "append-only resources must not carry updated_at (PRD §2.4)"
        )
        assert "version" not in data, (
            "append-only resources must not carry version (PRD §2.4)"
        )


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["gold_card_status"] in (
        "NOT_GOLD_CARDED", "GOLD_CARDED", "SUSPENDED",
    )
    assert data.get("gold_card_service_category") is None or isinstance(
        data["gold_card_service_category"], str
    )
    for field in (
        "rolling_determination_count", "rolling_approval_count",
        "lifetime_determination_count", "lifetime_approval_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer"
        )
    for field in ("rolling_approval_rate", "lifetime_approval_rate"):
        assert data.get(field) is None or isinstance(data[field], (int, float)), (
            f"{field} must be a number or null"
        )


def assert_criteria_set(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["line_of_business"] in ("COMMERCIAL", "MEDICARE", "MEDICAID")
    assert isinstance(data["service_category"], str) and data["service_category"]
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_guideline_version(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("criteria_set_id", ""))
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert isinstance(data["content"], str)
    assert isinstance(data["auto_approve_eligible"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data.get("effective_until") is None or is_iso8601_timestamp(
        data["effective_until"]
    )
    assert data.get("supersedes_version_id") is None or is_valid_uuid(
        data["supersedes_version_id"]
    )
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED")


def assert_prior_auth_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["member_ref"], str) and data["member_ref"]
    assert is_valid_uuid(data.get("criteria_set_id", ""))
    assert is_valid_uuid(data.get("guideline_version_id", ""))
    assert isinstance(data["service_code"], str) and data["service_code"]
    assert data["urgency"] in ("STANDARD", "URGENT")
    assert data["intake_channel"] in ("PORTAL", "FAX", "PHONE", "EDI")
    assert isinstance(data["documentation_complete"], bool)
    assert data["status"] in (
        "RECEIVED", "AUTO_APPROVED", "PENDED_REVIEW", "ESCALATED_MD",
        "APPROVED", "DENIED", "WITHDRAWN",
    )
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data.get("determined_at") is None or is_iso8601_timestamp(
        data["determined_at"]
    )
    assert data.get("escalated_by_user_id") is None or isinstance(
        data["escalated_by_user_id"], str
    )
    assert isinstance(data["is_tat_breached"], bool)


def assert_determination(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("request_id", ""))
    assert data["outcome"] in ("APPROVED", "DENIED")
    assert data["reason_code"] in (
        "GOLD_CARD_AUTO", "AUTO_RULE", "MEDICAL_NECESSITY_MET",
        "MEDICAL_NECESSITY_NOT_MET", "INSUFFICIENT_INFO",
        "EXPERIMENTAL_INVESTIGATIONAL",
    )
    assert data["decided_by_role"] in (
        "SYSTEM_RULE", "CLINICAL_REVIEWER", "MEDICAL_DIRECTOR",
    )
    assert data.get("decided_by_user_id") is None or isinstance(
        data["decided_by_user_id"], str
    )
    assert is_valid_uuid(data.get("guideline_version_id", ""))
    assert isinstance(data.get("notice_text", ""), str) and data["notice_text"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert data["status"] in ("FINAL", "OVERTURNED", "VOID")


def assert_p2p_conference(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("request_id", ""))
    assert isinstance(data["md_user_id"], str) and data["md_user_id"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_appeal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("determination_id", ""))
    assert isinstance(data["appeal_reason"], str) and data["appeal_reason"]
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in (
        "RECEIVED", "IN_REVIEW", "UPHELD", "OVERTURNED", "WITHDRAWN",
    )
    assert data.get("reviewer_id") is None or isinstance(data["reviewer_id"], str)
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])
    assert isinstance(data["is_tat_breached"], bool)


def assert_gold_card_evaluation(data: dict):
    _assert_common_fields(data, with_version=False)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["service_category"], str) and data["service_category"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["window_determination_count"], int)
    assert isinstance(data["window_approval_rate"], (int, float))
    assert data["decision"] in ("GRANTED", "REINSTATED")


def assert_delegation_arrangement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["delegating_plan_name"], str)
    assert is_valid_uuid(data.get("criteria_set_id", ""))
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_deficiency_count"], int)
    assert data["open_deficiency_count"] >= 0


def assert_audit_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("arrangement_id", ""))
    assert is_valid_uuid(data.get("determination_id", ""))
    assert data["finding_type"] in (
        "COMPLIANT", "NOTICE_DEFICIENT", "CRITERIA_MISAPPLIED", "TAT_VIOLATION",
    )
    assert data["status"] in ("OPEN", "CLOSED")


def assert_compliance_event(data: dict):
    _assert_common_fields(data, with_version=False)
    assert data["event_type"] in (
        "AUTO_APPROVAL_FIRED", "TAT_BREACHED", "GOLD_CARD_GRANTED",
        "GOLD_CARD_SUSPENDED", "DELEGATION_SUSPENDED", "DETERMINATION_VOIDED",
        "APPEAL_OVERTURNED",
    )
    assert data.get("request_id") is None or is_valid_uuid(data["request_id"])
    assert data.get("provider_id") is None or is_valid_uuid(data["provider_id"])
    assert isinstance(data.get("details", ""), str)


def assert_provider_stats_invariants(data: dict):
    """Rate fields are null exactly when their count is zero (PRD §2.10)."""
    if data["rolling_determination_count"] == 0:
        assert data["rolling_approval_rate"] is None
    else:
        assert data["rolling_approval_rate"] is not None
    if data["lifetime_determination_count"] == 0:
        assert data["lifetime_approval_rate"] is None
    else:
        assert data["lifetime_approval_rate"] is not None
    assert data["rolling_approval_count"] <= data["rolling_determination_count"]
    assert data["lifetime_approval_count"] <= data["lifetime_determination_count"]
