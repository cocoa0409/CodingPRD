"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.11)."""
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional seconds."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_instant_equals(actual: str, expected: str):
    """Two ISO 8601 strings denote the same instant (serialization may differ
    in fractional-second padding)."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """Primary-resource system properties (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict):
    """Append-only sub-resources carry only id and created_at (PRD §2.4):
    neither updated_at nor version exists on them."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only resource must not expose updated_at"
    assert "version" not in data, "append-only resource must not expose version"


def assert_price_config(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["is_current"], bool)


def assert_variety_config(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_field(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert data["maturity_state"] in ("SEEDED", "GROWING", "READY", "MATURE", "OVERAGED")
    assert data["field_sqft"] > 0


def assert_reseed_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNING", "IN_PROGRESS", "COMPLETED")


def assert_harvest_batch(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "COMPLETE", "CANCELLED")
    assert data["grade"] in ("PREMIUM", "STANDARD", "ECONOMY")
    assert data["pallet_count"] >= 1


def assert_customer(data: dict):
    assert_common_fields(data)
    assert data["freight_zone"] in (1, 2, 3)


def assert_crew(data: dict):
    assert_common_fields(data)
    assert isinstance(data["active"], bool)
    assert all(z in (1, 2, 3) for z in data["service_zones"])


def assert_quote(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACCEPTED", "SUPERSEDED", "EXPIRED")
    assert data["settlement_method"] in ("CARD", "CASH_CHECK")
    assert data["volume_tier"] in ("T0", "T1", "T2")


def assert_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PLACED", "CONFIRMED", "OUT_FOR_DELIVERY", "DELIVERED",
        "INSTALLING", "INSTALLED", "CLOSED", "CANCELLED",
    )
    assert data["payment_status"] in ("PENDING", "PAID")
    assert data["crew_referral_status"] in ("NONE", "CREW_REFERRED", "CREW_SCHEDULED")


def assert_payment(data: dict):
    assert_append_only_fields(data)
    assert data["method"] in ("CHECK", "CARD")


def assert_delivery_check(data: dict):
    assert_append_only_fields(data)
    assert data["check_index"] in (1, 2)
    assert isinstance(data["in_window"], bool)
    assert isinstance(data["strict_in_window"], bool)


def assert_crew_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REFERRED", "SCHEDULED", "REPLACED")


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "COMPLIANT", "INSUFFICIENT")
    assert data["resolution"] in ("NONE", "CREDIT_ISSUED", "REJECTED")
    assert data["weather_case"] in ("W1", "W2", "W3")


def assert_watering_log(data: dict):
    assert_append_only_fields(data)
    assert data["credits_awarded"] in (140, 120, 60)


def assert_truck_block(data: dict):
    assert_common_fields(data)
    assert data["freight_zone"] in (1, 2, 3)


def assert_money_eq(actual, expected, label="amount"):
    """Money is rounded half-up to exactly two decimal places (PRD §2.6)."""
    assert actual == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_order_books_balance(order: dict):
    """Conserved quantity (PRD §3.7): total_paid + amount_due - credit_balance
    == chargeable_amount at every moment."""
    lhs = order["total_paid"] + order["amount_due"] - order["credit_balance"]
    assert lhs == pytest.approx(order["chargeable_amount"], abs=0.001), (
        f"books unbalanced: {order['total_paid']} + {order['amount_due']} "
        f"- {order['credit_balance']} != {order['chargeable_amount']}"
    )


def assert_field_area_conserved(field: dict, completed_sellable_sqft: float):
    """Conserved quantity (PRD §2.11): remaining_sqft + sellable_sqft of
    non-cancelled completed batches this cycle == field_sqft."""
    assert field["remaining_sqft"] + completed_sellable_sqft == pytest.approx(
        field["field_sqft"], abs=0.001
    ), (
        f"field area not conserved: {field['remaining_sqft']} + "
        f"{completed_sellable_sqft} != {field['field_sqft']}"
    )
