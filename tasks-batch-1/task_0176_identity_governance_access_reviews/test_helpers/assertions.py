"""Entity assertions and domain invariant checkers for the Identity
Governance API. Generic UUID / timestamp validators come from the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ENTITLEMENT_STATUSES = {"ACTIVE", "ARCHIVED"}
_ROLE_STATUSES = {"ACTIVE", "RETIRED"}
_SOD_STATUSES = {"ACTIVE", "DISABLED"}
_SOD_SEVERITIES = {"HARD", "SOFT"}
_IDENTITY_STATUSES = {"ACTIVE", "DISABLED", "DEPROVISIONED"}
_REQUEST_STATUSES = {"DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "REJECTED"}
_GRANT_LIFECYCLE = {"PROVISIONING", "ACTIVE", "REVOKED"}
_GRANT_REVIEW = {"NOT_DUE", "UNDER_REVIEW", "CERTIFIED", "FLAGGED"}
_CAMPAIGN_STATUSES = {"DRAFT", "ACTIVE", "CLOSED"}
_CAMPAIGN_POSTURES = {"OPEN", "IN_REVIEW", "COMPLETE"}
_ITEM_STATUSES = {"PENDING", "UNDER_REVIEW", "CERTIFIED", "REVOKED"}
_AUDIT_EVENT_TYPES = {
    "GRANT_ACTIVATED", "GRANT_REVOKED", "REQUEST_APPROVED", "REQUEST_REJECTED",
    "IDENTITY_DISABLED", "ITEM_CERTIFIED", "ORPHAN_DETECTED",
}


def _assert_common_fields(data: dict):
    """id (bare UUID), created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_entitlement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["system_code"], str) and len(data["system_code"]) > 0
    assert isinstance(data["is_privileged"], bool), "is_privileged must be bool"
    assert isinstance(data["risk_weight"], int), "risk_weight must be int"
    assert 0 <= data["risk_weight"] <= 100, "risk_weight must be 0..100 inclusive"
    assert data["status"] in _ENTITLEMENT_STATUSES, f"unexpected status {data['status']}"


def assert_role(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["entitlement_ids"], list), "entitlement_ids must be a list"
    assert isinstance(data["requires_dual_approval"], bool), "requires_dual_approval must be bool"
    assert data["status"] in _ROLE_STATUSES, f"unexpected status {data['status']}"


def assert_sod_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data["entitlement_a_id"]), "entitlement_a_id must be a UUID"
    assert is_valid_uuid(data["entitlement_b_id"]), "entitlement_b_id must be a UUID"
    assert data["entitlement_a_id"] != data["entitlement_b_id"], "pair sides must differ"
    assert data["severity"] in _SOD_SEVERITIES, f"unexpected severity {data['severity']}"
    assert data["status"] in _SOD_STATUSES, f"unexpected status {data['status']}"


def assert_identity(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["is_human"], bool), "is_human must be bool"
    assert data["status"] in _IDENTITY_STATUSES, f"unexpected status {data['status']}"
    assert isinstance(data["active_grant_count"], int)
    assert isinstance(data["privileged_entitlement_count"], int)
    assert isinstance(data["effective_risk_score"], int)
    assert isinstance(data["projected_risk_score"], int)
    assert isinstance(data["is_orphan"], bool), "is_orphan must be bool"
    assert_identity_invariants(data)


def assert_identity_invariants(data: dict):
    """Conserved-quantity invariants the system keeps continuously consistent
    (PRD §2.7)."""
    assert data["active_grant_count"] >= 0, "active_grant_count must be non-negative"
    assert data["privileged_entitlement_count"] >= 0, "privileged_entitlement_count >= 0"
    assert data["privileged_entitlement_count"] <= data["active_grant_count"], (
        "privileged_entitlement_count cannot exceed active_grant_count"
    )
    assert data["effective_risk_score"] >= 0, "effective_risk_score must be non-negative"
    assert data["projected_risk_score"] >= 0, "projected_risk_score must be non-negative"
    # is_orphan ⇔ status ACTIVE & non-human & zero active grants (PRD §3.2).
    expected_orphan = (
        data["status"] == "ACTIVE"
        and data["is_human"] is False
        and data["active_grant_count"] == 0
    )
    assert data["is_orphan"] == expected_orphan, (
        f"is_orphan should be {expected_orphan} for status={data['status']} "
        f"is_human={data['is_human']} active_grant_count={data['active_grant_count']}"
    )


def assert_access_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["identity_id"]), "identity_id must be a UUID"
    assert is_valid_uuid(data["role_id"]), "role_id must be a UUID"
    assert isinstance(data["justification"], str)
    assert data["status"] in _REQUEST_STATUSES, f"unexpected status {data['status']}"
    assert isinstance(data["sod_conflict_detected"], bool), "sod_conflict_detected must be bool"


def assert_grant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["identity_id"]), "identity_id must be a UUID"
    assert is_valid_uuid(data["entitlement_id"]), "entitlement_id must be a UUID"
    assert isinstance(data["is_just_in_time"], bool), "is_just_in_time must be bool"
    assert data["lifecycle_status"] in _GRANT_LIFECYCLE, f"unexpected lifecycle {data['lifecycle_status']}"
    assert data["review_status"] in _GRANT_REVIEW, f"unexpected review {data['review_status']}"
    assert isinstance(data["risk_contribution"], int), "risk_contribution must be int"


def assert_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data["scope_role_id"]), "scope_role_id must be a UUID"
    assert data["status"] in _CAMPAIGN_STATUSES, f"unexpected status {data['status']}"
    assert data["posture"] in _CAMPAIGN_POSTURES, f"unexpected posture {data['posture']}"
    assert isinstance(data["item_count"], int)
    assert isinstance(data["completion_pct"], (int, float))
    assert isinstance(data["projected_revocation_count"], int)
    assert isinstance(data["realized_revocation_count"], int)


def assert_certification_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["campaign_id"]), "campaign_id must be a UUID"
    assert is_valid_uuid(data["grant_id"]), "grant_id must be a UUID"
    assert data["decision_status"] in _ITEM_STATUSES, f"unexpected decision {data['decision_status']}"


def assert_audit_event(data: dict):
    """AuditEvent is append-only/immutable: id + created_at only, no
    updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in _AUDIT_EVENT_TYPES, f"unexpected event_type {data['event_type']}"
    assert "version" not in data, "AuditEvent must NOT carry a version field"
    assert "updated_at" not in data, "AuditEvent must NOT carry an updated_at field"
