"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9)."""
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str, label="instant"):
    """Compare two ISO 8601 instants by value, not by string representation
    (the PRD pins the instant, not its rendering)."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict):
    """PRD §2.4 standard system-managed fields present with correct types."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_kg(actual, expected, label="weight"):
    """Two-decimal kilogram comparison tolerant of JSON float representation."""
    assert actual == pytest.approx(expected, abs=1e-6), (
        f"{label}: expected {expected} kg, got {actual}"
    )


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------

def assert_vessel(data: dict):
    assert_common_fields(data)
    assert isinstance(data["vessel_name"], str) and data["vessel_name"]
    assert isinstance(data["registration_number"], str) and data["registration_number"]
    assert isinstance(data["home_port"], str) and data["home_port"]
    assert isinstance(data["payable_balance_cents"], int)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["credit_exposure_cents"], int)


def assert_catch_area(data: dict):
    assert_common_fields(data)
    assert isinstance(data["fao_code"], str) and data["fao_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str)


def assert_species(data: dict):
    assert_common_fields(data)
    assert isinstance(data["species_code"], str) and data["species_code"]
    assert isinstance(data["common_name"], str)
    assert isinstance(data["labeling_name"], str)
    assert isinstance(data["substitution_group"], str)
    assert isinstance(data["is_import"], bool)
    assert isinstance(data["requires_cites"], bool)
    assert isinstance(data["fresh_shelf_life_hours"], int)
    assert isinstance(data["frozen_shelf_life_days"], int)


def assert_market_quote(data: dict):
    assert_common_fields(data)
    assert data["grade"] in ("GRADE_A", "GRADE_B", "GRADE_C")
    assert isinstance(data["quote_date"], str)
    assert isinstance(data["price_per_kg_cents"], int)
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "PUBLISHED", "SUPERSEDED", "EXPIRED")


def assert_dock_ticket(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "LANDED", "GRADED", "SETTLED", "PAID", "VOIDED")
    assert isinstance(data["regrade_count"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)


def assert_landing_line(data: dict):
    assert_common_fields(data)
    assert data["declared_grade"] in ("GRADE_A", "GRADE_B", "GRADE_C")
    assert data["processing_type"] in ("WHOLE", "FILLETED")
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["final_amount_cents"], int)
    assert isinstance(data["voided"], bool)


def assert_grade_assessment(data: dict):
    assert_common_fields(data)
    assert data["assessed_grade"] in ("GRADE_A", "GRADE_B", "GRADE_C")
    assert data["status"] in ("DRAFT", "FINAL", "SUPERSEDED")


def assert_inventory_lot(data: dict):
    assert_common_fields(data)
    assert data["storage_type"] in ("FRESH", "FROZEN")
    assert data["lifecycle_status"] in ("ACTIVE", "DEPLETED", "EXPIRED", "RECALLED")
    assert data["hold_status"] in ("CLEAR", "ON_HOLD", "CONDEMNED")
    for bucket in ("received_weight_kg", "available_weight_kg", "reserved_weight_kg",
                   "committed_weight_kg", "shipped_weight_kg", "condemned_weight_kg",
                   "spoiled_weight_kg", "recalled_weight_kg"):
        assert isinstance(data[bucket], (int, float)), f"{bucket} must be numeric"
    assert isinstance(data["unit_cost_cents"], int)


def assert_sales_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CONFIRMED", "FULFILLED", "INVOICED", "CANCELLED")
    assert isinstance(data["total_cents"], int)


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert data["requested_grade"] in ("GRADE_A", "GRADE_B", "GRADE_C")
    assert isinstance(data["allow_substitution"], bool)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)


def assert_allocation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")
    assert isinstance(data["transit_hours"], int)


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert data["mode"] in ("AIR", "TRUCK")
    assert data["temp_zone"] in ("CHILLED", "FROZEN")
    assert data["status"] in ("QUOTED", "BOOKED", "TENDERED", "IN_TRANSIT", "DELIVERED", "CANCELLED")
    assert isinstance(data["provisional_freight_cents"], int)
    assert isinstance(data["final_freight_cents"], int)


def assert_import_document(data: dict):
    assert_common_fields(data)
    assert data["doc_type"] in ("HEALTH_CERT", "CITES", "CUSTOMS_ENTRY")
    assert data["status"] in ("DRAFT", "SUBMITTED", "CLEARED", "REJECTED")
    assert isinstance(data["resubmit_count"], int)


def assert_inspection_hold(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLACED", "RELEASED", "CONDEMNED")


def assert_substitution_approval(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "APPLIED")
    assert isinstance(data["auto_created"], bool)
    assert isinstance(data["price_credit_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_lot_weight_conservation(lot: dict):
    """PRD §2.9: the seven weight buckets account for the received weight —
    every workflow moves weight between buckets without creating or losing it.
    Lots are born with available == received and all other buckets at zero (§3.4),
    so at every observable point the buckets sum back to received."""
    received = lot["received_weight_kg"]
    total = (
        lot["available_weight_kg"] + lot["reserved_weight_kg"]
        + lot["committed_weight_kg"] + lot["shipped_weight_kg"]
        + lot["condemned_weight_kg"] + lot["spoiled_weight_kg"]
        + lot["recalled_weight_kg"]
    )
    assert total == pytest.approx(received, abs=1e-6), (
        f"Lot {lot.get('id')} bucket sum {total} != received {received}"
    )


def assert_lot_buckets(lot: dict, available=None, reserved=None, committed=None,
                       shipped=None, condemned=None, spoiled=None, recalled=None,
                       received=None):
    """Pin individual lot buckets (kg, 2dp) where the workflow requires it."""
    checks = {
        "available_weight_kg": available,
        "reserved_weight_kg": reserved,
        "committed_weight_kg": committed,
        "shipped_weight_kg": shipped,
        "condemned_weight_kg": condemned,
        "spoiled_weight_kg": spoiled,
        "recalled_weight_kg": recalled,
        "received_weight_kg": received,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert_kg(lot[field], expected, label=field)
