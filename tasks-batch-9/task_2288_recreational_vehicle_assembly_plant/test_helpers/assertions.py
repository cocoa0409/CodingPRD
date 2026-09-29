"""Resource assertions and domain invariant checkers for the plant contract."""
from decimal import Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import types


def assert_hours(actual, expected):
    """PRD §2.6: station-hour figures carry exactly two decimals."""
    assert actual is not None, "expected a station-hour figure, got null"
    assert Decimal(str(actual)).quantize(Decimal("0.01")) == Decimal(str(expected)).quantize(
        Decimal("0.01")
    ), f"expected {expected} station hours, got {actual}"


def assert_two_decimals(actual, expected):
    """Compare a two-decimal figure (scores, hours) exactly."""
    assert actual is not None, "expected a two-decimal figure, got null"
    assert Decimal(str(actual)).quantize(Decimal("0.01")) == Decimal(str(expected)).quantize(
        Decimal("0.01")
    ), f"expected {expected}, got {actual}"


def assert_cents(actual, expected):
    """PRD §2.6: "All money is an integer number of cents"."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"money must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {expected} cents, got {actual}"


def assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["component_categories"], list) and data["component_categories"]
    for category in data["component_categories"]:
        assert category in types.COMPONENT_CATEGORIES
    assert data["supplier_status"] in types.SUPPLIER_STATUSES
    assert isinstance(data["open_recall_count"], int)
    assert isinstance(data["penalty_event_count"], int)
    assert Decimal("0.00") <= Decimal(str(data["quality_score"])) <= Decimal("100.00")


def assert_floor_plan(data: dict):
    assert_common_fields(data)
    assert data["chassis_class"] in types.CHASSIS_CLASSES
    assert data["status"] in types.FLOOR_PLAN_STATUSES
    assert data["electrical_service_amps"] in (30, 50)
    assert 18 <= data["length_ft"] <= 45
    assert data["gvwr_lbs"] > data["base_dry_weight_lbs"]
    # "The plant derives max_payload_lbs as the gross vehicle weight rating
    #  minus the base dry weight"
    assert data["max_payload_lbs"] == data["gvwr_lbs"] - data["base_dry_weight_lbs"]


def assert_option_item(data: dict):
    assert_common_fields(data)
    assert data["category"] in types.OPTION_CATEGORIES
    assert data["install_station"] in types.INSTALL_STATIONS
    assert data["status"] in types.OPTION_STATUSES
    assert data["price_cents"] >= 0
    assert data["weight_lbs"] >= 0
    assert Decimal(str(data["added_station_hours"])) >= 0
    assert data["amp_draw"] >= 0
    assert data["water_demand_gal"] >= 0
    assert isinstance(data["requires_option_codes"], list)
    assert isinstance(data["excludes_option_codes"], list)


def assert_dealer(data: dict):
    assert_common_fields(data)
    assert data["region"] in types.DEALER_REGIONS
    assert data["status"] in types.DEALER_STATUSES
    assert data["credit_status"] in types.CREDIT_STATUSES
    assert 1 <= data["allocation_share_bp"] <= 10000
    assert data["floor_plan_credit_limit_cents"] > 0
    assert data["goodwill_budget_cents"] >= 0
    assert data["financed_exposure_cents"] >= 0
    assert data["credit_utilization_bp"] >= 0
    assert data["goodwill_used_cents"] >= 0
    assert data["allocation_slots_reserved"] >= 0


def assert_unit_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.ORDER_STATUSES
    assert data["financing_status"] in types.FINANCING_STATUSES
    assert data["order_type"] in types.ORDER_TYPES
    assert data["ship_hold_reason"] in types.SHIP_HOLD_REASONS
    assert isinstance(data["selected_option_ids"], list)
    # "payload_remaining_lbs is the floor plan's gvwr_lbs minus config_weight_lbs"
    assert data["total_amp_draw"] >= 0
    assert data["total_water_demand_gal"] >= 0


def assert_unit_build(data: dict):
    assert_common_fields(data)
    assert data["current_station"] in types.BUILD_STATIONS
    assert isinstance(data["water_test_passed"], bool)
    assert isinstance(data["pdi_passed"], bool)
    assert isinstance(data["recall_hold"], bool)
    assert data["defect_points_total"] >= 0
    assert data["rework_count"] >= 0
    assert Decimal(str(data["actual_station_hours"])) >= 0


def assert_production_slot(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.SLOT_STATUSES
    assert data["sequence_position"] >= 1
    assert is_iso8601_timestamp(data["expires_at"])


def assert_chassis_receipt(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.CHASSIS_STATUSES
    assert data["chassis_class"] in types.CHASSIS_CLASSES
    assert data["gvwr_lbs"] > 0
    assert data["wheelbase_in"] > 0


def assert_component_lot(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.LOT_STATUSES
    assert data["category"] in types.COMPONENT_CATEGORIES
    assert_lot_counter_invariant(data)


def assert_lot_counter_invariant(lot: dict):
    """PRD §3.1: "available plus installed plus quarantined always equals
    quantity_received"."""
    total = lot["quantity_available"] + lot["quantity_installed"] + lot["quantity_quarantined"]
    assert total == lot["quantity_received"], (
        f"lot piece counters must conserve {lot['quantity_received']} received pieces, "
        f"got available={lot['quantity_available']} installed={lot['quantity_installed']} "
        f"quarantined={lot['quantity_quarantined']}"
    )


def assert_component_installation(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.INSTALLATION_STATUSES
    assert data["station"] in types.INSTALL_STATIONS
    assert data["quantity"] >= 1


def assert_quality_inspection(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.INSPECTION_STATUSES
    assert data["inspection_type"] in types.INSPECTION_TYPES
    if data.get("result") is not None:
        assert data["result"] in types.INSPECTION_GRADES


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.CLAIM_STATUSES
    assert data["claim_type"] in types.CLAIM_TYPES
    assert isinstance(data["in_warranty"], bool)
    assert data["info_request_count"] >= 0
    if data.get("authority_tier") is not None:
        assert data["authority_tier"] in types.GOODWILL_TIERS


def assert_recall_campaign(data: dict):
    assert_common_fields(data)
    assert data["status"] in types.CAMPAIGN_STATUSES
    assert data["severity"] in types.RECALL_SEVERITIES
    assert isinstance(data["lot_codes"], list)
    assert data["affected_installation_count"] >= 0
    assert data["remedied_installation_count"] >= 0
    assert data["remedied_installation_count"] <= data["affected_installation_count"]


def assert_vin_format(vin: str, model_code: str, build_sequence: int):
    """PRD §3.4: "the model_code, a hyphen, and the build_sequence zero-padded
    to six digits"."""
    assert vin == f"{model_code}-{build_sequence:06d}", (
        f"expected VIN {model_code}-{build_sequence:06d}, got {vin}"
    )
