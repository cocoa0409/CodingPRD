"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start >= 1, got {data['version']}"


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_name"], str) and len(data["customer_name"]) > 0
    assert isinstance(data["customer_user_id"], str) and len(data["customer_user_id"]) > 0
    assert data["service_tier"] in ["BASIC", "PLUS", "PREMIUM"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["route_day"] in ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["alive_livestock_count"], int)
    assert data["alive_livestock_count"] >= 0


def assert_system(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["system_kind"] in ["REEF", "FRESHWATER", "POND", "PALUDARIUM"]
    assert data["nominal_volume_l"] > 0
    assert 0 <= data["substrate_displacement_pct"] < 1
    assert data["status"] in ["PROVISIONING", "ACTIVE", "SUSPENDED", "DECOMMISSIONED"]
    assert data["stocking_posture"] in ["NORMAL", "OVERSTOCKED"]


def assert_livestock(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["common_name"], str) and len(data["common_name"]) > 0
    assert data["species_class"] in ["COMMUNITY", "CICHLID", "GOLDFISH", "PREDATOR", "INVERT"]
    assert data["adult_length_cm"] > 0
    assert data["status"] in ["ALIVE", "QUARANTINED", "DECEASED"]


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert data["device_kind"] in ["FILTER", "PUMP", "HEATER", "UV_STERILIZER", "SKIMMER"]
    assert data["media_interval_days"] >= 1
    assert data["status"] in ["OPERATIONAL", "DEGRADED", "OUT_OF_SERVICE"]


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["tech_user_id"], str) and len(data["tech_user_id"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["certified_for_reef"], bool)
    assert isinstance(data["active"], bool)


def assert_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert isinstance(data["technician_id"], str)
    assert data["visit_kind"] in ["ROUTINE", "EMERGENCY"]
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "DISPUTED", "CANCELLED"]
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0


def assert_water_test(data: dict):
    """WaterTest is immutable: only id and created_at; no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "WaterTest must not carry a version field"
    assert "updated_at" not in data, "WaterTest must not carry an updated_at field"
    assert data["parameter"] in ["ALKALINITY", "NITRATE", "PHOSPHATE", "PH", "AMMONIA"]
    assert data["measured_value"] >= 0
    assert data["target_value"] >= 0
    assert data["product_strength_ppm_per_ml"] > 0
    assert data["recommended_dose_ml"] >= 0.0


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["source_kind"] in ["VISIT", "INSTALL", "EMERGENCY_TRIP"]
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert data["amount_paid_cents"] <= data["total_cents"]
    assert data["status"] in ["ISSUED", "OVERDUE", "PAID", "VOID"]


def assert_install(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["system_id"], str)
    assert data["status"] in ["QUOTED", "APPROVED", "IN_BUILD", "HANDED_OFF", "CANCELLED"]
    assert isinstance(data["labor_estimate_cents"], int) and data["labor_estimate_cents"] >= 0
    assert isinstance(data["equipment_estimate_cents"], int) and data["equipment_estimate_cents"] >= 0


def assert_emergency(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert data["severity"] in ["LOW", "HIGH", "CRITICAL"]
    assert isinstance(data["trip_fee_cents"], int) and data["trip_fee_cents"] >= 0
    assert data["status"] in ["OPEN", "DISPATCHED", "RESOLVED", "CANCELLED"]


def assert_repair(data: dict):
    _assert_common(data)
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["reported_symptom"], str) and len(data["reported_symptom"]) > 0
    assert isinstance(data["parts_needed"], bool)
    assert data["status"] in ["REPORTED", "DIAGNOSED", "AWAITING_PARTS", "CLOSED", "SCRAPPED"]


def assert_quarantine(data: dict):
    _assert_common(data)
    assert isinstance(data["livestock_id"], str)
    assert isinstance(data["quarantine_tank_id"], str)
    assert data["status"] in ["ACTIVE", "CLEARED", "ABORTED"]


def assert_feeding_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["system_id"], str)
    assert 1 <= data["feedings_per_day"] <= 6
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"]
