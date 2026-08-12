"""Entity assertions and domain invariant checkers (PRD sections 2.5, 3.x)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity_label: str):
    """Standard system-managed fields present on all primary resources."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def assert_property(data: dict):
    """Validate a Property response against the PRD contract."""
    _assert_common(data, "Property")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["sale_share_designation"] in ["SELLS_AND_SHARES", "SHARES_ONLY", "NO_SALE_NO_SHARE"]
    assert data["posture"] in ["NORMAL", "FROZEN"]
    assert isinstance(data["granted_purpose_count"], int)
    assert data["granted_purpose_count"] >= 0


def assert_jurisdiction_policy(data: dict):
    """Validate a JurisdictionPolicy response against the PRD contract."""
    _assert_common(data, "JurisdictionPolicy")
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) > 0
    assert data["banner_regime"] in ["OPT_IN_REQUIRED", "OPT_OUT_ALLOWED", "NOTICE_ONLY"]
    assert isinstance(data["min_consent_age"], int)
    assert isinstance(data["retention_days"], int) and data["retention_days"] >= 1
    assert isinstance(data["gpc_honored"], bool)
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_banner_config(data: dict):
    """Validate a ConsentBannerConfig response against the PRD contract."""
    _assert_common(data, "ConsentBannerConfig")
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) > 0
    assert isinstance(data["categories_shown"], list)
    for cat in data["categories_shown"]:
        assert cat in ["ANALYTICS", "ADVERTISING", "SALE_SHARE"]
    assert isinstance(data["config_label"], str)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED", "SUPPRESSED", "ARCHIVED"]


def assert_vendor(data: dict):
    """Validate a Vendor response against the PRD contract."""
    _assert_common(data, "Vendor")
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["declared_purposes"], list)
    assert isinstance(data["tracker_signatures"], list)
    assert data["status"] in ["PENDING_REVIEW", "APPROVED", "SUSPENDED"]
    assert isinstance(data["risk_score_strict"], int) and data["risk_score_strict"] >= 0
    assert isinstance(data["risk_score_weighted"], int) and data["risk_score_weighted"] >= 0


def assert_tag_rule(data: dict):
    """Validate a TagRule response against the PRD contract."""
    _assert_common(data, "TagRule")
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a valid UUID"
    assert is_valid_uuid(data.get("banner_config_id", "")), "banner_config_id must be a valid UUID"
    assert data["purpose_category"] in ["ANALYTICS", "ADVERTISING", "SALE_SHARE"]
    assert data["status"] in ["ENABLED", "DISABLED", "RETIRED"]


def assert_visitor_profile(data: dict):
    """Validate a VisitorProfile response against the PRD contract."""
    _assert_common(data, "VisitorProfile")
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) > 0
    assert data["age_status"] in ["UNVERIFIED", "ADULT", "CHILD"]
    assert data["gpc_effective"] in ["UNSET", "ON", "OFF"]
    assert isinstance(data["sale_share_opted_out"], bool)


def assert_gpc_signal_event(data: dict):
    """Validate a GpcSignalEvent — append-only: only id, created_at, visitor_id, signal."""
    assert is_valid_uuid(data.get("id", "")), "GpcSignalEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "GpcSignalEvent.created_at must be ISO 8601"
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be a valid UUID"
    assert data["signal"] in ["ON", "OFF"]
    assert "version" not in data, "GpcSignalEvent must not carry a version field"
    assert "updated_at" not in data, "GpcSignalEvent must not carry an updated_at field"


def assert_consent_record(data: dict):
    """Validate a ConsentRecord response against the PRD contract."""
    _assert_common(data, "ConsentRecord")
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be a valid UUID"
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert data["purpose_category"] in ["NECESSARY", "ANALYTICS", "ADVERTISING", "SALE_SHARE"]
    assert data["status"] in ["GRANTED", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["policy_snapshot_retention_days"], int)
    assert is_iso8601_timestamp(data["last_changed_at"])
    assert is_iso8601_timestamp(data["expires_at_pinned"])
    assert is_iso8601_timestamp(data["expires_at_rolling"])
    assert data["source_of_decision"] in [
        "EXPLICIT_GRANT", "EXPLICIT_WITHDRAW", "AUTO_GPC_WITHDRAW", "EXPIRY",
    ]


