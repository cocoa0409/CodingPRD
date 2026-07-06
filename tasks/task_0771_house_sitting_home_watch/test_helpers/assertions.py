"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_with_version(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _common_with_version(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["billing_tier"] in ["STANDARD", "PREMIUM"]
    assert data["status"] == "ACTIVE"


def assert_property(data: dict):
    _common_with_version(data)
    assert data["size_tier"] in ["SMALL", "MEDIUM", "LARGE"]
    assert isinstance(data["has_pets"], bool)
    assert isinstance(data["checklist_config"], list) and len(data["checklist_config"]) > 0
    for task in data["checklist_config"]:
        assert task in ["MAIL", "PLANTS", "SECURITY"]
    assert isinstance(data["key_copies_total"], int) and data["key_copies_total"] >= 1
    assert isinstance(data["available_key_copies"], int)


def assert_sitter(data: dict):
    _common_with_version(data)
    assert data["status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED"]
    assert data["background_check_status"] in ["NONE", "SUBMITTED", "CLEARED", "REJECTED"]
    assert isinstance(data["missed_visit_count"], int)
    assert isinstance(data["escalated_incident_count"], int)
    assert data["reliability_score"] >= 0


def assert_booking(data: dict):
    _common_with_version(data)
    assert data["booking_type"] in ["RECURRING", "VACATION"]
    assert data["status"] in ["DRAFT", "PENDING_ASSIGNMENT", "SCHEDULED",
                              "ACTIVE", "COMPLETED", "CANCELLED"]


def assert_visit(data: dict):
    _common_with_version(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "FLAGGED",
                              "DONE", "MISSED", "CANCELLED"]
    assert isinstance(data["is_weekend"], bool)


def assert_visit_log_entry(data: dict):
    """VisitLogEntry is append-only: only id + created_at, no updated_at / version."""
    _common(data)
    assert "updated_at" not in data, "VisitLogEntry must not carry updated_at"
    assert "version" not in data, "VisitLogEntry must not carry version"
    assert data["entry_type"] in ["PHOTO", "GPS_PING", "NOTE"]


def assert_key_assignment(data: dict):
    _common_with_version(data)
    assert data["status"] in ["AT_OFFICE", "CHECKED_OUT", "RETURNED", "LOST"]


def assert_incident(data: dict):
    _common_with_version(data)
    assert data["category"] in ["BREAK_IN", "WATER_LEAK", "FIRE", "MEDICAL", "OTHER"]
    assert data["severity"] in ["MINOR", "MAJOR", "EMERGENCY"]
    assert data["status"] in ["OPEN", "ESCALATED", "RESOLVED"]


def assert_invoice(data: dict):
    _common_with_version(data)
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_key_custody_conserved(prop: dict, checked_out: int, lost: int):
    """PRD Section 2.9: available + checked-out + lost == key_copies_total."""
    assert prop["available_key_copies"] + checked_out + lost == prop["key_copies_total"], (
        f"Key custody not conserved: available {prop['available_key_copies']} + "
        f"checked_out {checked_out} + lost {lost} != total {prop['key_copies_total']}"
    )
