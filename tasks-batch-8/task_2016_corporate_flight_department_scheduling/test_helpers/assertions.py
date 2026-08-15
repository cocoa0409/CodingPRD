"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_system_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_aircraft(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert data["aircraft_type"] in ("LIGHT_JET", "MIDSIZE_JET", "HEAVY_JET", "TURBOPROP")
    assert isinstance(data["passenger_capacity"], int) and data["passenger_capacity"] >= 1
    assert isinstance(data["home_base_icao"], str) and data["home_base_icao"]
    assert data["status"] in ("ACTIVE", "GROUNDED", "RETIRED")
    assert data["posture"] in ("AVAILABLE", "MAINTENANCE_HOLD", "DOCUMENT_LAPSE")


def assert_document_permit(data: dict):
    _assert_system_fields(data)
    assert data["doc_kind"] in (
        "AIRWORTHINESS_CERT", "REGISTRATION", "INSURANCE",
        "OPS_SPECS", "NOISE_CERT", "INTERNATIONAL_PERMIT",
    )
    assert isinstance(data["identifier"], str) and data["identifier"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("CURRENT", "EXPIRED")


def assert_crew_member(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["seat_qualification"] in ("PIC", "SIC")
    assert isinstance(data["type_ratings"], list)
    assert is_iso8601_timestamp(data["training_valid_until"])
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "INACTIVE")
    assert isinstance(data["duty_minutes_used"], int) and data["duty_minutes_used"] >= 0


def assert_business_unit(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["bu_code"], str) and data["bu_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["annual_flight_budget_cents"], int)
    assert data["annual_flight_budget_cents"] >= 0
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0


def assert_passenger_profile(data: dict):
    _assert_system_fields(data)
    assert isinstance(data["employee_number"], str) and data["employee_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["priority_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert is_valid_uuid(data["home_bu_id"])
    assert isinstance(data["sifl_control_employee"], bool)


def assert_trip_request(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["requester_id"])
    assert is_valid_uuid(data["charge_bu_id"])
    assert data["trip_kind"] in ("BUSINESS", "PERSONAL", "MIXED")
    assert isinstance(data["purpose"], str)
    assert is_iso8601_timestamp(data["requested_departure_utc"])
    assert is_iso8601_timestamp(data["requested_return_utc"])
    assert isinstance(data["passenger_ids"], list) and len(data["passenger_ids"]) >= 1
    assert data["approval_status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert data["assignment_status"] in (
        "UNASSIGNED", "ASSIGNED", "DISPATCHED", "COMPLETED", "CANCELLED",
    )
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED")
    assert isinstance(data["personal_use_flag"], bool)


def assert_flight_leg(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["trip_request_id"])
    assert isinstance(data["leg_sequence"], int) and data["leg_sequence"] >= 1
    assert isinstance(data["origin_icao"], str) and data["origin_icao"]
    assert isinstance(data["destination_icao"], str) and data["destination_icao"]
    assert is_iso8601_timestamp(data["scheduled_departure_utc"])
    assert is_iso8601_timestamp(data["scheduled_arrival_utc"])
    assert isinstance(data["distance_statute_miles"], int)
    assert isinstance(data["block_minutes"], int) and data["block_minutes"] > 0
    assert data["status"] in (
        "PLANNED", "AIRCRAFT_ASSIGNED", "CREWED", "RELEASED", "COMPLETED", "CANCELLED",
    )


def assert_maintenance_window(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["aircraft_id"])
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert data["maintenance_kind"] in (
        "SCHEDULED_INSPECTION", "UNSCHEDULED_REPAIR", "AVIONICS_UPGRADE", "ENGINE_OVERHAUL",
    )
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_catering_order(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["flight_leg_id"])
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["menu_code"], str) and data["menu_code"]
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "DELIVERED", "CANCELLED")


def assert_ground_transport(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["flight_leg_id"])
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert isinstance(data["pickup_minutes_after_arrival"], int)
    assert data["pickup_minutes_after_arrival"] >= 0
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_charter_supplement(data: dict):
    _assert_system_fields(data)
    assert is_valid_uuid(data["trip_request_id"])
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0
    assert data["aircraft_type_offered"] in (
        "LIGHT_JET", "MIDSIZE_JET", "HEAVY_JET", "TURBOPROP",
    )
    assert data["status"] in ("QUOTED", "ACCEPTED", "DECLINED", "EXPIRED")


def assert_sifl_rate_period(data: dict):
    _assert_system_fields(data)
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])
    assert isinstance(data["terminal_charge_cents"], int)
    assert data["terminal_charge_cents"] >= 0
    assert isinstance(data["rate_band_1_cents_per_mile"], int)
    assert isinstance(data["rate_band_2_cents_per_mile"], int)
    assert isinstance(data["rate_band_3_cents_per_mile"], int)
    assert isinstance(data["control_employee_multiplier_pct"], int)
