"""Per-entity assertions and domain invariant checkers.

Each ``assert_<entity>`` checks the identity/timestamp shape PRD §2.4 requires
plus the field types PRD §3 declares for that resource.
"""

from typing import Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CaseModelStatus,
    ClaimType,
    ComplianceLabelStatus,
    CommercialStatus,
    DoorType,
    EndCap,
    EnergyTestStatus,
    InstallBookingStatus,
    ProductionStatus,
    SafetyClass,
    ShipmentStatus,
    SystemType,
    TemperatureClass,
    WarrantyClaimStatus,
    WorkOrderStatus,
)

_TEMPERATURE_CLASSES = [c.value for c in TemperatureClass]
_SYSTEM_TYPES = [s.value for s in SystemType]


def _assert_identity(data: Dict) -> None:
    """PRD §2.4: every persisted resource carries a UUID `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"


def _assert_revisioned(data: Dict) -> None:
    """PRD §2.4: mutable resources also carry `updated_at` and a `version`."""
    _assert_identity(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_reference_data_has_no_revision_fields(data: Dict) -> None:
    """PRD §2.4: refrigerants and energy standards have no `updated_at`/`version`."""
    assert "updated_at" not in data, "reference data must not expose updated_at"
    assert "version" not in data, "reference data must not expose version"


def assert_refrigerant(data: Dict) -> None:
    _assert_identity(data)
    assert_reference_data_has_no_revision_fields(data)
    assert isinstance(data["refrigerant_code"], str) and data["refrigerant_code"]
    assert isinstance(data["trade_name"], str) and data["trade_name"]
    assert isinstance(data["gwp_100yr"], int) and data["gwp_100yr"] >= 1
    assert data["safety_class"] in [s.value for s in SafetyClass]
    assert isinstance(data["max_charge_grams"], int) and data["max_charge_grams"] >= 1
    assert isinstance(data["allowed_system_types"], list) and data["allowed_system_types"]
    for system_type in data["allowed_system_types"]:
        assert system_type in _SYSTEM_TYPES


def assert_energy_standard(data: Dict) -> None:
    _assert_identity(data)
    assert_reference_data_has_no_revision_fields(data)
    assert isinstance(data["standard_code"], str) and 0 < len(data["standard_code"]) <= 48
    assert isinstance(data["effective_date"], str) and data["effective_date"]
    assert isinstance(data["max_gwp"], int)
    assert data["limit_coefficient_a"] > 0
    assert data["limit_constant_b"] >= 0
    assert data["temperature_class"] in _TEMPERATURE_CLASSES
    assert data["system_type_scope"] in _SYSTEM_TYPES + ["ANY"]


def assert_test_chamber(data: Dict) -> None:
    _assert_revisioned(data)
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert (
        isinstance(data["supported_temperature_classes"], list)
        and data["supported_temperature_classes"]
    )
    for temperature_class in data["supported_temperature_classes"]:
        assert temperature_class in _TEMPERATURE_CLASSES
    assert isinstance(data["turnaround_hours"], int) and data["turnaround_hours"] >= 0
    assert data["max_tda_sqft"] > 0


def assert_case_model(data: Dict) -> None:
    _assert_revisioned(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["temperature_class"] in _TEMPERATURE_CLASSES
    assert data["system_type"] in _SYSTEM_TYPES
    assert is_valid_uuid(data["refrigerant_id"])
    assert data["nominal_length_ft"] in [4, 6, 8, 12]
    assert data["tda_sqft"] > 0
    assert isinstance(data["charge_grams"], int) and data["charge_grams"] >= 1
    assert isinstance(data["line_set_length_ft"], int) and data["line_set_length_ft"] >= 0
    assert data["door_type"] in [d.value for d in DoorType]
    assert isinstance(data["glass_door_count"], int) and data["glass_door_count"] >= 0
    assert isinstance(data["curtain_layers"], int) and data["curtain_layers"] >= 1
    assert data["discharge_velocity_mps"] > 0
    assert data["lighting_w_per_ft"] >= 0
    assert data["fan_w_per_ft"] >= 0
    assert (
        isinstance(data["defrost_cycles_per_day"], int)
        and data["defrost_cycles_per_day"] >= 0
    )
    assert data["status"] in [s.value for s in CaseModelStatus]
    assert isinstance(data["design_revision"], int) and data["design_revision"] >= 1


def assert_case_model_load_fields_absent(data: Dict) -> None:
    """PRD §3.2: computed airflow and charge fields are absent on a fresh design."""
    for field in (
        "curtain_factor",
        "velocity_factor",
        "infiltration_load_w",
        "lighting_load_w",
        "fan_load_w",
        "defrost_load_w",
        "anti_sweat_load_w",
        "total_design_load_w",
        "installed_charge_grams",
        "nameplate_co2e_kg",
        "installed_co2e_kg",
    ):
        assert data.get(field) is None, f"{field} must be absent, got {data.get(field)!r}"


def assert_energy_test(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["case_model_id"])
    assert is_valid_uuid(data["test_chamber_id"])
    assert is_valid_uuid(data["energy_standard_id"])
    assert data["status"] in [s.value for s in EnergyTestStatus]
    assert isinstance(data["pinned_design_revision"], int)
    assert data["pinned_tda_sqft"] > 0
    assert isinstance(data["pinned_defrost_cycles_per_day"], int)
    assert data["limit_daily_kwh"] >= 0


def assert_compliance_label(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["case_model_id"])
    assert is_valid_uuid(data["energy_test_id"])
    assert isinstance(data["label_code"], str) and data["label_code"]
    assert data["label_status"] in [s.value for s in ComplianceLabelStatus]
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert isinstance(data["pinned_design_revision"], int)
    assert isinstance(data["pinned_standard_code"], str) and data["pinned_standard_code"]


def assert_store_plan(data: Dict) -> None:
    _assert_revisioned(data)
    assert isinstance(data["banner_name"], str) and data["banner_name"]
    assert isinstance(data["store_number"], str) and data["store_number"]
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert data["commercial_status"] in [s.value for s in CommercialStatus]
    assert data["production_status"] in [s.value for s in ProductionStatus]
    for counter in (
        "line_count",
        "unit_count",
        "held_line_count",
        "units_completed_count",
        "units_shipped_count",
        "warranty_reserve_accrual_cents",
        "warranty_reserve_incurred_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must not be negative"
    assert isinstance(data["credit_limit_cents"], int)


def assert_store_plan_line(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["store_plan_id"])
    assert is_valid_uuid(data["case_model_id"])
    assert data["length_ft"] in [4, 6, 8, 12]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["end_cap"] in [e.value for e in EndCap]
    assert isinstance(data["merchandising_options"], list)
    assert isinstance(data["compliance_hold"], bool)


def assert_work_order(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["store_plan_id"])
    assert is_valid_uuid(data["store_plan_line_id"])
    assert is_valid_uuid(data["case_model_id"])
    assert isinstance(data["unit_sequence"], int) and data["unit_sequence"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["status"] in [s.value for s in WorkOrderStatus]


def assert_shipment(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["store_plan_id"])
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert data["status"] in [s.value for s in ShipmentStatus]
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 0
    assert isinstance(data["linear_feet"], int) and data["linear_feet"] >= 0


def assert_install_crew(data: Dict) -> None:
    _assert_revisioned(data)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["contractor_name"], str) and data["contractor_name"]
    assert isinstance(data["service_region_codes"], list) and data["service_region_codes"]
    assert (
        isinstance(data["daily_case_capacity"], int) and data["daily_case_capacity"] >= 1
    )
    assert isinstance(data["committed_case_days"], int)
    assert data["committed_case_days"] >= 0, "committed_case_days must not go negative"


def assert_install_booking(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["shipment_id"])
    assert is_valid_uuid(data["install_crew_id"])
    assert isinstance(data["cases_committed"], int) and data["cases_committed"] >= 1
    assert isinstance(data["day_count"], int) and data["day_count"] >= 1
    assert data["status"] in [s.value for s in InstallBookingStatus]


def assert_part_inventory(data: Dict) -> None:
    _assert_revisioned(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert is_valid_uuid(data["case_model_id"])
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["min_stock_qty"], int) and data["min_stock_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["below_min"], bool)
    assert_depot_stock_invariants(data)


def assert_depot_stock_invariants(data: Dict) -> None:
    """PRD §3.1/§3.9 depot arithmetic: available = on_hand - reserved; below_min flag."""
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"], (
        "available_qty must equal on_hand_qty less reserved_qty, got "
        f"{data['available_qty']} for {data['on_hand_qty']}/{data['reserved_qty']}"
    )
    assert data["below_min"] is (data["available_qty"] < data["min_stock_qty"]), (
        "below_min must be true exactly when available_qty is below min_stock_qty"
    )


def assert_warranty_claim(data: Dict) -> None:
    _assert_revisioned(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["part_inventory_id"])
    assert is_valid_uuid(data["install_crew_id"])
    assert data["claim_type"] in [c.value for c in ClaimType]
    assert isinstance(data["requested_qty"], int) and data["requested_qty"] >= 1
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in [s.value for s in WarrantyClaimStatus]
    assert isinstance(data["warranty_term_months"], int)
    assert isinstance(data["in_warranty"], bool)


def assert_pricing_waterfall(data: Dict) -> None:
    """PRD §3.6 six-step roll-up self-consistency on a priced plan."""
    assert data["net_cents"] == data["subtotal_cents"] - data["volume_discount_cents"], (
        "net_cents must equal subtotal_cents less volume_discount_cents"
    )
    assert (
        data["total_cents"]
        == data["net_cents"] + data["freight_cents"] + data["install_allowance_cents"]
    ), "total_cents must equal net plus freight plus install allowance"
    for field in (
        "subtotal_cents",
        "volume_discount_bps",
        "volume_discount_cents",
        "net_cents",
        "freight_cents",
        "install_allowance_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_pricing_cleared(data: Dict) -> None:
    """PRD §3.6: adding a line to a priced plan clears the whole quote."""
    for field in (
        "subtotal_cents",
        "volume_discount_bps",
        "volume_discount_cents",
        "net_cents",
        "freight_cents",
        "install_allowance_cents",
        "total_cents",
        "priced_by_user_id",
    ):
        assert data.get(field) is None, f"{field} must be cleared, got {data.get(field)!r}"


def _normalize_instant(value: str) -> str:
    """Drop fractional-second padding so two ISO 8601 UTC instants compare equal."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
        text = f"{whole}.{fraction}" if fraction else whole
    return text


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """PRD §2.4 renders instants in ISO 8601 UTC; compare them modulo padding."""
    assert isinstance(actual, str), f"{label} must be an ISO 8601 string, got {actual!r}"
    assert _normalize_instant(actual) == _normalize_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_version_is(data: Dict, expected: int, label: str = "row") -> None:
    assert data["version"] == expected, (
        f"{label} version should be {expected}, got {data['version']}"
    )
