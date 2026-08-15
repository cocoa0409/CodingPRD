"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ActivityStatus,
    AssessmentStatus,
    ContractVerificationStatus,
    DataElementStatus,
    DataSystemStatus,
    FulfillmentStatus,
    NoticeStatus,
    PurposeStatus,
    RequestVerificationStatus,
    TaskStatus,
    TransferStatus,
    VendorContractStatus,
    VendorStatus,
)

_ELEMENT_CATEGORIES = [
    "BASIC_CONTACT", "IDENTIFIER", "FINANCIAL", "HEALTH",
    "BIOMETRIC", "PRECISE_LOCATION", "MINOR_DATA",
]
_CLASSIFICATIONS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
_REGIONS = ["US", "EU", "UK", "BR", "APAC"]
_NOTICE_SCOPES = ["WEBSITE", "MOBILE_APP", "EMPLOYEE", "LOYALTY_PROGRAM"]
_CLAUSE_CODES = ["DPA", "BREACH_NOTICE_72H", "DELETION_ON_EXIT", "SUBPROCESSOR_CONSENT", "AUDIT_RIGHTS"]
_PURPOSE_TYPES = ["MARKETING", "ANALYTICS", "SERVICE_DELIVERY", "EMPLOYMENT", "LEGAL_COMPLIANCE", "RESEARCH"]
_LEGAL_BASES = ["CONSENT", "CONTRACT", "LEGAL_OBLIGATION", "LEGITIMATE_INTEREST", "VITAL_INTEREST", "PUBLIC_TASK"]
_REQUEST_TYPES = ["ACCESS", "DELETION", "CORRECTION", "PORTABILITY", "OPT_OUT"]
_MECHANISMS = ["SCC_2021", "ADEQUACY", "BCR", "DEROGATION"]
_TRIGGER_REASONS = ["MANUAL", "RISK_THRESHOLD", "RECLASSIFICATION"]


def _assert_common(data: dict, context: str):
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{context}: created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{context}: updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{context}: version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_retention_policy(data: dict):
    _assert_common(data, "RetentionPolicy")
    assert isinstance(data.get("policy_code"), str) and data["policy_code"]
    assert isinstance(data.get("duration_days"), int) and data["duration_days"] > 0
    assert data.get("disposal_action") in ["ANONYMIZE", "DELETE", "ARCHIVE"]


def assert_data_element(data: dict):
    _assert_common(data, "DataElement")
    assert isinstance(data.get("element_key"), str) and data["element_key"]
    assert data.get("category") in _ELEMENT_CATEGORIES
    assert data.get("classification") in _CLASSIFICATIONS
    assert data.get("status") in [s.value for s in DataElementStatus]


def assert_data_system(data: dict):
    _assert_common(data, "DataSystem")
    assert isinstance(data.get("system_key"), str) and data["system_key"]
    assert data.get("hosting_region") in _REGIONS
    assert isinstance(data.get("stores_categories"), list)
    for member in data["stores_categories"]:
        assert member in _ELEMENT_CATEGORIES, f"DataSystem: bad stores_categories member {member!r}"
    assert data.get("status") in [s.value for s in DataSystemStatus]


def assert_notice(data: dict):
    _assert_common(data, "Notice")
    assert data.get("scope") in _NOTICE_SCOPES
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("body"), str)
    assert is_iso8601_timestamp(data.get("effective_from", "")), "Notice: effective_from must be ISO 8601 UTC"
    assert data.get("effective_to") is None or is_iso8601_timestamp(data["effective_to"])
    assert data.get("supersedes_notice_id") is None or isinstance(data["supersedes_notice_id"], str)
    assert data.get("status") in [s.value for s in NoticeStatus]
    assert data.get("published_at") is None or is_iso8601_timestamp(data["published_at"])
    assert data.get("superseded_by_notice_id") is None or isinstance(data["superseded_by_notice_id"], str)


def assert_state_law_rule(data: dict):
    _assert_common(data, "StateLawRule")
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert isinstance(data.get("law_name"), str) and data["law_name"]
    assert isinstance(data.get("resident_records_threshold"), int) and data["resident_records_threshold"] > 0
    pct = data.get("revenue_share_threshold_pct")
    assert isinstance(pct, (int, float)) and 0 < pct <= 100
    assert isinstance(data.get("request_deadline_days"), int) and data["request_deadline_days"] > 0
    assert isinstance(data.get("extension_days"), int) and data["extension_days"] >= 0


