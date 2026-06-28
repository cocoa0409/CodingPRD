"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def _assert_audit(data: dict):
    """Lightweight audit records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit record must not carry updated_at"
    assert "version" not in data, "audit record must not carry version"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["membership_tier"] in ("NONE", "SEASON", "PREMIER")
    assert data["waiver_status"] in ("UNSIGNED", "SIGNED", "EXPIRED")
    assert data["training_level"] in ("NONE", "BASIC", "ADVANCED")
    assert isinstance(data["deposit_hold_cents"], int) and data["deposit_hold_cents"] >= 0
    assert isinstance(data["lifetime_damage_strikes"], int) and data["lifetime_damage_strikes"] >= 0


def assert_guide(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["max_class"] in ("TRAIL", "UTILITY", "MOUNTAIN")
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")


def assert_trail(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["required_class"] in ("TRAIL", "UTILITY", "MOUNTAIN")
    assert isinstance(data["max_riders"], int) and data["max_riders"] >= 1
    assert data["condition"] in ("OPEN", "CAUTION", "CLOSED")


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["vin_tag"], str) and len(data["vin_tag"]) > 0
    assert data["unit_class"] in ("TRAIL", "UTILITY", "MOUNTAIN")
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["tank_capacity_liters"] > 0
    assert data["status"] in ("AVAILABLE", "RESERVED", "OUT", "MAINTENANCE")


def assert_gear_item(data: dict):
    _assert_common(data)
    assert data["kind"] in ("HELMET", "SUIT")
    assert isinstance(data["size_code"], str)
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] >= 0
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "OUT", "RETIRED")


def assert_departure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("trail_id", "")), "trail_id must be valid UUID"
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert data["required_guide_class"] in ("TRAIL", "UTILITY", "MOUNTAIN")
    assert isinstance(data["capacity_riders"], int) and data["capacity_riders"] >= 1
    assert isinstance(data["rider_count"], int) and data["rider_count"] >= 0
    assert isinstance(data["guide_count"], int) and data["guide_count"] >= 0
    assert data["status"] in ("SCHEDULED", "LOCKED", "DEPARTED", "COMPLETED", "CANCELLED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be valid UUID"
    assert is_valid_uuid(data.get("tour_departure_id", "")), "tour_departure_id must be valid UUID"
    assert is_valid_uuid(data.get("unit_id", "")), "unit_id must be valid UUID"
    assert data["reservation_status"] in (
        "PENDING", "CONFIRMED", "CHECKED_OUT", "RETURNED", "CANCELLED", "NO_SHOW")
    assert data["settlement_status"] in ("NONE", "HELD", "SETTLED", "REFUNDED")
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["deposit_hold_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be valid UUID"
    for f in ("rental_charge_cents", "fuel_charge_cents", "late_charge_cents",
              "damage_assessed_cents", "gear_loss_cents", "deposit_applied_cents",
              "refund_cents", "net_charge_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_closure_event(data: dict):
    _assert_audit(data)
    assert is_valid_uuid(data.get("trail_id", "")), "trail_id must be valid UUID"
    assert data["new_condition"] in ("OPEN", "CAUTION", "CLOSED")
    assert isinstance(data["cancelled_departure_count"], int)


def assert_guide_assignment(data: dict):
    _assert_audit(data)
    assert is_valid_uuid(data.get("tour_departure_id", "")), "tour_departure_id must be valid UUID"
    assert is_valid_uuid(data.get("guide_id", "")), "guide_id must be valid UUID"
    assert isinstance(data["active"], bool)


def assert_settlement_reconciles(data: dict):
    """Waterfall invariant: applied + refund == deposit_hold; charges reconcile."""
    total_charges = (data["rental_charge_cents"] + data["fuel_charge_cents"]
                     + data["late_charge_cents"] + data["damage_assessed_cents"]
                     + data["gear_loss_cents"])
    deposit_hold = data["deposit_applied_cents"] + data["refund_cents"]
    assert data["deposit_applied_cents"] == min(deposit_hold, total_charges), \
        "deposit_applied must equal min(deposit_hold, total_charges)"
    assert data["net_charge_cents"] == max(0, total_charges - deposit_hold), \
        "net_charge must equal max(0, total_charges - deposit_hold)"
