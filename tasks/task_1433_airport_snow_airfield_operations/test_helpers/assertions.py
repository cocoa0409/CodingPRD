"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_snow_event(data: dict):
    _assert_common_fields(data, "SnowEvent")
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert isinstance(data["season_label"], str) and data["season_label"]
    assert isinstance(data["chemical_limit_lbs"], (int, float))
    assert isinstance(data["budget_cents"], int)
    assert data["status"] in [
        "FORECAST", "ACTIVATED", "ESCALATED", "STANDING_DOWN", "CLOSED",
    ]
    assert data["closure_status"] in ["NONE", "PROPOSED", "RATIFIED", "LIFTED"]
    assert isinstance(data["airline_acknowledged"], bool)
    assert data.get("activated_at") is None or is_iso8601_timestamp(
        data["activated_at"])
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["actual_cost_cents"], int)
    assert isinstance(data["chemical_used_lbs"], (int, float))


def assert_airfield_surface(data: dict):
    _assert_common_fields(data, "AirfieldSurface")
    assert isinstance(data["surface_code"], str) and data["surface_code"]
    assert data["surface_type"] in ["RUNWAY", "TAXIWAY", "APRON"]
    assert isinstance(data["length_ft"], (int, float))
    assert isinstance(data["width_ft"], (int, float))
    assert isinstance(data["area_sqft"], (int, float))
    assert isinstance(data["priority_rank"], int)
    assert data["status"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert data.get("current_condition_code") is None or isinstance(
        data["current_condition_code"], int)
    assert isinstance(data["active_notam_count"], int)


def assert_condition_report(data: dict):
    _assert_common_fields(data, "ConditionReport")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("surface_id", ""))
    assert data["contaminant_type"] in [
        "DRY", "WET", "DRY_SNOW", "WET_SNOW", "COMPACTED_SNOW", "ICE",
        "SLUSH", "STANDING_WATER",
    ]
    assert isinstance(data["coverage_pct"], int)
    assert isinstance(data["depth_inches"], (int, float))
    assert is_iso8601_timestamp(data.get("observed_at", ""))
    assert isinstance(data["condition_code"], int)
    assert 0 <= data["condition_code"] <= 6
    assert data["status"] in ["FILED", "SUPERSEDED"]
    assert data.get("superseded_by_id") is None or is_valid_uuid(
        data["superseded_by_id"])


def assert_friction_assessment(data: dict):
    _assert_common_fields(data, "FrictionAssessment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("surface_id", ""))
    assert isinstance(data["mu_value"], (int, float))
    assert is_iso8601_timestamp(data.get("measured_at", ""))
    assert data["braking_action"] in [
        "GOOD", "MEDIUM", "MEDIUM_POOR", "POOR", "NIL",
    ]
    assert data["status"] in ["REPORTED", "SUPERSEDED"]
    assert data.get("superseded_by_id") is None or is_valid_uuid(
        data["superseded_by_id"])


def assert_notam(data: dict):
    _assert_common_fields(data, "Notam")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("surface_id", ""))
    assert data["notam_type"] in [
        "SURFACE_CONDITION", "RUNWAY_CLOSURE", "CHEMICAL_TREATMENT",
    ]
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_until", ""))
    assert isinstance(data["message"], str)
    assert data["status"] in ["DRAFT", "ISSUED", "REISSUE_REQUIRED", "RESCINDED"]


def assert_chemical_product(data: dict):
    _assert_common_fields(data, "ChemicalProduct")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["base_rate_lbs_per_1000sqft"], (int, float))
    assert isinstance(data["unit_cost_cents_per_lb"], int)
    assert isinstance(data["seasonal_limit_lbs"], (int, float))
    assert isinstance(data["seasonal_reserved_lbs"], (int, float))
    assert isinstance(data["seasonal_dispensed_lbs"], (int, float))
    assert isinstance(data["seasonal_available_lbs"], (int, float))
    assert data["status"] in ["ACTIVE", "CONSTRAINED"]


def assert_chemical_application(data: dict):
    _assert_common_fields(data, "ChemicalApplication")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("surface_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["pavement_temp_f"], (int, float))
    assert isinstance(data["raw_quantity_lbs"], (int, float))
    assert data.get("authorized_quantity_lbs") is None or isinstance(
        data["authorized_quantity_lbs"], (int, float))
    assert isinstance(data["capped"], bool)
    assert data.get("authorized_by") is None or isinstance(
        data["authorized_by"], str)
    assert isinstance(data["line_cost_cents"], int)
    assert data["status"] in ["PROPOSED", "AUTHORIZED", "DISPENSED",
                              "REJECTED", "VOIDED"]


def assert_equipment_unit(data: dict):
    _assert_common_fields(data, "EquipmentUnit")
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["unit_type"] in ["PLOW", "BROOM", "DEICER", "BLOWER"]
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["readiness"] in ["READY", "OUT_OF_SERVICE"]


def assert_operator_shift(data: dict):
    _assert_common_fields(data, "OperatorShift")
    assert isinstance(data["operator_code"], str) and data["operator_code"]
    assert is_valid_uuid(data.get("event_id", ""))
    assert data.get("equipment_unit_id") is None or is_valid_uuid(
        data["equipment_unit_id"])
    assert isinstance(data["base_rate_cents_per_hour"], int)
    assert is_iso8601_timestamp(data.get("start_utc", ""))
    assert is_iso8601_timestamp(data.get("end_utc", ""))
    assert data.get("worked_hours") is None or isinstance(
        data["worked_hours"], (int, float))
    assert isinstance(data["line_cost_cents"], int)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_product_quota_invariant(product: dict):
    """The conserved-quota invariant on a product's seasonal counters (PRD 3.7)."""
    total = (product["seasonal_dispensed_lbs"] + product["seasonal_reserved_lbs"]
             + product["seasonal_available_lbs"])
    assert total == product["seasonal_limit_lbs"], (
        f"Quota not conserved: dispensed {product['seasonal_dispensed_lbs']} + "
        f"reserved {product['seasonal_reserved_lbs']} + available "
        f"{product['seasonal_available_lbs']} != limit "
        f"{product['seasonal_limit_lbs']}"
    )
