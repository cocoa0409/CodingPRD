"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --- generic helpers ---------------------------------------------------------


def _assert_common_fields(data: Dict[str, Any], *, versioned: bool = True) -> None:
    """PRD §2.5 common system-managed fields.

    versioned=True for primary resources (id, created_at, updated_at, version);
    versioned=False for append-only events (only id + created_at present).
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an int >= 1, got {data.get('version')!r}"
        )
    else:
        assert "updated_at" not in data, "append-only event must not expose updated_at"
        assert "version" not in data, "append-only event must not expose version"


def _assert_iso_date(value: str, field: str) -> None:
    assert isinstance(value, str) and len(value) == 10, (
        f"{field} must be an ISO date string (YYYY-MM-DD), got {value!r}"
    )
    y, m, d = value.split("-")
    assert y.isdigit() and m.isdigit() and d.isdigit(), f"{field} malformed: {value!r}"


# --- per-entity assertions ---------------------------------------------------


def assert_product(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["product_form"] in ("COATED", "BONDED", "NONWOVEN")
    assert isinstance(data["max_operating_speed_rpm"], int)
    assert data["max_operating_speed_rpm"] >= 1
    assert data["shelf_life_policy"] in ("EXACT_DAY", "END_OF_MONTH")
    assert data["used_media_hazard_class"] in ("NONE", "METAL_SWARF", "OIL_CONTAMINATED")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_machine(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert isinstance(data["customer_ref"], str)
    assert isinstance(data["asset_tag"], str)
    assert isinstance(data["machine_type"], str)
    assert isinstance(data["spindle_max_rpm"], int) and data["spindle_max_rpm"] >= 1
    assert data["guard_type"] in ("FIXED", "ADJUSTABLE", "NONE")
    assert data["status"] in ("ACTIVE", "QUARANTINED")
    assert data["consumption_flag"] in ("NORMAL", "ELEVATED")


def assert_lot(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["lot_code"], str)
    _assert_iso_date(data["manufacture_date"], "manufacture_date")
    assert isinstance(data["qty_received"], int) and data["qty_received"] >= 1
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    if data.get("expiry_date") is not None:
        _assert_iso_date(data["expiry_date"], "expiry_date")
    assert data["status"] in ("AVAILABLE", "BLOCKED", "EXPIRED", "DEPLETED")


def assert_standard(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["operation_name"], str)
    assert isinstance(data["standard_qty_per_part"], (int, float))
    assert data["standard_qty_per_part"] > 0
    _assert_iso_date(data["effective_from"], "effective_from")
    if data.get("effective_to") is not None:
        _assert_iso_date(data["effective_to"], "effective_to")
    assert isinstance(data["needs_review"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_usage_record(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=False)
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["lot_id"])
    _assert_iso_date(data["usage_date"], "usage_date")
    assert isinstance(data["qty_used"], int) and data["qty_used"] >= 1
    assert isinstance(data["parts_produced"], int) and data["parts_produced"] >= 1
    assert isinstance(data["actual_qty_per_part"], (int, float))
    assert isinstance(data["variance_pct"], (int, float))
    assert data["variance_band"] in ("UNDER", "IN_BAND", "OVER")


def assert_contract(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert isinstance(data["customer_ref"], str)
    assert isinstance(data["contract_number"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    _assert_iso_date(data["term_start"], "term_start")
    _assert_iso_date(data["term_end"], "term_end")
    _assert_iso_date(data["price_hold_end"], "price_hold_end")
    assert isinstance(data["escalation_pct"], (int, float)) and data["escalation_pct"] >= 0
    _assert_iso_date(data["escalation_effective_date"], "escalation_effective_date")


def assert_contract_line(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["base_unit_price_cents"], int) and data["base_unit_price_cents"] >= 1
    assert isinstance(data["current_unit_price_cents"], int)


def assert_blanket_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["committed_qty"], int) and data["committed_qty"] >= 1
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "CANCELLED")
    assert data["substitution_status"] in ("NONE", "PENDING", "ACCEPTED")


def assert_release(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert is_valid_uuid(data["blanket_order_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    _assert_iso_date(data["scheduled_ship_date"], "scheduled_ship_date")
    assert isinstance(data.get("allocations"), list)
    assert data["status"] in ("SCHEDULED", "ON_HOLD", "PICKED", "SHIPPED", "CANCELLED")


def assert_trial(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=True)
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["product_id"])
    _assert_iso_date(data["scheduled_start"], "scheduled_start")
    _assert_iso_date(data["scheduled_end"], "scheduled_end")
    assert data["status"] in ("ACTIVE", "EVALUATION", "CONVERTED", "REJECTED")


def assert_disposal_record(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, versioned=False)
    assert isinstance(data["customer_ref"], str)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["qty_disposed"], int) and data["qty_disposed"] >= 1
    assert isinstance(data["gross_weight_kg"], (int, float)) and data["gross_weight_kg"] > 0
    assert data["disposal_method"] in (
        "RECYCLING",
        "INCINERATION",
        "LANDFILL",
        "HAZARDOUS_WASTE_FACILITY",
    )
    _assert_iso_date(data["disposed_at"], "disposed_at")


# --- domain invariant checkers -----------------------------------------------


def assert_allocations_shape(allocations: List[Dict[str, Any]]) -> None:
    """Each allocation line is {lot_id, qty}; ordering is allocation order (PRD §3.7)."""
    assert isinstance(allocations, list)
    for line in allocations:
        assert set(line.keys()) >= {"lot_id", "qty"}, f"allocation line keys: {line.keys()!r}"
        assert is_valid_uuid(line["lot_id"])
        assert isinstance(line["qty"], int) and line["qty"] >= 1
