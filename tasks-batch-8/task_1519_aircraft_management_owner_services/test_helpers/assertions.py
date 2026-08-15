"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_owner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_aircraft(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["home_base_icao"], str) and data["home_base_icao"]
    assert isinstance(data["total_time_hours"], (int, float))


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["owner_id"], str) and data["owner_id"]
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["monthly_management_fee_cents"], int)
    assert isinstance(data["variable_fee_pct"], (int, float))
    assert isinstance(data["charter_owner_share_pct"], (int, float))
    assert data["tax_allocation_method"] in ("FLIGHT_HOURS", "TRIP_LEGS")
    assert data["status"] in (
        "PENDING", "ACTIVE", "TERMINATION_PENDING", "HANDOVER_IN_PROGRESS", "TERMINATED",
    )
    assert isinstance(data["records_total"], int)
    assert isinstance(data["records_released"], int)


def assert_budget(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["fiscal_year"], int)
    for field in ("fuel_cents", "maintenance_cents", "crew_cents",
                  "hangar_cents", "insurance_cents", "other_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_expense(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert data["category"] in (
        "FUEL", "CREW", "MAINTENANCE", "HANGAR", "INSURANCE",
        "PROGRAM_ACCRUAL", "CHARTER_DIRECT", "OTHER",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert data["tax_use"] in ("OWNER_USE", "CHARTER_USE", "MIXED")
    assert data["status"] in ("POSTED", "BILLED", "VOID")


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert isinstance(data["accrual_total_cents"], int)
    assert isinstance(data["cash_total_cents"], int)
    assert isinstance(data["management_fee_cents"], int)
    assert isinstance(data["charter_offset_cents"], int)
    assert "budget_variance_cents" in data
    assert isinstance(data["mixed_owner_share_cents"], int)
    assert isinstance(data["mixed_charter_share_cents"], int)
    assert data["tax_method_used"] in ("FLIGHT_HOURS", "TRIP_LEGS")
    assert data["status"] in ("DRAFT", "CERTIFIED", "DELIVERED")


def assert_crew_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["crew_role"] in ("CAPTAIN", "FIRST_OFFICER")
    assert data["status"] in ("HIRED", "IN_TRAINING", "QUALIFIED", "INACTIVE")
    assert isinstance(data["training_hours_accumulated"], (int, float))
    assert isinstance(data["duty_hours_7d"], (int, float))
    assert isinstance(data["duty_hours_28d"], (int, float))
    assert isinstance(data["flight_hours_total"], (int, float))


def assert_trip(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert data["trip_use"] in ("OWNER_USE", "CHARTER")
    assert isinstance(data["depart_icao"], str) and data["depart_icao"]
    assert isinstance(data["arrive_icao"], str) and data["arrive_icao"]
    assert isinstance(data["block_hours_est"], (int, float)) and data["block_hours_est"] > 0
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DECLINED", "SCHEDULED",
        "COMPLETED", "CANCELLED", "VOID",
    )


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["trip_id"], str) and data["trip_id"]
    assert isinstance(data["crew_member_id"], str) and data["crew_member_id"]
    assert data["duty_role"] in ("PIC", "SIC")
    assert isinstance(data["duty_hours"], (int, float)) and data["duty_hours"] > 0
    assert data["status"] in ("ASSIGNED", "RELEASED", "COMPLETED")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["rate_per_hour_cents"], int)
    assert data["status"] in ("QUOTED", "ENROLLED", "SUSPENDED", "CANCELLED")


def assert_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert isinstance(data["interval_hours"], (int, float))
    assert isinstance(data["due_at_aircraft_hours"], (int, float))
    assert data["status"] in ("FORECAST", "SCHEDULED", "COMPLETED")


def assert_filing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert data["filing_kind"] in ("INSURANCE_COI", "REGISTRATION", "OPS_SPECS_AMENDMENT")
    assert isinstance(data["authority"], str) and data["authority"]
    assert isinstance(data["reference_no"], str) and data["reference_no"]
    assert isinstance(data["valid_until"], str) and data["valid_until"]
    assert data["status"] in ("DRAFT", "FILED", "ACCEPTED", "REJECTED")


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert data["vendor_kind"] in ("HANGAR", "FUEL")
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert data["unit"] in ("MONTH", "GALLON")
    assert isinstance(data["rate_cents_per_unit"], int)
    assert data["status"] in ("DRAFT", "PROPOSED", "COUNTERED", "EXECUTED", "EXPIRED")
