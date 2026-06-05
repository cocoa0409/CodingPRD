"""Entity assertions and domain invariant checkers for the CLM API.

Each assert_{entity}(data) validates the structural shape an implementer must
return per the PRD. Generic format checks come from the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CONTRACT_STATES = [
    "DRAFT", "UNDER_REVIEW", "REDLINING", "APPROVED", "OUT_FOR_SIGNATURE",
    "ACTIVE", "EXPIRED", "TERMINATED", "CANCELLED",
]
CLAUSE_CATEGORIES = [
    "LIABILITY", "INDEMNITY", "TERMINATION", "PAYMENT", "CONFIDENTIALITY", "OTHER",
]
PARTIES = ["INTERNAL", "COUNTERPARTY"]


def _assert_common(data: dict):
    """Common system fields for entities that carry id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_writeonce_common(data: dict):
    """Common system fields for write-once records (id + created_at only)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "write-once record must not carry updated_at"
    assert "version" not in data, "write-once record must not carry version"


def assert_organization(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["risk_appetite_threshold"], int)
    assert 0 <= data["risk_appetite_threshold"] <= 100
    assert isinstance(data["auto_renew_lead_days"], int)
    assert data["auto_renew_lead_days"] > 0


def assert_clause_template(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["clause_key"], str) and len(data["clause_key"]) > 0
    assert data["category"] in CLAUSE_CATEGORIES
    assert isinstance(data["standard_text"], str)
    assert isinstance(data["risk_weight"], int) and 0 <= data["risk_weight"] <= 40
    assert isinstance(data["is_mandatory"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_contract_template(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["clause_template_ids"], list)
    assert isinstance(data["default_term_months"], int)
    assert isinstance(data["auto_renew_default"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["contract_template_id"])
    assert isinstance(data["counterparty_name"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["term_months"], int) and data["term_months"] > 0
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert isinstance(data["renewal_cycle_index"], int) and data["renewal_cycle_index"] >= 0
    assert data["status"] in CONTRACT_STATES
    assert isinstance(data["drafter_user_id"], str) and len(data["drafter_user_id"]) > 0


def assert_contract_version(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["authored_by_party"] in PARTIES
    assert isinstance(data["clauses"], list)
    assert isinstance(data["deviation_count"], int) and data["deviation_count"] >= 0
    assert data["status"] in ("PROPOSED", "SUPERSEDED", "ACCEPTED")


def assert_approval_workflow(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["pinned_version_id"])
    assert isinstance(data["required_approver_count"], int) and data["required_approver_count"] >= 1
    assert isinstance(data["approvals_received"], int) and data["approvals_received"] >= 0
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "VOIDED")


def assert_approval_step(data: dict):
    _assert_writeonce_common(data)
    assert is_valid_uuid(data["approval_workflow_id"])
    assert isinstance(data["approver_user_id"], str) and len(data["approver_user_id"]) > 0
    assert data["decision"] in ("APPROVE", "REJECT")


def assert_signature_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert data["signer_party"] in PARTIES
    assert isinstance(data["signer_name"], str)
    assert data["status"] in ("SENT", "SIGNED", "DECLINED", "VOIDED")


def assert_obligation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["description"], str)
    assert data["owner_party"] in PARTIES
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in ("OPEN", "FULFILLED", "BREACHED", "WAIVED")


def assert_deviation_approval(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["contract_version_id"])
    assert is_valid_uuid(data["clause_template_id"])
    assert isinstance(data["justification"], str)
    assert data["status"] in ("PENDING", "GRANTED", "DENIED")


def assert_renewal_alert(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_iso8601_timestamp(data["trigger_date"])
    assert data["status"] in ("SCHEDULED", "DUE", "RESOLVED", "CANCELLED")


def assert_audit_event(data: dict):
    _assert_writeonce_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["event_type"], str) and len(data["event_type"]) > 0


def assert_cost_estimate(data: dict):
    """The cost-estimate read echoes contract_id, deviation_count, review_cost_cents."""
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["deviation_count"], int) and data["deviation_count"] >= 0
    assert isinstance(data["review_cost_cents"], int) and data["review_cost_cents"] >= 0