def assert_vendor(data: dict):
    _assert_common(data, "Vendor")
    assert isinstance(data.get("vendor_name"), str) and data["vendor_name"]
    assert data.get("home_region") in _REGIONS
    assert isinstance(data.get("processes_categories"), list)
    for member in data["processes_categories"]:
        assert member in _ELEMENT_CATEGORIES, f"Vendor: bad processes_categories member {member!r}"
    assert data.get("risk_tier") in ["LOW", "STANDARD", "HIGH"]
    assert data.get("status") in [s.value for s in VendorStatus]


def assert_vendor_contract(data: dict):
    _assert_common(data, "VendorContract")
    assert is_valid_uuid(data.get("vendor_id", "")), "VendorContract: vendor_id must be a UUID"
    assert isinstance(data.get("provided_clauses"), list)
    for member in data["provided_clauses"]:
        assert member in _CLAUSE_CODES, f"VendorContract: bad clause {member!r}"
    assert isinstance(data.get("required_clauses"), list)
    assert isinstance(data.get("missing_clauses"), list)
    for member in data["missing_clauses"]:
        assert member in _CLAUSE_CODES, f"VendorContract: bad missing clause {member!r}"
    assert data["missing_clauses"] == sorted(data["missing_clauses"]), (
        "VendorContract: missing_clauses must be sorted by clause code ascending"
    )
    assert data.get("verification_status") in [s.value for s in ContractVerificationStatus]
    assert data.get("status") in [s.value for s in VendorContractStatus]


def assert_activity(data: dict):
    _assert_common(data, "ProcessingActivity")
    assert isinstance(data.get("activity_name"), str) and data["activity_name"]
    assert isinstance(data.get("business_unit"), str)
    assert data.get("notice_scope") in _NOTICE_SCOPES
    assert isinstance(data.get("data_element_ids"), list)
    assert data.get("vendor_id") is None or isinstance(data["vendor_id"], str)
    assert isinstance(data.get("risk_score"), int), "ProcessingActivity: risk_score must be an integer"
    assert 0 <= data["risk_score"] <= 1000, "ProcessingActivity: risk_score must be within 0..1000"
    assert isinstance(data.get("pia_required"), bool)
    assert data.get("status") in [s.value for s in ActivityStatus]


def assert_purpose(data: dict):
    _assert_common(data, "Purpose")
    assert is_valid_uuid(data.get("activity_id", "")), "Purpose: activity_id must be a UUID"
    assert data.get("purpose_type") in _PURPOSE_TYPES
    assert data.get("legal_basis") in _LEGAL_BASES
    assert is_valid_uuid(data.get("retention_policy_id", "")), "Purpose: retention_policy_id must be a UUID"
    assert data.get("pinned_notice_id") is None or isinstance(data["pinned_notice_id"], str)
    assert is_iso8601_timestamp(data.get("retention_expires_at", "")), (
        "Purpose: retention_expires_at must be ISO 8601 UTC"
    )
    assert data.get("status") in [s.value for s in PurposeStatus]


def assert_assessment(data: dict):
    _assert_common(data, "PrivacyImpactAssessment")
    assert is_valid_uuid(data.get("activity_id", "")), "PrivacyImpactAssessment: activity_id must be a UUID"
    assert data.get("trigger_reason") in _TRIGGER_REASONS
    assert isinstance(data.get("screening_score"), int)
    assert data.get("final_score") is None or isinstance(data["final_score"], int)
    assert data.get("submitted_by_user_id") is None or isinstance(data["submitted_by_user_id"], str)
    assert data.get("status") in [s.value for s in AssessmentStatus]


def assert_consumer(data: dict):
    _assert_common(data, "Consumer")
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2


