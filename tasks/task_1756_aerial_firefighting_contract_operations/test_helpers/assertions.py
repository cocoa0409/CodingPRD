"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only_fields(data: dict):
    """Ledger-style records carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert data["agency"] in ("USFS", "CAL_FIRE")
    assert data["contract_type"] in ("EXCLUSIVE_USE", "CALL_WHEN_NEEDED")
    assert isinstance(data["daily_availability_rate_cents"], int)
    assert data["daily_availability_rate_cents"] > 0
    assert isinstance(data["flight_hour_rate_cents"], int)
    assert data["flight_hour_rate_cents"] > 0
    assert isinstance(data["min_daily_available_minutes"], int)
    assert data["min_daily_available_minutes"] > 0
    assert isinstance(data["season_flight_hour_cap_tenths"], int)
    assert data["season_flight_hour_cap_tenths"] > 0
    assert isinstance(data["acceptance_window_minutes"], int)
    assert data["acceptance_window_minutes"] > 0
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["season_billed_cents"], int)
    assert isinstance(data["season_flight_hours_tenths"], int)


def assert_aircraft(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["tank_capacity_gallons"], int)
    assert data["tank_capacity_gallons"] > 0
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert data["carding_status"] in ("UNCARDED", "CARDED", "SUSPENDED", "DECARDED")
    assert data.get("carded_until") is None or isinstance(data["carded_until"], str)


def assert_crew_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["crew_role"] in ("PIC", "SIC")
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert isinstance(data["qualified_aircraft_models"], list)
    assert data["carding_status"] in ("UNCARDED", "CARDED", "SUSPENDED")
    assert data["duty_status"] in ("AVAILABLE", "FATIGUE_HOLD")
    assert data.get("carded_until") is None or isinstance(data["carded_until"], str)


def assert_carding_inspection(data: dict):
    _assert_common_fields(data)
    subjects = [data.get("subject_aircraft_id"), data.get("subject_crew_member_id")]
    assert sum(1 for s in subjects if s) == 1, "exactly one subject must be set"
    assert is_iso8601_timestamp(data.get("scheduled_for", ""))
    assert isinstance(data["valid_days"], int) and data["valid_days"] > 0
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert data["result"] in ("PENDING", "PASSED", "FAILED")
    assert data.get("completed_at") is None or \
        is_iso8601_timestamp(data["completed_at"])


def assert_availability_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert is_iso8601_timestamp(data.get("available_start", ""))
    assert is_iso8601_timestamp(data.get("available_end", ""))
    assert data["status"] in ("OFFERED", "CONFIRMED", "UNAVAILABLE", "EXCUSED")
    assert data.get("excuse_reason") is None or \
        data["excuse_reason"] in ("MAINTENANCE", "CARDING", "WEATHER", "AGENCY_RELEASE")
    assert isinstance(data["available_minutes"], int)
    assert isinstance(data["availability_charge_cents"], int)


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["incident_number"], str) and data["incident_number"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["agency"] in ("USFS", "CAL_FIRE")
    assert data["priority"] in ("INITIAL_ATTACK", "EXTENDED_ATTACK")
    assert data["status"] in ("REPORTED", "ACTIVE", "CONTAINED", "CLOSED")


def assert_dispatch_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_number"], str) and data["order_number"]
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert isinstance(data["incident_id"], str) and data["incident_id"]
    assert isinstance(data["aircraft_quantity"], int)
    assert data["aircraft_quantity"] > 0
    assert data.get("required_model") is None or isinstance(data["required_model"], str)
    assert is_iso8601_timestamp(data.get("placed_at", ""))
    assert is_iso8601_timestamp(data.get("accept_deadline", ""))
    assert data["status"] in ("PLACED", "ACCEPTED", "PARTIALLY_FILLED", "FILLED",
                              "DECLINED", "CANCELLED", "CLOSED")
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data.get("decline_reason") is None or isinstance(data["decline_reason"], str)


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dispatch_order_id"], str) and data["dispatch_order_id"]
    assert isinstance(data["aircraft_id"], str) and data["aircraft_id"]
    assert isinstance(data["pilot_id"], str) and data["pilot_id"]
    assert is_iso8601_timestamp(data.get("planned_start", ""))
    assert is_iso8601_timestamp(data.get("planned_end", ""))
    assert data["status"] in ("ASSIGNED", "EN_ROUTE", "ON_INCIDENT", "RELEASED",
                              "DEMOBILIZED")
    assert is_iso8601_timestamp(data.get("assigned_at", ""))
    for ts_field in ("launched_at", "arrived_at", "released_at", "demobilized_at"):
        assert data.get(ts_field) is None or is_iso8601_timestamp(data[ts_field])
    assert data.get("release_reason") is None or \
        data["release_reason"] in ("AGENCY", "MECHANICAL", "FATIGUE")
    assert data.get("reload_turn_avg_minutes") is None or \
        isinstance(data["reload_turn_avg_minutes"], (int, float))
    assert isinstance(data["reload_sla_breach"], bool)


def assert_flight_log(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["assignment_id"], str) and data["assignment_id"]
    assert isinstance(data["pilot_id"], str) and data["pilot_id"]
    assert isinstance(data["logged_date"], str) and data["logged_date"]
    assert isinstance(data["hobbs_start"], (int, float))
    assert isinstance(data["hobbs_stop"], (int, float))
    assert data["hobbs_stop"] > data["hobbs_start"]
    assert isinstance(data["flight_hours_tenths"], int)
    assert data["flight_hours_tenths"] > 0
    assert isinstance(data["billable_cents"], int)


def assert_retardant_load(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assignment_id"], str) and data["assignment_id"]
    assert isinstance(data["gallons"], int) and data["gallons"] > 0
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert data.get("loaded_at") is None or is_iso8601_timestamp(data["loaded_at"])
    assert data.get("dropped_at") is None or is_iso8601_timestamp(data["dropped_at"])
    assert data["status"] in ("REQUESTED", "LOADED", "DROPPED")
    assert data.get("reload_turn_minutes") is None or \
        isinstance(data["reload_turn_minutes"], int)


def assert_crew_duty_day(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_member_id"], str) and data["crew_member_id"]
    assert isinstance(data["duty_date"], str) and data["duty_date"]
    assert data.get("duty_start") is None or is_iso8601_timestamp(data["duty_start"])
    assert isinstance(data["flown_tenths"], int) and data["flown_tenths"] >= 0
    assert isinstance(data["projected_tenths"], int) and data["projected_tenths"] >= 0


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert isinstance(data["period_start"], str) and data["period_start"]
    assert isinstance(data["period_end"], str) and data["period_end"]
    assert data["status"] in ("DRAFT", "SUBMITTED", "DISPUTED", "RECONCILED",
                              "PAID", "VOID")
    assert data["billing_basis"] in ("PROVISIONAL", "RECONCILED")
    for money_field in ("availability_subtotal_cents", "flight_subtotal_cents",
                        "penalty_cents", "net_cents"):
        assert isinstance(data[money_field], int), f"{money_field} must be int cents"
    assert data.get("submitted_by") is None or isinstance(data["submitted_by"], str)
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data.get("reconciled_by") is None or isinstance(data["reconciled_by"], str)
    assert data.get("dispute_reason") is None or isinstance(data["dispute_reason"], str)


def assert_invoice_line_item(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["invoice_id"], str) and data["invoice_id"]
    assert data["line_type"] in ("AVAILABILITY_DAY", "FLIGHT_DAY", "PENALTY")
    assert isinstance(data["reference_date"], str) and data["reference_date"]
    assert isinstance(data["source_ref_id"], str) and data["source_ref_id"]
    assert isinstance(data["carrier_qty"], int)
    assert isinstance(data["carrier_amount_cents"], int)
    assert data.get("agency_qty") is None or isinstance(data["agency_qty"], int)
    assert data.get("agency_amount_cents") is None or \
        isinstance(data["agency_amount_cents"], int)
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["mismatch_flag"], bool)


def assert_agency_record(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert isinstance(data["assignment_id"], str) and data["assignment_id"]
    assert isinstance(data["record_date"], str) and data["record_date"]
    assert isinstance(data["agency_flight_hours_tenths"], int)
    assert data["agency_flight_hours_tenths"] >= 0
    assert data.get("agency_available_minutes") is None or \
        isinstance(data["agency_available_minutes"], int)


def assert_season_billed_invariant(contract: dict, invoices: list):
    """season_billed_cents equals the sum of net_cents over invoices in
    SUBMITTED, DISPUTED, RECONCILED, or PAID."""
    counted = {"SUBMITTED", "DISPUTED", "RECONCILED", "PAID"}
    expected = sum(inv["net_cents"] for inv in invoices if inv["status"] in counted)
    assert contract["season_billed_cents"] == expected, (
        f"season_billed_cents {contract['season_billed_cents']} != "
        f"sum of in-set invoice nets {expected}"
    )


def assert_filled_count_invariant(order: dict, assignments: list):
    """filled_count equals the count of the order's assignments in
    ASSIGNED, EN_ROUTE, or ON_INCIDENT."""
    live = {"ASSIGNED", "EN_ROUTE", "ON_INCIDENT"}
    expected = sum(1 for a in assignments if a["status"] in live)
    assert order["filled_count"] == expected, (
        f"filled_count {order['filled_count']} != live assignment count {expected}"
    )
