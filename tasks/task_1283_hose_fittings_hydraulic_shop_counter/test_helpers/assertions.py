"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_REEL_STATUSES = ["AVAILABLE", "LOW", "DEPLETED", "RETIRED"]
_ORDER_STATUSES = [
    "DRAFT", "CONFIRMED", "BUILT", "TEST_PASSED", "TEST_FAILED",
    "REWORK", "TAGGED", "COMPLETED", "CANCELLED",
]
_ASSET_STATUSES = ["ACTIVE", "DECOMMISSIONED"]
_POSTURES = ["COMPLIANT", "DUE_SOON", "OVERDUE", "NON_COMPLIANT"]
_PROGRAM_STATUSES = ["NONE", "ACTIVE", "PROBATION"]
_INSPECTION_STATUSES = ["SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "SUPERSEDED"]
_DISPATCH_STATUSES = ["REQUESTED", "DISPATCHED", "ON_SITE", "COMPLETED", "ABORTED"]
_TEST_RESULTS = ["PASSED", "FAILED"]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant (Z or offset form) into an aware datetime."""
    assert isinstance(value, str), f"expected ISO instant string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str):
    """Two timestamp strings denote the same instant, regardless of formatting."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_int(data: dict, field: str):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer, got {value!r}"
    )


def _assert_int_cents(data: dict, field: str):
    _assert_int(data, field)


def _assert_nullable_int(data: dict, field: str):
    value = data.get(field)
    assert value is None or (isinstance(value, int) and not isinstance(value, bool)), (
        f"{field} must be null or an integer, got {value!r}"
    )


def _assert_number(data: dict, field: str):
    value = data.get(field)
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["program_enrolled"], bool)
    _assert_number(data, "program_discount_pct")
    _assert_int(data, "inspection_interval_days")
    assert data["inspection_interval_days"] >= 1
    _assert_number(data, "compliance_score_strict")
    _assert_number(data, "compliance_score_projected")
    assert data["program_status"] in _PROGRAM_STATUSES


def assert_equipment_asset(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["asset_tag"], str)
    assert isinstance(data["machine_type"], str)
    assert data["status"] in _ASSET_STATUSES
    assert data["compliance_posture"] in _POSTURES
    for field in ("installed_at", "installed_assembly_order_id",
                  "last_passed_inspection_at", "next_due_date"):
        assert field in data, f"{field} must be present (null allowed)"
        assert data[field] is None or isinstance(data[field], str)


def assert_reel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hose_sku"], str)
    _assert_number(data, "hose_diameter_in")
    _assert_int(data, "working_pressure_psi")
    _assert_int_cents(data, "price_per_meter_cents")
    _assert_int(data, "initial_length_mm")
    assert data["initial_length_mm"] >= 1
    _assert_int(data, "remaining_length_mm")
    assert data["remaining_length_mm"] >= 0
    _assert_int(data, "scrap_length_mm")
    assert data["scrap_length_mm"] >= 0
    assert data["status"] in _REEL_STATUSES


def assert_coupling(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["coupling_sku"], str)
    _assert_number(data, "size_in")
    _assert_int_cents(data, "unit_price_cents")
    _assert_int(data, "initial_on_hand_qty")
    _assert_int(data, "on_hand_qty")
    _assert_int(data, "reserved_qty")
    _assert_int(data, "available_qty")
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        "available_qty must equal on_hand_qty - reserved_qty"
    )


def assert_assembly_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["reel_id"], str)
    assert "equipment_asset_id" in data
    assert data["equipment_asset_id"] is None or isinstance(data["equipment_asset_id"], str)
    _assert_int(data, "cut_length_mm")
    assert data["cut_length_mm"] >= 1
    _assert_int(data, "required_working_pressure_psi")
    _assert_number(data, "crimp_diameter_spec_mm")
    _assert_number(data, "crimp_tolerance_mm")
    _assert_int(data, "crimp_count")
    _assert_int(data, "estimated_labor_minutes")
    assert isinstance(data["is_emergency"], bool)
    assert isinstance(data["application_error_suspected"], bool)
    assert isinstance(data["waiver_signed"], bool)
    assert data.get("waiver_signed_by") is None or isinstance(data["waiver_signed_by"], str)
    _assert_nullable_int(data, "waiver_liability_cents")
    assert data.get("measured_crimp_diameter_mm") is None or isinstance(
        data["measured_crimp_diameter_mm"], (int, float))
    _assert_nullable_int(data, "actual_labor_minutes")
    _assert_nullable_int(data, "test_pressure_psi")
    assert data.get("test_result") is None or data["test_result"] in _TEST_RESULTS
    assert data.get("tag_serial") is None or isinstance(data["tag_serial"], str)
    _assert_int(data, "scrap_charged_mm")
    assert data["status"] in _ORDER_STATUSES
    _assert_int_cents(data, "material_hose_cents")
    _assert_int_cents(data, "material_couplings_cents")
    _assert_int_cents(data, "waste_surcharge_cents")
    _assert_int_cents(data, "quoted_total_cents")
    _assert_nullable_int(data, "final_total_cents")


def assert_assembly_line(data: dict):
    # Append-only line: carries only id + created_at plus its own fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "lines must not carry updated_at"
    assert "version" not in data, "lines must not carry version"
    assert isinstance(data["assembly_order_id"], str)
    assert isinstance(data["coupling_id"], str)
    _assert_int(data, "quantity")
    assert data["quantity"] >= 1
    _assert_int_cents(data, "unit_price_cents")
    _assert_int_cents(data, "line_total_cents")
    assert data["line_total_cents"] == data["quantity"] * data["unit_price_cents"]


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["equipment_asset_id"], str)
    assert data.get("inspector_name") is None or isinstance(data["inspector_name"], str)
    assert isinstance(data["scheduled_window_start"], str)
    assert isinstance(data["scheduled_window_end"], str)
    assert data["status"] in _INSPECTION_STATUSES
    assert data.get("result") is None or data["result"] in _TEST_RESULTS
    assert data.get("performed_at") is None or isinstance(data["performed_at"], str)
    assert isinstance(data["was_overdue"], bool)


def assert_service_dispatch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["van_id"], str)
    assert data.get("equipment_asset_id") is None or isinstance(data["equipment_asset_id"], str)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in _DISPATCH_STATUSES
    assert data.get("installed_assembly_order_id") is None or isinstance(
        data["installed_assembly_order_id"], str)


def assert_reel_length_invariant(reel: dict, committed_cut_mm: int):
    """initial == remaining + scrap + cuts still committed on non-terminal orders."""
    assert reel["initial_length_mm"] == (
        reel["remaining_length_mm"] + reel["scrap_length_mm"] + committed_cut_mm
    ), (
        f"Reel length ledger broke: initial {reel['initial_length_mm']} != "
        f"remaining {reel['remaining_length_mm']} + scrap {reel['scrap_length_mm']} "
        f"+ committed {committed_cut_mm}"
    )
