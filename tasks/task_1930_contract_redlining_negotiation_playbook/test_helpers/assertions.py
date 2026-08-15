"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Primary resources carry id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_audit_fields(data: dict):
    """Append-only audit records carry ONLY id + created_at; updated_at and
    version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit records must not carry updated_at"
    assert "version" not in data, "audit records must not carry version"


def assert_playbook(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["DRAFT", "ACTIVE", "DEPRECATED"]
    assert data["published_at"] is None or is_iso8601_timestamp(data["published_at"])
    assert isinstance(data["clause_count"], int) and data["clause_count"] >= 0
    assert isinstance(data["active_negotiation_count"], int) and data["active_negotiation_count"] >= 0


def assert_clause_template(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("playbook_id", "")), "playbook_id must be a UUID"
    assert isinstance(data["clause_key"], str) and data["clause_key"]
    assert data["category"] in ["RISK", "COMMERCIAL", "OPERATIONAL", "REGULATORY"]
    assert isinstance(data["standard_text"], str)
    assert isinstance(data["fallback_positions"], list)
    assert len(data["fallback_positions"]) <= 3, "at most three fallback positions"
    assert data["approver_role_required"] in [
        "LEGAL_COUNSEL", "FINANCE_CONTROLLER", "BUSINESS_OWNER", "CHIEF_COUNSEL"]
    assert data["deviation_severity_cap"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_contract_type(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    low = data["low_value_threshold_cents"]
    mid = data["mid_value_threshold_cents"]
    high = data["high_value_threshold_cents"]
    assert isinstance(low, int) and isinstance(mid, int) and isinstance(high, int)
    assert low < mid < high, "tier thresholds must be strictly ascending"
    assert isinstance(data["auto_approve_below_cents"], int)
    assert isinstance(data["requires_chief_counsel_above_cents"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_counterparty(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["jurisdiction"], str) and data["jurisdiction"]
    assert data["risk_tier"] in ["LOW", "STANDARD", "HIGH_RISK", "SANCTIONED"]
    assert isinstance(data["active_negotiation_count"], int) and data["active_negotiation_count"] >= 0
    assert data["last_executed_at"] is None or is_iso8601_timestamp(data["last_executed_at"])


def assert_user(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["primary_role"] in [
        "CONTRACT_ANALYST", "BUSINESS_OWNER", "LEGAL_COUNSEL",
        "FINANCE_CONTROLLER", "CHIEF_COUNSEL", "SIGNATORY", "OPS_ADMIN"]
    assert isinstance(data["can_sign_above_cents"], int)
    assert data["status"] in ["ACTIVE", "DEACTIVATED"]


def assert_intake_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("submitted_by_user_id", "")), "submitted_by_user_id must be a UUID"
    assert is_valid_uuid(data.get("contract_type_id", "")), "contract_type_id must be a UUID"
    assert is_valid_uuid(data.get("counterparty_id", "")), "counterparty_id must be a UUID"
    assert isinstance(data["contract_value_cents"], int) and data["contract_value_cents"] > 0
    assert data["status"] in ["PENDING_TRIAGE", "ROUTED", "NEGOTIATION_OPENED", "REJECTED", "CANCELLED"]


def assert_triage_decision(data: dict):
    _assert_audit_fields(data)
    assert data["routing_bucket"] in ["SELF_SERVE", "STANDARD", "ELEVATED", "EXECUTIVE"]
    assert data["value_tier"] in ["LOW", "MID", "HIGH", "VERY_HIGH"]
    assert data["counterparty_risk"] in ["LOW", "STANDARD", "HIGH_RISK", "SANCTIONED"]
    assert data["decided_by"] in ["SYSTEM", "ANALYST_OVERRIDE"]
    assert is_iso8601_timestamp(data["decided_at"])


def assert_negotiation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("intake_request_id", "")), "intake_request_id must be a UUID"
    assert is_valid_uuid(data.get("playbook_id", "")), "playbook_id must be a UUID"
    assert isinstance(data["playbook_version_at_pin"], int)
    assert isinstance(data["contract_value_cents"], int) and data["contract_value_cents"] > 0
    assert data["draft_status"] in ["OPEN", "REDLINING", "AWAITING_COUNTERSIGN", "EXECUTED", "ABORTED"]
    assert data["approval_status"] in [
        "NO_DEVIATIONS", "DEVIATIONS_PENDING", "APPROVED_WITH_DEVIATIONS", "BLOCKED"]
    assert data["signature_status"] in [
        "NOT_STARTED", "ROUTING", "PARTIALLY_SIGNED", "FULLY_SIGNED", "EXECUTION_RECORDED"]
    assert isinstance(data["current_round_index"], int) and data["current_round_index"] >= 0
    assert isinstance(data["open_deviation_count"], int) and data["open_deviation_count"] >= 0
    assert isinstance(data["blocking_deviation_count"], int) and data["blocking_deviation_count"] >= 0
    assert isinstance(data["total_rounds"], int) and data["total_rounds"] >= 0
    assert isinstance(data["cycle_time_seconds"], int) and data["cycle_time_seconds"] >= 0


def assert_negotiation_round(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert is_iso8601_timestamp(data["opened_at"])
    assert data["status"] in ["OPEN", "CLOSED", "SUPERSEDED"]
    assert data["closed_at"] is None or is_iso8601_timestamp(data["closed_at"])
    assert data["closed_by_user_id"] is None or isinstance(data["closed_by_user_id"], str)
    assert data["round_duration_seconds"] is None or isinstance(data["round_duration_seconds"], int)


def assert_deviation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("negotiation_id", "")), "negotiation_id must be a UUID"
    assert is_valid_uuid(data.get("clause_template_id", "")), "clause_template_id must be a UUID"
    assert isinstance(data["proposed_text"], str)
    assert isinstance(data["fallback_index"], int) and data["fallback_index"] >= -1
    assert data["severity"] in ["STANDARD", "FALLBACK", "NON_STANDARD"]
    assert isinstance(data["risk_score"], int) and 0 <= data["risk_score"] <= 100
    assert data["required_approver_role"] in [
        "LEGAL_COUNSEL", "FINANCE_CONTROLLER", "BUSINESS_OWNER", "CHIEF_COUNSEL"]
    assert isinstance(data["escalated_to_chief_counsel"], bool)
    assert data["status"] in [
        "OPEN", "IN_REVIEW", "APPROVED", "REJECTED", "ESCALATED", "WITHDRAWN", "SUPERSEDED"]
    assert is_iso8601_timestamp(data["opened_at"])
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])


def assert_approval_decision(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("deviation_id", "")), "deviation_id must be a UUID"
    assert data["decision"] in ["APPROVE", "REJECT", "ESCALATE", "ABSTAIN"]
    assert is_iso8601_timestamp(data["decided_at"])
    assert isinstance(data["snapshot_clause_version"], int)


def assert_signature_packet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("negotiation_id", "")), "negotiation_id must be a UUID"
    assert isinstance(data["signatories"], list) and len(data["signatories"]) >= 1
    for entry in data["signatories"]:
        assert isinstance(entry["user_id"], str)
        assert isinstance(entry["order_index"], int)
        assert isinstance(entry["authority_cap_cents"], int)
    assert is_iso8601_timestamp(data["signature_window_opens_at"])
    assert is_iso8601_timestamp(data["signature_window_closes_at"])
    assert isinstance(data["signed_record"], list)
    assert data["status"] in [
        "ROUTING", "PARTIALLY_SIGNED", "FULLY_SIGNED", "EXPIRED", "VOIDED", "EXECUTION_RECORDED"]


def assert_obligation(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("negotiation_id", "")), "negotiation_id must be a UUID"
    assert is_valid_uuid(data.get("clause_template_id", "")), "clause_template_id must be a UUID"
    assert isinstance(data["obligation_text"], str)
    assert data["extraction_source"] in ["STANDARD_TEXT", "FALLBACK_POSITION", "APPROVED_DEVIATION"]
    assert data["owner_role"] in ["BUSINESS_OWNER", "LEGAL_COUNSEL", "FINANCE_CONTROLLER"]
    assert isinstance(data["due_offset_days"], int)
    assert is_iso8601_timestamp(data["due_date"])
    assert is_iso8601_timestamp(data["extracted_at"])


def assert_negotiation_counters_invariants(negotiation: dict):
    """Counter invariants that must hold on any negotiation read (PRD §2.11)."""
    assert negotiation["blocking_deviation_count"] <= negotiation["open_deviation_count"], (
        "blocking deviations are a subset of open deviations")
    assert negotiation["total_rounds"] >= negotiation["current_round_index"] - 1
    assert negotiation["total_rounds"] >= 0
