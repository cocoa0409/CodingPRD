"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the system-managed identity fields and the
field types/enums the PRD declares for that resource. Append-only AffectedLot
is checked WITHOUT updated_at / version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str)
    assert data["regulator"] in ("FDA", "CPSC"), data["regulator"]
    assert isinstance(data["unit_list_price_cents"], int) and data["unit_list_price_cents"] >= 1
    assert data.get("active_recall_id") is None or is_valid_uuid(data["active_recall_id"])


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["serial_start"], int) and data["serial_start"] >= 1
    assert isinstance(data["serial_end"], int) and data["serial_end"] >= data["serial_start"]
    assert data["manufactured_units"] == data["serial_end"] - data["serial_start"] + 1
    assert data["quarantine_status"] in ("RELEASED", "HELD"), data["quarantine_status"]


def assert_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["serial_number"], int)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] >= 0
    assert isinstance(data["affected"], bool)


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["contact_channel"] in ("EMAIL", "SMS", "MAIL"), data["contact_channel"]
    assert isinstance(data["contact_address"], str)
    assert isinstance(data["reachable"], bool)


def assert_recall(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert data["status"] in (
        "DRAFT", "CLASSIFIED", "ANNOUNCED", "MONITORING", "EFFECTIVE", "TERMINATED",
    ), data["status"]
    assert data.get("classification") in (None, "CLASS_I", "CLASS_II", "CLASS_III")
    assert isinstance(data["affected_unit_count"], int) and data["affected_unit_count"] >= 0
    assert isinstance(data["recovered_unit_count"], int) and data["recovered_unit_count"] >= 0
    assert isinstance(data["effectiveness_pct"], (int, float))
    assert isinstance(data["total_refund_cents"], int) and data["total_refund_cents"] >= 0


def assert_recall_invariants(data: dict):
    """Counter relationships that must hold after any recall operation (PRD §3.11)."""
    assert data["recovered_unit_count"] <= data["affected_unit_count"], (
        "recovered cannot exceed affected"
    )
    if data["affected_unit_count"] == 0:
        assert data["effectiveness_pct"] == 0, "effectiveness_pct is 0 when no affected units"
    assert data["total_refund_cents"] >= 0


def assert_affected_lot(data: dict):
    # Append-only junction: id + created_at only — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["unit_count_snapshot"], int) and data["unit_count_snapshot"] >= 0


def assert_quarantine_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["lot_id"])
    assert data["status"] in ("ACTIVE", "LIFTED"), data["status"]
    assert isinstance(data["lifted_count"], int) and data["lifted_count"] >= 0


def assert_notification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in ("QUEUED", "SENT", "ACKNOWLEDGED", "FAILED"), data["status"]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_disposition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recall_id"])
    assert is_valid_uuid(data["unit_id"])
    assert data["disposition_type"] in ("RETURN", "REPLACE", "REFUND"), data["disposition_type"]
    assert data["logistics_status"] in (
        "PENDING", "RETURNED", "REPLACED", "CANCELLED",
    ), data["logistics_status"]
    assert data["financial_status"] in (
        "NOT_OWED", "OWED", "REFUNDED", "VOID",
    ), data["financial_status"]
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0


def assert_regulatory_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recall_id"])
    assert data["report_kind"] in ("INITIAL", "FOLLOWUP", "FINAL"), data["report_kind"]
    assert data["status"] in ("DRAFTED", "SUBMITTED", "ACKNOWLEDGED"), data["status"]


def assert_effectiveness_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recall_id"])
    assert isinstance(data["target_pct"], (int, float))
    assert isinstance(data["measured_pct"], (int, float))
    assert data["outcome"] in ("PASS", "FAIL"), data["outcome"]
