"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_light_fields(data: dict):
    """PRD §2.4: immutable resources carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "immutable resource must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "immutable resource must not carry version (PRD §2.4)"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert data["credit_status"] in ("GOOD", "WATCH", "HOLD")
    assert isinstance(data["standby_contract"], bool)
    assert isinstance(data["sla_response_minutes"], int) and data["sla_response_minutes"] > 0
    discount = data["loyalty_discount_pct"]
    assert isinstance(discount, (int, float)) and 0 <= discount < 1


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["fuel_tank_capacity_liters"], int)
    assert data["fuel_tank_capacity_liters"] > 0
    level = data["tank_level_liters"]
    assert isinstance(level, (int, float)), "tank_level_liters must be numeric"
    assert 0 <= level <= data["fuel_tank_capacity_liters"], (
        "tank invariants: level never below zero and never above capacity (PRD §3.1)"
    )


def assert_equipment_unit(data: dict):
    _assert_common_fields(data)
    assert data["unit_type"] in ("GENERATOR", "CHILLER")
    assert isinstance(data["capacity_kw"], int) and data["capacity_kw"] > 0
    assert data["fuel_type"] in ("DIESEL", "NATURAL_GAS")
    assert data["emissions_tier"] in ("TIER_2", "TIER_4F")
    assert isinstance(data["nox_g_per_kwh"], (int, float)) and data["nox_g_per_kwh"] > 0
    for rate_field in ("day_rate_cents", "week_rate_cents", "month_rate_cents"):
        assert isinstance(data[rate_field], int) and data[rate_field] > 0
    assert isinstance(data["demob_fee_cents"], int) and data["demob_fee_cents"] >= 0
    assert isinstance(data["home_depot_code"], str) and data["home_depot_code"]
    assert data["status"] in (
        "AVAILABLE", "RESERVED", "DEPLOYED", "OFF_RENT", "QUARANTINED", "MAINTENANCE",
    )
    assert "current_site_id" in data
    assert isinstance(data["runtime_hours_total"], (int, float))
    assert isinstance(data["fuel_consumed_liters_total"], (int, float))


def assert_accessory_kit(data: dict):
    _assert_light_fields(data)
    assert isinstance(data["kit_code"], str) and data["kit_code"]
    assert isinstance(data["description"], str)
    assert isinstance(data["max_ampacity_a"], int) and data["max_ampacity_a"] > 0
    for rate_field in ("day_rate_cents", "week_rate_cents", "month_rate_cents"):
        assert isinstance(data[rate_field], int) and data[rate_field] > 0


def assert_rental_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["load_profile"], list)
    assert data["status"] in (
        "DRAFT", "QUOTED", "CONFIRMED", "MOBILIZING", "ON_RENT", "SUSPENDED",
        "OFF_HIRE", "CLOSED", "CANCELLED", "EXPIRED",
    )
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["expected_offhire_date"])
    for nullable in (
        "sizing_method", "sized_kw", "quoted_at", "quoted_total_cents",
        "on_rent_at", "actual_offhire_at", "invoice_total_cents",
    ):
        assert nullable in data, f"contract must carry {nullable} (null until filled, PRD §3.3)"


def assert_rental_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str)
    assert data["line_type"] in ("EQUIPMENT", "ACCESSORY_KIT")
    if data["line_type"] == "EQUIPMENT":
        assert isinstance(data["equipment_unit_id"], str)
        assert data["quantity"] == 1
    else:
        assert isinstance(data["accessory_kit_id"], str)
        assert data["quantity"] >= 1
        assert data["demob_fee_cents"] == 0, "demob fee is always 0 on kit lines (PRD §3.3)"
    for rate_field in ("day_rate_cents", "week_rate_cents", "month_rate_cents"):
        assert isinstance(data[rate_field], int) and data[rate_field] > 0
    assert isinstance(data["demob_fee_cents"], int) and data["demob_fee_cents"] >= 0
    assert data["status"] in ("PENDING", "ON_RENT", "OFF_HIRED", "RETURNED", "RELEASED")
    assert "final_charge_cents" in data
    assert "offhired_at" in data


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str)
    assert data["permit_type"] in ("EMISSIONS", "NOISE")
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["review_rounds"], int) and data["review_rounds"] >= 0
    assert "submitted_at" in data
    assert "decided_at" in data


def assert_service_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str)
    assert data["visit_type"] in ("TECHNICIAN", "FUEL_DELIVERY", "EMERGENCY")
    assert data["status"] in ("SCHEDULED", "DISPATCHED", "ON_SITE", "COMPLETED", "CANCELLED")
    for nullable in (
        "scheduled_start", "scheduled_end", "assigned_technician_id",
        "fuel_quantity_liters", "requested_at", "dispatched_at", "arrived_at",
        "response_minutes", "sla_met",
    ):
        assert nullable in data, f"visit must carry {nullable} (PRD §3.7)"


def assert_telemetry_event(data: dict):
    _assert_light_fields(data)
    assert isinstance(data["contract_id"], str)
    assert data["event_type"] in ("RUNTIME", "FUEL_BURN", "FUEL_DELIVERY", "FUEL_PUMP_OUT")
    assert isinstance(data["value"], (int, float)) and data["value"] > 0
    assert is_iso8601_timestamp(data["recorded_at"])
    if data["event_type"] in ("RUNTIME", "FUEL_BURN"):
        assert isinstance(data["equipment_unit_id"], str)
    else:
        assert data.get("equipment_unit_id") is None


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["equipment_unit_id"], str)
    assert data["incident_type"] in ("DAMAGE", "SPILL")
    if data["incident_type"] == "SPILL":
        assert isinstance(data["spill_volume_liters"], (int, float))
    assert data["status"] in ("REPORTED", "ASSESSED", "CHARGED", "WAIVED")
    assert "assessed_charge_cents" in data
    assert "assessed_by" in data


def assert_emissions_screening(data: dict):
    """PRD §3.5 computed read shape."""
    assert isinstance(data["aggregate_nox_g_per_kwh"], (int, float))
    assert isinstance(data["jurisdiction_cap_g_per_kwh"], (int, float))
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["input_unit_count"], int) and data["input_unit_count"] >= 0


def assert_fuel_projection(data: dict):
    """PRD §3.6 computed read shape."""
    assert data["method"] in ("RATED_CURVE", "METERED_AVG")
    assert isinstance(data["liters_per_hour"], (int, float))
    assert isinstance(data["projected_liters_per_day"], (int, float))
    assert isinstance(data["next_refuel_eta_hours"], (int, float))
    assert isinstance(data["telemetry_event_count"], int) and data["telemetry_event_count"] >= 0


def assert_tank_level(site: dict, expected_liters):
    """Domain invariant probe: the site's live computed tank level (PRD §3.1)."""
    actual = site["tank_level_liters"]
    assert abs(actual - expected_liters) < 1e-6, (
        f"Expected tank_level_liters == {expected_liters}, got {actual}"
    )
