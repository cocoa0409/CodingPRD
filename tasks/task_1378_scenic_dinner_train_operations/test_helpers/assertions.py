"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["host_railroad_name"], str) and data["host_railroad_name"]
    assert isinstance(data["subdivision_code"], str) and data["subdivision_code"]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert isinstance(data["max_trains_per_day"], int) and data["max_trains_per_day"] >= 1
    assert isinstance(data["min_slot_minutes"], int) and data["min_slot_minutes"] >= 30
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")


def assert_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["service_date"], str)
    assert isinstance(data["start_minute"], int) and 0 <= data["start_minute"] <= 1439
    assert isinstance(data["end_minute"], int) and 1 <= data["end_minute"] <= 1440
    assert data["end_minute"] > data["start_minute"]
    assert data["status"] in ("OPEN", "RESERVED", "CONSUMED", "RELEASED")


def assert_rolling_stock(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["stock_type"] in ("LOCOMOTIVE", "COACH_CAR", "FIRST_CLASS_CAR", "DINING_CAR")
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 0
    assert isinstance(data["table_count"], int) and data["table_count"] >= 0
    assert data["status"] in ("AVAILABLE", "IN_MAINTENANCE", "OUT_OF_SERVICE")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("stock_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["scope"] in ("INSPECTION", "REPAIR", "OVERHAUL")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_excursion(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert is_valid_uuid(data.get("slot_id", ""))
    assert data["event_type"] in ("REGULAR", "HOLIDAY")
    assert isinstance(data["surge_multiplier_bp"], int)
    assert isinstance(data["service_date"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "BOARDING", "OPERATED", "CANCELLED")
    assert data.get("cancel_reason") in (None, "WEATHER", "EVENT", "OPERATOR", "TRACK_RIGHTS_LOST")
    for field in ("coach_seats_available", "first_class_seats_available", "dining_seats_available"):
        assert isinstance(data[field], int), f"{field} must be an integer seat count"


def assert_car_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("excursion_id", ""))
    assert is_valid_uuid(data.get("stock_id", ""))
    assert data["class_code"] in ("LOCO", "COACH", "FIRST_CLASS", "DINING")
    assert isinstance(data["position"], int) and data["position"] >= 1
    assert isinstance(data["effective_capacity"], int) and data["effective_capacity"] >= 0


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("excursion_id", ""))
    assert isinstance(data["customer_email"], str) and data["customer_email"]
    assert data["class_code"] in ("COACH", "FIRST_CLASS", "DINING")
    assert isinstance(data["party_size"], int) and 1 <= data["party_size"] <= 8
    assert data.get("dining_service") in (None, "EARLY", "LATE")
    assert data["status"] in ("HELD", "CONFIRMED", "CHECKED_IN", "COMPLETED",
                              "CANCELLED", "RAIN_CHECKED", "NO_SHOW")
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    # PRD §3.5 pins pricing to CONFIRM ("Confirmation converts a hold into
    # revenue ... Pricing follows the fare rule of §2.6 exactly"), so the three
    # fare fields are pinned integers only for bookings that have passed through
    # CONFIRM. For HELD (and HELD->CANCELLED) bookings the PRD is silent on
    # their pre-confirm values, so null-or-int is the only fair assertion.
    if data["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "RAIN_CHECKED"):
        for field in ("unit_fare_cents", "total_price_cents", "paid_cents"):
            assert isinstance(data[field], int), f"{field} must be integer cents"
    else:
        for field in ("unit_fare_cents", "total_price_cents", "paid_cents"):
            assert data.get(field) is None or isinstance(data[field], int)
    # PRD §3.6: "Bookings cancelled from any other path — swept holds, no-shows,
    # rain-checked passengers — carry `refund_cents` of 0." A swept hold never
    # sees a refund computation yet carries 0, so refund_cents is a standing
    # integer field from creation onward.
    assert isinstance(data["refund_cents"], int), "refund_cents must be integer cents"
    assert data.get("dining_table_number") is None or isinstance(data["dining_table_number"], int)
    assert data.get("dining_car_assignment_id") is None or isinstance(data["dining_car_assignment_id"], str)


def assert_crew_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["role"] in ("ENGINEER", "CONDUCTOR", "CAR_HOST", "CHEF", "SERVER", "DOCENT")
    assert isinstance(data["is_volunteer"], bool)
    assert data.get("cert_expires_on") is None or isinstance(data["cert_expires_on"], str)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_crew_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("excursion_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert data["position"] in ("ENGINEER", "CONDUCTOR", "CAR_HOST", "CHEF", "SERVER", "DOCENT")
    assert data["status"] in ("ASSIGNED", "RELEASED", "COMPLETED")


def assert_manifest(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("excursion_id", ""))
    assert data["status"] in ("DRAFT", "LOCKED", "PROVISIONED")
    assert isinstance(data["early_diner_count"], int) and data["early_diner_count"] >= 0
    assert isinstance(data["late_diner_count"], int) and data["late_diner_count"] >= 0
    assert isinstance(data["galley_load_units"], int) and data["galley_load_units"] >= 0
    assert data.get("locked_at") is None or is_iso8601_timestamp(data["locked_at"])
    assert data.get("actual_loaded_units") is None or isinstance(data["actual_loaded_units"], int)


def assert_rain_check(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("booking_id", ""))
    assert isinstance(data["customer_email"], str) and data["customer_email"]
    assert isinstance(data["value_cents"], int) and data["value_cents"] >= 0
    assert data["reason"] in ("WEATHER", "EVENT", "TRACK_RIGHTS_LOST")
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ("ISSUED", "REDEEMED", "EXPIRED")
    assert data.get("redeemed_booking_id") is None or isinstance(data["redeemed_booking_id"], str)