def assert_do_not_sell_request(data: dict):
    """Validate a DoNotSellRequest response against the PRD contract."""
    _assert_common(data, "DoNotSellRequest")
    assert is_valid_uuid(data.get("visitor_id", "")), "visitor_id must be a valid UUID"
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert isinstance(data["scope_categories"], list)
    assert data["verification_status"] in ["UNVERIFIED", "VERIFIED", "REJECTED"]
    assert data["propagation_status"] in ["NOT_STARTED", "PROPAGATING", "ALL_CONFIRMED", "PARTIAL_FAILURE"]
    assert isinstance(data["total_propagations"], int)
    assert isinstance(data["pending_count"], int)
    assert isinstance(data["confirmed_count"], int)
    assert isinstance(data["failed_count"], int)


def assert_vendor_propagation(data: dict):
    """Validate a VendorPropagation response against the PRD contract."""
    _assert_common(data, "VendorPropagation")
    assert is_valid_uuid(data.get("request_id", "")), "request_id must be a valid UUID"
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a valid UUID"
    assert data["status"] in ["PENDING", "CONFIRMED", "FAILED"]
    assert isinstance(data["attempts"], int) and data["attempts"] >= 1
    assert is_iso8601_timestamp(data["last_attempt_at"])


def assert_tag_audit_scan(data: dict):
    """Validate a TagAuditScan response against the PRD contract."""
    _assert_common(data, "TagAuditScan")
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert data["status"] in ["SCHEDULED", "COMPLETED"]
    assert isinstance(data["created_by_user_id"], str) and len(data["created_by_user_id"]) > 0
    assert isinstance(data["findings_created_count"], int)
    assert isinstance(data["unauthorized_findings_count"], int)


def assert_tracker_finding(data: dict):
    """Validate a TrackerFinding response against the PRD contract."""
    _assert_common(data, "TrackerFinding")
    assert is_valid_uuid(data.get("scan_id", "")), "scan_id must be a valid UUID"
    assert isinstance(data["tracker_signature"], str) and len(data["tracker_signature"]) > 0
    assert data["violation_type"] in ["UNAUTHORIZED_TRACKER", "PURPOSE_MISMATCH"]
    assert data["severity"] in ["HIGH", "MEDIUM"]
    assert data["status"] in ["OPEN", "REMEDIATED", "CONFIRMED_VIOLATION", "CLOSED"]


def assert_regulatory_sweep(data: dict):
    """Validate a RegulatorySweep response against the PRD contract."""
    _assert_common(data, "RegulatorySweep")
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a valid UUID"
    assert isinstance(data["regulator_ref"], str) and len(data["regulator_ref"]) > 0
    assert isinstance(data["jurisdiction_code"], str) and len(data["jurisdiction_code"]) > 0
    assert isinstance(data["deadline_days"], int) and data["deadline_days"] > 0
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["status"] in ["OPEN", "EVIDENCE_COLLECTION", "RESPONDED", "ESCALATED", "CLOSED"]


def assert_propagation_counter_invariants(request: dict):
    """PRD invariant: pending + confirmed + failed == total_propagations == child count."""
    total = request["total_propagations"]
    pending = request["pending_count"]
    confirmed = request["confirmed_count"]
    failed = request["failed_count"]
    assert pending + confirmed + failed == total, (
        f"Counter partition violated: {pending}+{confirmed}+{failed} != {total}"
    )
    if pending > 0:
        assert request["propagation_status"] == "PROPAGATING"
    elif failed == 0:
        assert request["propagation_status"] == "ALL_CONFIRMED"
    else:
        assert request["propagation_status"] == "PARTIAL_FAILURE"
