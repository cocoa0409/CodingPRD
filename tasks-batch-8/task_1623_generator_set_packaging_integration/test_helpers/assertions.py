"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_customer_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["credit_utilized_cents"], int)
    assert data["primary_locale"] in ("US_CA", "US_TX", "DE")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_engine_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str)
    assert isinstance(data["manufacturer"], str)
    assert data["rated_kw"] > 0
    assert data["fuel_burn_gph_at_75"] > 0
    assert data["emissions_tier_capability"] in (
        "TIER_2", "EPA_TIER_4", "STAGE_V", "TIER_4_FINAL_CARB"
    )
    assert data["list_price_cents"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_alternator_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["model_code"], str)
    assert data["rated_kva"] > 0
    assert 0 < data["efficiency_pct"] <= 100
    assert data["list_price_cents"] >= 0


def assert_package_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["site_locale"] in ("US_CA", "US_TX", "DE")
    assert data["occupancy_type"] in ("STANDARD", "HOSPITAL")
    assert data["application"] in ("STANDBY", "PRIME")
    assert data["build_status"] in (
        "SPEC", "SIZING", "CONFIGURING", "PERMITTING", "TESTING",
        "READY_TO_SHIP", "DELIVERED", "COMMISSIONED", "CANCELLED",
    )
    assert data["commercial_status"] in (
        "QUOTE", "AUTHORIZED", "INVOICED", "CLOSED", "REFUNDED"
    )
    for field in (
        "authorized_amount_cents", "committed_amount_cents", "refunded_amount_cents",
        "restocking_fee_cents", "freight_charge_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int cents"


def assert_sizing_study(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["engine_model_id"])
    assert is_valid_uuid(data["alternator_model_id"])
    assert isinstance(data["load_steps"], list)
    assert data["largest_motor_kva"] > 0
    assert data["starting_method"] in ("DOL", "SOFT_START")
    assert data["altitude_m"] >= 0
    assert -40 <= data["ambient_c"] <= 60
    assert data["method"] in ("NAMEPLATE_SUM", "DERATED_STOCHASTIC")
    assert isinstance(data["required_kva"], (int, float))
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_package_configuration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["sizing_study_id"])
    assert data["enclosure_type"] in ("OPEN", "WEATHERPROOF", "SOUND_ATTENUATED")
    assert data["enclosure_price_cents"] >= 0
    assert data["fuel_tank_gallons"] > 0
    assert isinstance(data["usable_gallons"], (int, float))
    assert isinstance(data["tank_price_cents"], int)
    assert isinstance(data["runtime_hours"], (int, float))
    assert data["min_runtime_hours"] in (24, 48)
    assert data["status"] in ("DRAFT", "LOCKED", "RELEASED", "CANCELLED")


def assert_permit_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["configuration_id"])
    assert data["jurisdiction_locale"] in ("US_CA", "US_TX", "DE")
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["resubmission_fee_cents"], int)
    assert isinstance(data["total_fees_paid_cents"], int)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CORRECTION_REQUESTED", "APPROVED", "EXPIRED", "WITHDRAWN"
    )


def assert_emissions_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["configuration_id"])
    assert data["required_tier"] in ("TIER_2", "EPA_TIER_4", "STAGE_V", "TIER_4_FINAL_CARB")
    assert data["engine_tier"] in ("TIER_2", "EPA_TIER_4", "STAGE_V", "TIER_4_FINAL_CARB")
    assert isinstance(data["requires_hour_log"], bool)
    assert isinstance(data["hour_log_attached"], bool)
    assert data["status"] in ("APP_DRAFT", "SUBMITTED", "ISSUED", "REJECTED", "VOIDED")


def assert_paralleling_scheme(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["sync_mode"] in ("ISOLATED", "PARALLEL_WITH_UTILITY", "MULTI_UNIT")
    assert 1 <= data["max_units"] <= 8
    assert isinstance(data["positions"], list)
    assert data["status"] in ("DESIGN", "PROGRAMMED", "VERIFIED")


def assert_test_bay(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bay_code"], str)
    assert data["max_kw"] > 0
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_factory_test(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["configuration_id"])
    assert is_valid_uuid(data["bay_id"])
    assert 0 <= data["start_hour"] < data["end_hour"] <= 24
    assert isinstance(data["readings"], list)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED", "ACCEPTED")


def assert_crane_slot(data: dict):
    _assert_common_fields(data)
    assert 0 <= data["window_start_hour"] < data["window_end_hour"] <= 24
    assert isinstance(data["buffer_hours"], (int, float))
    assert isinstance(data["reserved_hours"], (int, float))
    assert isinstance(data["free_hours"], (int, float))
    assert data["status"] in ("OPEN", "CLOSED")


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["crane_slot_id"])
    assert data["lift_hours"] > 0
    assert data["gross_weight_kg"] > 0
    assert data["freight_class"] in ("STANDARD", "OVERSIZE", "HEAVY_HAUL")
    assert data["status"] in ("BOOKED", "DISPATCHED", "DELIVERED", "RELEASED")


def assert_commissioning_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["shipment_id"])
    assert data["status"] in (
        "REQUESTED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "ACCEPTED", "CANCELLED"
    )


def assert_service_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["pricing_variant"] in ("FLAT_RISK_PREMIUM", "TIME_AND_MATERIALS_EV")
    assert 1 <= data["term_years"] <= 10
    assert data["nameplate_kw"] > 0
    assert data["pm_interval_days"] >= 30
    assert isinstance(data["annual_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert data["status"] in ("QUOTED", "BOUND", "ACTIVE", "LAPSED", "EXPIRED", "CANCELLED")


def assert_crane_slot_invariant(data: dict):
    """CraneSlot conservation invariant (PRD §3.8):
    free_hours + reserved_hours == window_end_hour - window_start_hour at all times."""
    window = data["window_end_hour"] - data["window_start_hour"]
    total = data["free_hours"] + data["reserved_hours"]
    assert abs(total - window) < 1e-6, (
        f"CraneSlot invariant violated: free {data['free_hours']} + "
        f"reserved {data['reserved_hours']} != window {window}"
    )