def assert_rights_request(data: dict):
    _assert_common(data, "RightsRequest")
    assert is_valid_uuid(data.get("consumer_id", "")), "RightsRequest: consumer_id must be a UUID"
    assert data.get("request_type") in _REQUEST_TYPES
    assert isinstance(data.get("requested_categories"), list) and data["requested_categories"], (
        "RightsRequest: requested_categories must be a non-empty list"
    )
    for member in data["requested_categories"]:
        assert member in _ELEMENT_CATEGORIES, f"RightsRequest: bad category {member!r}"
    assert data.get("applicable_state_code") is None or isinstance(data["applicable_state_code"], str)
    assert is_iso8601_timestamp(data.get("provisional_due_at", "")), (
        "RightsRequest: provisional_due_at must be ISO 8601 UTC"
    )
    assert data.get("final_due_at") is None or is_iso8601_timestamp(data["final_due_at"])
    assert isinstance(data.get("is_overdue"), bool)
    assert data.get("verification_status") in [s.value for s in RequestVerificationStatus]
    assert data.get("fulfillment_status") in [s.value for s in FulfillmentStatus]


def assert_request_task(data: dict):
    _assert_common(data, "RequestTask")
    assert is_valid_uuid(data.get("request_id", "")), "RequestTask: request_id must be a UUID"
    assert is_valid_uuid(data.get("data_system_id", "")), "RequestTask: data_system_id must be a UUID"
    assert data.get("status") in [s.value for s in TaskStatus]
    assert data.get("outcome_notes") is None or isinstance(data["outcome_notes"], str)


def assert_transfer(data: dict):
    _assert_common(data, "CrossBorderTransfer")
    assert is_valid_uuid(data.get("source_system_id", "")), "Transfer: source_system_id must be a UUID"
    assert is_valid_uuid(data.get("vendor_id", "")), "Transfer: vendor_id must be a UUID"
    assert is_valid_uuid(data.get("vendor_contract_id", "")), "Transfer: vendor_contract_id must be a UUID"
    assert is_valid_uuid(data.get("activity_id", "")), "Transfer: activity_id must be a UUID"
    assert data.get("dest_region") in _REGIONS
    assert data.get("mechanism") in _MECHANISMS
    assert is_iso8601_timestamp(data.get("effective_from", "")), "Transfer: effective_from must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("effective_to", "")), "Transfer: effective_to must be ISO 8601 UTC"
    assert data.get("suspension_reason") in (None, "ACTIVITY_HOLD", "CONTRACT_SUPERSEDED")
    assert data.get("status") in [s.value for s in TransferStatus]


def assert_applicability_evaluation(data: dict):
    """Append-only audit record: id + created_at only — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ApplicabilityEvaluation: id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ApplicabilityEvaluation: created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "ApplicabilityEvaluation must not carry updated_at"
    assert "version" not in data, "ApplicabilityEvaluation must not carry version"
    assert is_valid_uuid(data.get("state_law_rule_id", "")), (
        "ApplicabilityEvaluation: state_law_rule_id must be a UUID"
    )
    assert isinstance(data.get("evaluation_run_id"), str) and data["evaluation_run_id"]
    assert isinstance(data.get("resident_consumer_count"), int)
    assert isinstance(data.get("revenue_share_pct"), (int, float))
    assert isinstance(data.get("applies"), bool)
    assert isinstance(data.get("margin_to_threshold"), int)


def assert_iso_equal(actual: str, expected: str, context: str = "timestamp"):
    """Compare two ISO 8601 UTC instants, tolerating the optional three
    fractional digits spelled out in the envelope (".000Z" vs "Z")."""
    def _canon(value: str) -> str:
        if isinstance(value, str) and value.endswith(".000Z"):
            return value[:-5] + "Z"
        return value

    assert is_iso8601_timestamp(actual), f"{context}: {actual!r} is not ISO 8601 UTC"
    assert _canon(actual) == _canon(expected), (
        f"{context}: expected {expected!r}, got {actual!r}"
    )


def assert_activity_invariants(data: dict):
    """Domain invariants that must hold for any processing activity (PRD §3.4, §2.10)."""
    assert isinstance(data.get("risk_score"), int) and 0 <= data["risk_score"] <= 1000
    assert isinstance(data.get("pia_required"), bool)
    # gating: pia_required is derived only from the screening score vs the 500 threshold
    assert data["pia_required"] == (data["risk_score"] >= 500), (
        f"pia_required {data['pia_required']} inconsistent with screening risk_score "
        f"{data['risk_score']} vs threshold 500"
    )
