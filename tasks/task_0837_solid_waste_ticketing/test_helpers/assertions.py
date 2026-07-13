"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_common_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_facility(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["gas_status"] in ("NORMAL", "ELEVATED", "EXCEEDANCE")
    assert data["acceptance_posture"] in ("OPEN", "RESTRICTED", "CLOSED")
    assert data["consumed_airspace_cubic_yards"] >= 0


def assert_cell(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OPEN", "FULL", "CLOSED")
    assert data["consumed_cubic_yards"] >= 0
    assert isinstance(data["fill_sequence"], int)


def assert_hauler_account(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["credit_limit_cents"], int)


def assert_manifest(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CONSUMED", "CANCELLED")
    assert isinstance(data["is_special_waste"], bool)
    assert isinstance(data["special_waste_cleared"], bool)


def assert_special_waste_approval(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")
    assert data["waste_type"] in ("TIRE", "ASBESTOS")


def assert_ticket(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("CREATED", "WEIGHED", "INSPECTED", "POSTED", "REJECTED", "VOIDED")
    assert data["material"] in (
        "MSW", "CONSTRUCTION_DEBRIS", "GREEN_WASTE", "CLEAN_WOOD", "TIRE", "ASBESTOS",
    )
    assert isinstance(data["is_diverted"], bool)
    assert isinstance(data["estimated_fee_cents"], int)


def assert_gas_reading(data: dict):
    # Append-only event: id + created_at only, no updated_at / version (PRD §2.4).
    _assert_common(data)
    assert data["resulting_gas_status"] in ("NORMAL", "ELEVATED", "EXCEEDANCE")
    assert "version" not in data, "GasReading is append-only and must not expose version"
    assert "updated_at" not in data, "GasReading is append-only and must not expose updated_at"


def assert_disposal_window(data: dict):
    _assert_common_versioned(data)
    assert data["waste_type"] in ("TIRE", "ASBESTOS")


def assert_scale_reservation(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["lane_number"], int)


def assert_invoice(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert isinstance(data["tipping_subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_payment(data: dict):
    _assert_common_versioned(data)
    assert data["method"] in ("ACH", "CARD", "CHECK")
    assert isinstance(data["amount_cents"], int)
