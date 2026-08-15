"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every resource carries id/created_at/updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}")


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str):
    """Compare two ISO-8601 UTC instants regardless of fractional-digit rendering."""
    assert isinstance(actual, str), f"expected an ISO timestamp string, got {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_rate_card(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["storage_method"] in ("DAILY_PRORATED", "FULL_MONTH")
    assert isinstance(data["frozen_storage_cents_per_pallet_month"], int)
    assert isinstance(data["chilled_storage_cents_per_pallet_month"], int)
    assert isinstance(data["handling_in_cents_per_pallet"], int)
    assert isinstance(data["handling_out_cents_per_pallet"], int)
    assert isinstance(data["blast_base_cents"], int)
    assert isinstance(data["blast_per_pallet_cents"], int)
    assert data["liability_model"] in ("DECLARED_VALUE", "LIMITED_LIABILITY")
    assert isinstance(data["liability_per_pallet_cents"], int)
    assert isinstance(data["dwell_exempt"], bool)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["temp_class"] in ("FROZEN", "CHILLED")
    assert isinstance(data["capacity_pallets"], int) and data["capacity_pallets"] >= 1
    assert isinstance(data["dock_doors"], int) and data["dock_doors"] >= 1
    assert isinstance(data["in_use_pallets"], int) and data["in_use_pallets"] >= 0
    assert isinstance(data["reserved_pallets"], int) and data["reserved_pallets"] >= 0
    assert isinstance(data["free_pallets"], int)
    assert data["posture"] in ("OPEN", "TIGHT", "FULL")


def assert_receipt(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["production_date"], str) and data["production_date"]
    assert data["temp_class"] in ("FROZEN", "CHILLED")
    assert isinstance(data["expected_pallets"], int) and data["expected_pallets"] >= 1
    assert data["status"] in ("SCHEDULED", "ARRIVED", "COMPLETED", "CANCELLED")


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["on_hand_pallets"], int) and data["on_hand_pallets"] >= 0
    assert data["status"] in (
        "AVAILABLE", "PARTIAL_HOLD", "FULL_HOLD", "DEPLETED", "RECALLED")


def assert_pallet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["receipt_id"])
    assert is_valid_uuid(data["zone_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in (
        "STORED", "IN_BLAST_FREEZE", "ALLOCATED", "SHIPPED", "DISPOSITIONED")
    assert data["quality"] in ("OK", "QUARANTINED", "RECALLED")
    assert is_iso8601_timestamp(data["received_at"])


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["requested_pallets"], int) and data["requested_pallets"] >= 1
    assert isinstance(data["allocated_pallets"], int) and data["allocated_pallets"] >= 0
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ALLOCATED", "SHORTED", "SHIPPED", "CANCELLED")


def assert_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["pallet_id"])
    assert is_valid_uuid(data["lot_id"])
    assert data["status"] in ("ACTIVE", "RELEASED", "FULFILLED")


def assert_blast_cell(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cell_code"], str) and data["cell_code"]
    assert isinstance(data["capacity_pallets"], int) and data["capacity_pallets"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0


def assert_blast_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cell_id"])
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["pallet_count"], int) and data["pallet_count"] >= 1
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_excursion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["zone_id"])
    assert isinstance(data["observed_temp_c"], (int, float))
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert isinstance(data["quarantined_pallet_count"], int)
    assert data["quarantined_pallet_count"] >= 0
    assert data["status"] in ("REPORTED", "CONFIRMED_BREACH", "CLEARED")


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["reason"], str)
    assert data["status"] in ("DECLARED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["excursion_id"])
    assert isinstance(data["affected_pallet_count"], int)
    assert data["affected_pallet_count"] >= 1
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] > 0
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "REOPENED", "SETTLED", "WITHDRAWN")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in ("OPEN", "FINALIZED", "DISPUTED", "SETTLED")
    for field in ("storage_cents", "handling_in_cents", "handling_out_cents",
                  "blast_freeze_cents", "dwell_surcharge_cents", "claim_credit_cents",
                  "total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_invoice_total_invariant(data: dict):
    """total_cents is the plain sum of components minus claim credits (PRD §3.9)."""
    expected = (
        data["storage_cents"] + data["handling_in_cents"] + data["handling_out_cents"]
        + data["blast_freeze_cents"] + data["dwell_surcharge_cents"]
        - data["claim_credit_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != component sum {expected}")
