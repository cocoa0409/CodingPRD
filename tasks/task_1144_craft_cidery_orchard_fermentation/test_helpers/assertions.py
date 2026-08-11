"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lightweight record must not carry updated_at"
    assert "version" not in data, "lightweight record must not carry version"


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["grower_name"], str) and data["grower_name"]
    assert isinstance(data["season_year"], int)
    assert isinstance(data["committed_weight_lbs"], int)
    assert isinstance(data["received_weight_lbs"], int) and data["received_weight_lbs"] >= 0
    assert isinstance(data["price_per_lb_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SETTLED", "VOIDED")


def assert_settlement_penalty_cents(contract_data: dict, expected_cents: int):
    """Assert the persisted settlement penalty equals `expected_cents`.

    PRD 3.1 pins the tiered formula and that the final penalty "persists to the
    settlement record", but never names the response field (2.6 calls it "the
    settlement penalty", 3.1 "the shortfall penalty"). Accept either natural
    field name; absence of both fails the assertion.
    """
    penalty = contract_data.get("shortfall_penalty_cents",
                                contract_data.get("settlement_penalty_cents"))
    assert penalty is not None, (
        "settled contract must expose the persisted penalty "
        "(shortfall_penalty_cents or settlement_penalty_cents); "
        f"got keys: {sorted(contract_data.keys())}"
    )
    assert penalty == expected_cents, f"settlement penalty {penalty} != expected {expected_cents}"


def assert_variety(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["code"], str) and data["code"]


def assert_harvest_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] > 0
    assert isinstance(data["pressed_weight_lbs"], int) and data["pressed_weight_lbs"] >= 0
    assert isinstance(data["unpressed_weight_lbs"], int) and data["unpressed_weight_lbs"] >= 0
    assert data["status"] in ("RECEIVED", "PARTIALLY_PRESSED", "PRESSED", "SPOILED")


def assert_lot_weight_invariant(lot: dict):
    """unpressed_weight_lbs is always weight_lbs minus pressed_weight_lbs."""
    assert lot["pressed_weight_lbs"] + lot["unpressed_weight_lbs"] == lot["weight_lbs"], (
        f"lot weight invariant violated: {lot['pressed_weight_lbs']} + "
        f"{lot['unpressed_weight_lbs']} != {lot['weight_lbs']}"
    )


def assert_press_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "PRESSING", "COMPLETE", "CANCELLED")
    assert isinstance(data["press_window_minutes"], int)


def assert_blend_line(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] > 0
    assert isinstance(data["position"], int)


def assert_tank(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] > 0
    assert data["material"] in ("STAINLESS", "OAK", "CONCRETE", "PLASTIC")
    assert data["status"] in ("EMPTY", "RESERVED", "FERMENTING", "AGING", "CLEANING", "MAINTENANCE")


def assert_yeast_program(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["kind"] in ("CULTURED", "WILD", "MIXED")


def assert_fermentation_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["volume_liters"], int) and data["volume_liters"] >= 0
    assert data["status"] in ("PITCHED", "FERMENTING", "AGING", "READY", "PACKAGED", "DUMPED")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["style"] in ("DRY", "SEMI_DRY", "SWEET", "HOPPED", "FRUIT_INFUSED")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_label_approval(data: dict):
    _assert_common(data)
    assert data["market"] in ("FEDERAL_TTB", "NY_SLA", "VT_DLL", "MA_ABCC")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")


def assert_license(data: dict):
    _assert_common(data)
    assert data["kind"] in ("TTB_BREWERS_NOTICE", "NY_FARM_CIDERY", "VT_MANUFACTURER",
                            "MA_FARMER_WINERY", "INTERSTATE_SHIPPER")
    assert isinstance(data["annual_volume_cap_liters"], int)
    assert isinstance(data["volume_used_liters"], int) and data["volume_used_liters"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REINSTATED", "EXPIRED")


def assert_packaging_run(data: dict):
    _assert_common(data)
    assert data["package_format"] in ("CAN_12OZ", "CAN_16OZ", "BOTTLE_500ML",
                                      "BOTTLE_750ML", "KEG_5GAL", "KEG_15_5GAL")
    assert isinstance(data["units_produced"], int) and data["units_produced"] >= 0
    assert isinstance(data["volume_liters"], int) and data["volume_liters"] > 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_order(data: dict):
    _assert_common(data)
    assert data["channel"] in ("TASTING_ROOM", "CLUB_SUBSCRIPTION", "WHOLESALE_DISTRIBUTION")
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["subtotal_cents"], int)
    assert data["status"] in ("DRAFT", "CONFIRMED", "SHIPPED", "DELIVERED", "CANCELLED", "RETURNED")


def assert_excise_report(data: dict):
    _assert_common(data)
    assert isinstance(data["period_year"], int)
    assert 1 <= data["period_month"] <= 12
    assert data["regulator"] in ("TTB", "NY_SLA", "VT_DLL", "MA_ABCC")
    assert data["status"] in ("OPEN", "FILED", "AMENDED")


def assert_compliance_event(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["action"], str) and data["action"]
    assert is_iso8601_timestamp(data.get("event_at", "")), "event_at must be ISO 8601"
