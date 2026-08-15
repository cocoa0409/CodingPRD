"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. DestructionCertificate and ReminderLog are
append-only and must NOT expose updated_at/version (PRD common-resource-
properties section).
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_RULE_STATUSES = ("DRAFT", "ACTIVE", "PENDING_CONFLICT", "SUPERSEDED", "RETIRED")
_CONFLICT_STATUSES = ("OPEN", "RESOLVED", "WITHDRAWN")
_POSTURES = ("UNSCHEDULED", "HELD", "CONFLICT_BLOCKED", "ELIGIBLE", "RETAINED")
_HOLD_STATUSES = ("DRAFT", "ISSUED", "RELEASED", "CANCELLED")
_ASSIGNMENT_STATUSES = ("AWAITING_ISSUANCE", "PENDING", "ESCALATED",
                        "ACKNOWLEDGED", "RELEASED", "CANCELLED")
_SCOPE_ITEM_STATUSES = ("PENDING_ISSUANCE", "ACTIVE", "EXCLUDED", "RELEASED", "CANCELLED")
_REQUEST_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EXECUTED", "WITHDRAWN")
_ITEM_STATUSES = ("PENDING", "DESTROYED", "SKIPPED_HELD", "SKIPPED_ALREADY_DESTROYED")
_METHODS = ("SECURE_ERASE", "SHRED", "CRYPTO_SHRED")
_NOTICE_KINDS = ("ISSUED_NOTICE", "REMINDER", "ESCALATION", "RELEASE_NOTICE", "CANCEL_NOTICE")
_FRACTION_RE = re.compile(r"\.\d+")


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at among system fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def normalize_instant(value: str) -> str:
    """Strip fractional seconds so an instant compares at second precision."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    return _FRACTION_RE.sub("", value)


def assert_instant_equals(actual: str, expected: str):
    """Two ISO-8601 instants denote the same second regardless of fraction rendering."""
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_governance_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert 1 <= data["fiscal_year_end_day"] <= 31
    assert data["ack_deadline_days"] > 0
    assert data["reminder_interval_days"] > 0
    assert data["max_reminders_before_escalation"] >= 1
    assert data["stale_hold_days"] > 0
    assert data["ack_sla_mode"] in ("STRICT", "REMINDER_ADJUSTED")


def assert_record_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["monthly_storage_cost_cents_per_gb"] > 0


def assert_jurisdiction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]


def assert_custodian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["department"], str)
    assert isinstance(data["open_obligation_count"], int) and data["open_obligation_count"] >= 0


def assert_retention_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["record_class_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["retention_months"] > 0
    assert data["trigger_basis"] in ("EVENT_DATE", "FISCAL_YEAR_END")
    assert is_iso8601_timestamp(data["effective_from"])
    assert data.get("effective_to") is None or is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in _RULE_STATUSES


def assert_retention_conflict(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["record_class_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["incumbent_rule_id"], str)
    assert isinstance(data["challenger_rule_id"], str)
    assert data["status"] in _CONFLICT_STATUSES


def assert_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["record_class_id"], str)
    assert isinstance(data["jurisdiction_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["source_system"], str) and data["source_system"]
    assert is_iso8601_timestamp(data["event_date"])
    assert data["size_gb"] > 0
    assert isinstance(data["auto_delete_enabled"], bool)
    assert data["retention_due_date"] is None or is_iso8601_timestamp(data["retention_due_date"])
    assert isinstance(data["active_hold_count"], int) and data["active_hold_count"] >= 0
    assert isinstance(data["auto_delete_suspended"], bool)
    assert data["disposition_posture"] in _POSTURES
    assert data["status"] in ("ACTIVE", "DESTROYED")


def assert_legal_hold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["matter_ref"], str) and data["matter_ref"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["reason"], str) and data["reason"]
    assert isinstance(data["late_ack_count"], int) and data["late_ack_count"] >= 0
    assert isinstance(data["all_acknowledged"], bool)
    assert isinstance(data["active_scope_count"], int) and data["active_scope_count"] >= 0
    assert data["status"] in _HOLD_STATUSES


def assert_hold_custodian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hold_id"], str)
    assert isinstance(data["custodian_id"], str)
    assert isinstance(data["program_id"], str)
    assert data.get("ack_due_date") is None or is_iso8601_timestamp(data["ack_due_date"])
    assert data.get("was_late") is None or isinstance(data["was_late"], bool)
    assert isinstance(data["reminder_count"], int) and data["reminder_count"] >= 0
    assert data["status"] in _ASSIGNMENT_STATUSES


def assert_hold_scope_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hold_id"], str)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["program_id"], str)
    assert data["status"] in _SCOPE_ITEM_STATUSES


def assert_disposition_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["requester_user_id"], str) and data["requester_user_id"]
    assert data["method"] in _METHODS
    assert isinstance(data["justification"], str) and len(data["justification"]) >= 20
    assert isinstance(data["stale_item_count"], int) and data["stale_item_count"] >= 0
    assert data["status"] in _REQUEST_STATUSES


def assert_disposition_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["program_id"], str)
    assert data["status"] in _ITEM_STATUSES


def assert_destruction_certificate(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["request_id"], str)
    assert isinstance(data["disposition_item_id"], str)
    assert isinstance(data["record_id"], str)
    assert isinstance(data["record_title"], str)
    assert isinstance(data["record_class_code"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert data.get("retention_due_date") is None or is_iso8601_timestamp(data["retention_due_date"])
    assert is_iso8601_timestamp(data["destroyed_at"])
    assert data["method"] in _METHODS
    assert isinstance(data["content_hash"], str)
    assert isinstance(data["witness_user_id"], str) and data["witness_user_id"]
    assert isinstance(data["certificate_seq"], int) and data["certificate_seq"] >= 1


def assert_hold_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    for field in ("active_hold_count", "stale_hold_count", "held_record_count",
                  "eligible_record_count", "over_preserved_record_count"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative int"
    assert isinstance(data["over_preservation_pct"], (int, float))
    assert data["over_preservation_pct"] >= 0
    assert isinstance(data["over_preservation_cost_cents"], int)
    assert data["over_preservation_cost_cents"] >= 0
    assert isinstance(data["threshold_breached"], bool)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_reminder_log(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["hold_id"], str)
    assert isinstance(data["hold_custodian_id"], str)
    assert isinstance(data["custodian_id"], str)
    assert data["kind"] in _NOTICE_KINDS
    assert is_iso8601_timestamp(data["sent_at"])
    assert isinstance(data["reminder_seq"], int) and data["reminder_seq"] >= 0


def assert_freeze_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["reason"], str) and data["reason"]
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_record_hold_invariant(record: dict, active_scope_items: list):
    """Conserved quantity: a record's active_hold_count equals the number of
    ACTIVE scope items referencing it."""
    expected = sum(1 for item in active_scope_items
                   if item.get("record_id") == record["id"] and item.get("status") == "ACTIVE")
    assert record["active_hold_count"] == expected, (
        f"active_hold_count {record['active_hold_count']} != |ACTIVE scope items| {expected}"
    )
    assert record["auto_delete_suspended"] == (record["active_hold_count"] > 0)
