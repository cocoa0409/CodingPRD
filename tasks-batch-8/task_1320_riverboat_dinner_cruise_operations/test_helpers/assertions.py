"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Primary resources carry id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _assert_light_fields(data: dict, entity: str):
    """BookingPassenger and CruiseCredit carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_vessel(data: dict):
    _assert_common_fields(data, "Vessel")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["coast_guard_capacity"], int)
    assert data["coast_guard_capacity"] >= 0
    assert isinstance(data["home_dock_id"], str)
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_dock(data: dict):
    _assert_common_fields(data, "Dock")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["parking_capacity"], int)
    assert data["parking_capacity"] >= 0
    assert isinstance(data["parking_in_use"], int)
    assert data["parking_in_use"] >= 0


def assert_menu_tier(data: dict):
    _assert_common_fields(data, "MenuTier")
    assert data["code"] in ("STANDARD", "PREMIUM", "LUXE")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["galley_load_per_cover"], (int, float))
    assert isinstance(data["bar_package_price_cents"], int)


def assert_cruise(data: dict):
    _assert_common_fields(data, "CruiseInstance")
    assert isinstance(data["vessel_id"], str)
    assert isinstance(data["menu_tier_id"], str)
    assert is_iso8601_timestamp(data["depart_at"])
    assert is_iso8601_timestamp(data["return_at"])
    assert data["season"] in ("PEAK", "SHOULDER", "OFF")
    assert isinstance(data["is_holiday"], bool)
    assert isinstance(data["reserved_covers"], int) and data["reserved_covers"] >= 0
    assert isinstance(data["boarded_count"], int) and data["boarded_count"] >= 0
    assert isinstance(data["bar_service_enabled"], bool)
    assert data.get("charter_booking_id") is None or isinstance(
        data["charter_booking_id"], str)
    assert data["status"] in (
        "SCHEDULED", "BOARDING", "UNDERWAY", "COMPLETED", "WEATHER_HOLD", "CANCELLED")


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0


def assert_booking(data: dict):
    _assert_common_fields(data, "Booking")
    assert isinstance(data["cruise_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["booking_total_cents"], int)
    assert isinstance(data["bar_package_count"], int)
    assert 0 <= data["bar_package_count"] <= data["party_size"]
    assert isinstance(data["bar_package_total_cents"], int)
    assert data["payment_status"] in (
        "PENDING", "PAID", "REFUND_PENDING", "REFUNDED", "CREDITED")
    assert data["booking_status"] in (
        "RESERVED", "CONFIRMED", "BOARDED", "NO_SHOW", "CANCELLED",
        "CONVERTED_TO_CHARTER")


def assert_booking_passenger(data: dict):
    _assert_light_fields(data, "BookingPassenger")
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["is_minor"], bool)
    assert data.get("boarded_at") is None or is_iso8601_timestamp(data["boarded_at"])


def assert_manifest(data: dict):
    _assert_common_fields(data, "BoardingManifest")
    assert isinstance(data["cruise_id"], str)
    assert isinstance(data["passenger_count"], int) and data["passenger_count"] >= 0
    assert isinstance(data["coast_guard_capacity"], int)
    assert data["status"] in ("DRAFT", "FROZEN", "FILED")


def assert_staff_member(data: dict):
    _assert_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_code"] in (
        "SERVER", "BARTENDER", "GALLEY", "ENTERTAINER", "DECKHAND")
    assert data.get("alcohol_cert_expires_at") is None or is_iso8601_timestamp(
        data["alcohol_cert_expires_at"])


def assert_staff_assignment(data: dict):
    _assert_common_fields(data, "StaffAssignment")
    assert isinstance(data["cruise_id"], str)
    assert isinstance(data["staff_member_id"], str)
    assert data["assigned_role"] in (
        "SERVER", "BARTENDER", "GALLEY", "ENTERTAINER", "DECKHAND")
    assert data["status"] in ("ASSIGNED", "CONFIRMED", "RELEASED")


def assert_provision_order(data: dict):
    _assert_common_fields(data, "GalleyProvisionOrder")
    assert isinstance(data["cruise_id"], str)
    assert isinstance(data["provisional_covers"], int)
    assert data["provisional_covers"] >= 0
    assert isinstance(data["provision_load_units"], (int, float))
    assert isinstance(data["restocking_rebate_cents"], int)
    assert data["restocking_rebate_cents"] >= 0
    assert data["status"] in ("DRAFT", "PLACED", "RECEIVED", "SETTLED", "CANCELLED")


def assert_charter_inquiry(data: dict):
    _assert_common_fields(data, "CharterInquiry")
    assert isinstance(data["cruise_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["quote_round"], int) and data["quote_round"] >= 0
    assert data["status"] in (
        "DRAFT", "QUOTED", "COUNTERED", "ACCEPTED", "CONVERTED", "DECLINED",
        "EXPIRED")


def assert_weather_event(data: dict):
    _assert_common_fields(data, "WeatherEvent")
    assert is_iso8601_timestamp(data["declared_at"])
    assert data["severity"] in ("ADVISORY", "GALE_WARNING", "CANCELLATION_REQUIRED")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in (
        "DECLARED", "CANCELLATION_ISSUED", "CREDITS_SETTLED", "CLOSED")


def assert_cruise_credit(data: dict):
    _assert_light_fields(data, "CruiseCredit")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["credit_status"] in ("ISSUED", "SETTLED", "REDEEMED", "EXPIRED")


def assert_dock_slot(data: dict):
    _assert_common_fields(data, "DockSlot")
    assert isinstance(data["dock_id"], str)
    assert isinstance(data["vessel_id"], str)
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])


def assert_parking_pass(data: dict):
    _assert_common_fields(data, "ParkingPass")
    assert isinstance(data["dock_id"], str)
    assert isinstance(data["booking_id"], str)
    assert isinstance(data["cruise_id"], str)
    assert data["status"] in ("RESERVED", "REDEEMED", "RELEASED", "EXPIRED")


def assert_parking_pool_invariant(dock: dict):
    """parking_in_use must stay within [0, parking_capacity] (PRD §3.7)."""
    assert 0 <= dock["parking_in_use"] <= dock["parking_capacity"], (
        f"parking_in_use {dock['parking_in_use']} out of bounds for capacity "
        f"{dock['parking_capacity']}"
    )


def assert_capacity_invariant(cruise: dict, vessel: dict):
    """reserved_covers / boarded_count never exceed certified capacity (PRD §3.2)."""
    cap = vessel["coast_guard_capacity"]
    assert cruise["reserved_covers"] <= cap, (
        f"reserved_covers {cruise['reserved_covers']} exceeds capacity {cap}"
    )
    assert cruise["boarded_count"] <= cap, (
        f"boarded_count {cruise['boarded_count']} exceeds capacity {cap}"
    )
