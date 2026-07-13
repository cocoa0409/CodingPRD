"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common properties carried by full entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_establishment(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["jurisdiction"], str) and len(data["jurisdiction"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["sealed_device_count"], int)
    assert data["balance_due_cents"] >= 0, "balance_due_cents must be non-negative"
    assert data["sealed_device_count"] >= 0, "sealed_device_count must be non-negative"


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert isinstance(data["region"], str)


def assert_device(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", "")), "establishment_id must be a UUID"
    assert data["device_type"] in ("SCALE", "FUEL_PUMP", "SCANNER")
    assert data["device_class"] in ("CLASS_III", "CLASS_IIIL")
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["status"] in ("REGISTERED", "SEALED", "CONDEMNED", "OUT_OF_SERVICE", "RETIRED")


def assert_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert is_valid_uuid(data.get("inspector_id", "")), "inspector_id must be a UUID"
    assert data["inspection_type"] in ("ACCURACY_TEST", "PRICE_VERIFICATION", "COMPLAINT_RETEST")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")
    assert data["outcome"] in (None, "PASS", "FAIL")


def assert_complaint(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert data["status"] in ("FILED", "UPHELD", "DISMISSED")


def assert_seal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert is_valid_uuid(data.get("inspection_id", "")), "inspection_id must be a UUID"
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_condemnation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert data["status"] in ("ISSUED", "LIFTED")


def assert_penalty(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", "")), "establishment_id must be a UUID"
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert data["violation_type"] in ("OUT_OF_TOLERANCE", "PRICE_ERROR", "OPERATING_CONDEMNED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("ASSESSED", "PAID", "WAIVED")


def assert_fee_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("establishment_id", "")), "establishment_id must be a UUID"
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a UUID"
    assert data["fee_type"] == "REGISTRATION"
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["proration_applied"], bool)
    assert data["status"] in ("DUE", "PAID")


def assert_test_reading(data: dict):
    """Append-only line item: id + created_at only (PRD §2.4, §3.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TestReading is append-only: no updated_at"
    assert "version" not in data, "TestReading is append-only: no version"


def assert_audit_item(data: dict):
    """Append-only line item: id + created_at only (PRD §2.4, §3.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ScannerAuditItem is append-only: no updated_at"
    assert "version" not in data, "ScannerAuditItem is append-only: no version"


def assert_balance_equals(establishment: dict, expected_cents: int):
    """PRD §2.8 ledger identity check."""
    actual = establishment["balance_due_cents"]
    assert actual == expected_cents, (
        f"Expected balance_due_cents {expected_cents}, got {actual}"
    )
