"""Entity assertions and domain invariant checkers.

Append-only records (telemetry readings, water test results, blowdown events)
carry only id + created_at per the PRD; their assertions deliberately do NOT
demand updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_append_only(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is append-only and must not carry updated_at"
    assert "version" not in data, f"{entity} is append-only and must not carry version"


def assert_account(data: dict):
    _assert_common(data, "CustomerAccount")
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["credit_hold"], bool)
    assert data["billing_model"] in ("PRODUCT", "SERVICE_CONTRACT")
    assert isinstance(data["open_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_asset(data: dict):
    _assert_common(data, "SystemAsset")
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["asset_type"] in ("COOLING_TOWER", "BOILER", "CLOSED_LOOP")
    assert data["recirculation_rate_gpm"] > 0
    assert data["system_volume_gal"] > 0
    assert data["metallurgy"] in ("MILD_STEEL", "COPPER_ALLOY", "STAINLESS", "GALVANIZED")
    assert data["posture"] in ("COMPLIANT", "WATCH", "NON_COMPLIANT", "FROZEN")
    assert data["status"] in ("COMMISSIONING", "IN_SERVICE", "DECOMMISSIONED")


def assert_program_design(data: dict):
    _assert_common(data, "ProgramDesign")
    assert data["status"] in (
        "SURVEY_SCHEDULED", "SURVEYED", "DRAFTED", "PROPOSED",
        "REVISE_REQUESTED", "ACCEPTED", "SUPERSEDED", "WITHDRAWN",
    )
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1


def assert_product(data: dict):
    _assert_common(data, "ChemicalProduct")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert 0 < data["active_pct"] <= 100
    assert data["container_size_gal"] > 0
    assert data["unit_price_cents_per_gal"] >= 0
    assert 0 <= data["contract_price_cents_per_gal"] <= data["unit_price_cents_per_gal"]
    assert data["status"] in ("LISTED", "DELISTED")


def assert_feed_station(data: dict):
    _assert_common(data, "FeedStation")
    assert data["feed_mode"] in ("CONTINUOUS", "SHOT_FEED")
    assert data["capacity_cap_ml_per_min"] > 0
    assert data["status"] in ("OFFLINE", "ONLINE", "LOCKED_OUT")
    assert data["inventory_gal"] is not None
    assert data["consumption_rate_gal_per_day"] is not None


def assert_telemetry_reading(data: dict):
    _assert_append_only(data, "TelemetryReading")
    assert data["feed_pulses"] >= 0
    assert data["ml_per_pulse"] > 0
    assert data["level_gal"] >= 0


def assert_test_route(data: dict):
    _assert_common(data, "TestRoute")
    assert isinstance(data["route_name"], str) and data["route_name"]
    assert data["status"] in ("PLANNED", "PUBLISHED", "COMPLETED", "CANCELLED")


def assert_route_stop(data: dict):
    _assert_common(data, "RouteStop")
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert data["status"] in ("SCHEDULED", "ARRIVED", "SAMPLED", "SKIPPED", "MISSED")


def assert_water_test_result(data: dict):
    _assert_append_only(data, "WaterTestResult")
    assert 0 <= data["ph"] <= 14
    assert data["conductivity_umhos"] > 0
    assert data["classification"] in ("SCALE_FORMING", "BALANCED", "CORROSIVE")
    assert data["range_status"] in ("IN_RANGE", "OUT_OF_RANGE")
    assert data["status"] in ("RECORDED", "CONFIRMED", "VOIDED")


def assert_corrective_action(data: dict):
    _assert_common(data, "CorrectiveAction")
    assert data["status"] in ("PENDING", "APPROVED", "APPLIED", "DECLINED")
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_rack(data: dict):
    _assert_common(data, "CouponRack")
    assert 1 <= data["position_count"] <= 8
    assert data["status"] in ("INSTALLED", "ARCHIVED")


def assert_coupon(data: dict):
    _assert_common(data, "CorrosionCoupon")
    assert data["alloy"] in ("MILD_STEEL", "COPPER", "ADMIRALTY", "STAINLESS_304")
    assert data["pre_weight_g"] > 0
    assert data["status"] in ("INSTALLED", "REMOVED")


def assert_legionella_plan(data: dict):
    _assert_common(data, "LegionellaRiskPlan")
    assert 7 <= data["validation_interval_days"] <= 365
    assert data["status"] in ("DRAFT", "ACTIVE", "VALIDATION_DUE", "DELINQUENT", "SUSPENDED")


def assert_blowdown_event(data: dict):
    _assert_append_only(data, "BlowdownEvent")
    assert data["blowdown_gal"] > 0
    assert data["makeup_gal"] > 0


def assert_delivery_order(data: dict):
    _assert_common(data, "DeliveryOrder")
    assert data["quantity_gal"] > 0
    assert isinstance(data["auto_drafted"], bool)
    assert data["status"] in (
        "DRAFT", "PENDING", "SCHEDULED", "IN_TRANSIT", "DELIVERED",
        "FAILED_DELIVERY", "CLOSED", "CANCELLED",
    )


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert data["pricing_variant"] in ("PRODUCT", "SERVICE_CONTRACT")
    assert isinstance(data["product_charges_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["invoice_total_cents"], int)
    assert data["invoice_total_cents"] == data["product_charges_cents"] + data["service_fee_cents"]
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "OVERDUE", "VOID")


def assert_account_invariants(data: dict):
    """Domain invariants for an account: balance never negative."""
    assert data["open_balance_cents"] >= 0, "open_balance_cents must not be negative"


def assert_station_invariants(data: dict):
    """Domain invariants for a feed station: setpoint clamped to [0, cap]."""
    assert 0 <= data["setpoint_ml_per_min"] <= data["capacity_cap_ml_per_min"], (
        f"setpoint {data['setpoint_ml_per_min']} outside [0, {data['capacity_cap_ml_per_min']}]"
    )
