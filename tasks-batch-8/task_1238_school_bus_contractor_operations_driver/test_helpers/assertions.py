"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, what: str):
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{what}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{what}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{what}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_append_only(data: dict, what: str):
    """Append-only resources carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{what}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{what} must not carry updated_at (append-only)"
    assert "version" not in data, f"{what} must not carry version (append-only)"


def assert_district(data: dict):
    _assert_common(data, "District")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_fuel_index_code"], str) and data["region_fuel_index_code"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["billing_dispute_window_days"], int)
    assert data["status"] in ["ACTIVE"]
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_contract(data: dict):
    _assert_common(data, "Contract")
    assert is_valid_uuid(data.get("district_id", "")), "Contract.district_id must be a UUID"
    assert isinstance(data["bid_reference"], str) and data["bid_reference"]
    for field in ("daily_rate_per_bus_cents", "school_days_per_year", "fuel_base_price_cents",
                  "fuel_escalation_trigger_pct", "fuel_escalation_share_pct",
                  "shortage_penalty_flat_cents", "shortage_penalty_per_student_minute_cents",
                  "assumed_minutes_per_missed_route", "monthly_cap_cents",
                  "charter_hourly_rate_cents", "charter_per_mile_cents", "amendment_seq"):
        assert isinstance(data[field], int), f"Contract.{field} must be an integer"
    assert data["penalty_mode"] in ["FLAT_PER_ROUTE", "PER_STUDENT_MINUTE"]
    assert data["status"] in ["DRAFT_BID", "SUBMITTED", "AWARDED", "ACTIVE",
                              "EXPIRED", "TERMINATED", "WITHDRAWN", "LOST"]


def assert_route(data: dict):
    _assert_common(data, "Route")
    assert is_valid_uuid(data.get("contract_id", "")), "Route.contract_id must be a UUID"
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["am_start_minute"], int)
    assert isinstance(data["am_end_minute"], int)
    assert data["am_end_minute"] > data["am_start_minute"]
    assert isinstance(data["student_count"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "ARCHIVED"]


def assert_driver(data: dict):
    _assert_common(data, "Driver")
    assert is_valid_uuid(data.get("primary_district_id", "")), "Driver.primary_district_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_class"] in ["A", "B"]
    assert isinstance(data["hourly_wage_cents"], int)
    assert data["status"] in ["APPLICANT", "SCREENING", "TRAINING", "TESTING",
                              "CERTIFIED", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["suspension_reason"] in [None, "DISCIPLINE", "CREDENTIAL_LAPSED"]
    for field in ("behind_wheel_minutes", "classroom_minutes", "test_fail_count",
                  "weekly_assigned_minutes"):
        assert isinstance(data[field], int), f"Driver.{field} must be an integer"


def assert_training_event(data: dict):
    _assert_append_only(data, "TrainingEvent")
    assert is_valid_uuid(data.get("driver_id", "")), "TrainingEvent.driver_id must be a UUID"
    assert data["category"] in ["CLASSROOM", "BEHIND_WHEEL", "SAFETY"]
    assert isinstance(data["minutes"], int) and data["minutes"] > 0


def assert_credential(data: dict):
    _assert_common(data, "Credential")
    assert is_valid_uuid(data.get("driver_id", "")), "Credential.driver_id must be a UUID"
    assert data["kind"] in ["CDL_B", "S_ENDORSEMENT", "FIRST_AID"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]


def assert_bus(data: dict):
    _assert_common(data, "Bus")
    assert is_valid_uuid(data.get("district_id", "")), "Bus.district_id must be a UUID"
    assert isinstance(data["fleet_number"], str) and data["fleet_number"]
    assert isinstance(data["capacity"], int)
    assert data["fuel_type"] in ["DIESEL", "GASOLINE", "ELECTRIC"]
    assert isinstance(data["mpg_x10"], int)
    assert isinstance(data["odometer_miles"], int)
    assert data["status"] in ["IN_SERVICE", "IN_SHOP", "GROUNDED", "DECOMMISSIONED"]


def assert_inspection(data: dict):
    _assert_common(data, "Inspection")
    assert is_valid_uuid(data.get("bus_id", "")), "Inspection.bus_id must be a UUID"
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "OVERDUE", "CANCELLED"]
    assert data["result"] in [None, "PASS", "FAIL"]


def assert_work_order(data: dict):
    _assert_common(data, "WorkOrder")
    assert is_valid_uuid(data.get("bus_id", "")), "WorkOrder.bus_id must be a UUID"
    assert data["category"] in ["PM", "REPAIR", "INSPECTION_FOLLOWUP"]
    assert data["status"] in ["OPEN", "DIAGNOSING", "WAITING_PARTS", "IN_REPAIR",
                              "COMPLETED", "CANCELLED"]


def assert_service_day(data: dict):
    _assert_common(data, "ServiceDay")
    assert is_valid_uuid(data.get("contract_id", "")), "ServiceDay.contract_id must be a UUID"
    assert data["status"] in ["SCHEDULED", "DISPATCH_OPEN", "LOCKED", "RECONCILED",
                              "INVOICED", "CANCELLED"]
    for field in ("required_routes", "covered_routes", "uncovered_routes",
                  "shortage_credit_cents"):
        assert isinstance(data[field], int), f"ServiceDay.{field} must be an integer"
    assert isinstance(data["shortage_flag"], bool)
    assert data["cancellation_reason"] in [None, "WEATHER", "DISTRICT_CLOSURE"]


def assert_assignment(data: dict):
    _assert_common(data, "Assignment")
    assert is_valid_uuid(data.get("service_day_id", "")), "Assignment.service_day_id must be a UUID"
    assert is_valid_uuid(data.get("route_id", "")), "Assignment.route_id must be a UUID"
    assert data["status"] in ["PLANNED", "CONFIRMED", "EN_ROUTE", "COMPLETED",
                              "NO_SHOW", "CANCELLED"]
    assert data["cancellation_reason"] in [None, "BUS_GROUNDED", "DRIVER_SUSPENDED",
                                           "CONTRACT_TERMINATED", "WEATHER", "OPS_CANCEL"]
    assert isinstance(data["is_doubled"], bool)
    assert isinstance(data["planned_start_minute"], int)
    assert isinstance(data["planned_end_minute"], int)
    assert isinstance(data["billable"], bool)


def assert_charter_trip(data: dict):
    _assert_common(data, "CharterTrip")
    assert is_valid_uuid(data.get("contract_id", "")), "CharterTrip.contract_id must be a UUID"
    assert data["status"] in ["REQUESTED", "QUOTED", "APPROVED", "SCHEDULED", "IN_PROGRESS",
                              "COMPLETED", "INVOICED", "DECLINED", "CANCELLED", "EXPIRED"]
    assert isinstance(data["pickup_minute"], int)
    assert isinstance(data["return_minute"], int)
    assert data["return_minute"] > data["pickup_minute"]
    assert isinstance(data["estimated_hours_x10"], int)
    assert isinstance(data["estimated_miles"], int)
    assert isinstance(data["passenger_count"], int)


def assert_fuel_price_entry(data: dict):
    _assert_append_only(data, "FuelPriceEntry")
    assert is_valid_uuid(data.get("district_id", "")), "FuelPriceEntry.district_id must be a UUID"
    assert isinstance(data["effective_month"], str) and len(data["effective_month"]) == 7
    assert isinstance(data["avg_price_cents_per_gallon"], int)


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("contract_id", "")), "Invoice.contract_id must be a UUID"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["status"] in ["DRAFT", "ISSUED", "DISPUTED", "PAID", "WRITTEN_OFF"]
    for field in ("bus_lines_cents", "charter_lines_cents", "shortage_credit_cents",
                  "fuel_adjustment_cents", "total_cents", "dispute_count"):
        assert isinstance(data[field], int), f"Invoice.{field} must be an integer"


def assert_incident(data: dict):
    _assert_common(data, "Incident")
    assert is_valid_uuid(data.get("district_id", "")), "Incident.district_id must be a UUID"
    assert data["category"] in ["ACCIDENT", "BEHAVIOR", "MECHANICAL", "MEDICAL"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "RETURNED_FOR_INFO", "CLOSED"]
    assert isinstance(data["student_discipline_flag"], bool)
    assert isinstance(data["sla_breached"], bool)


def assert_ridership_report(data: dict):
    _assert_append_only(data, "RidershipReport")
    assert is_valid_uuid(data.get("assignment_id", "")), "RidershipReport.assignment_id must be a UUID"
    assert isinstance(data["boardings"], int)
    assert isinstance(data["alightings"], int)
    assert isinstance(data["minutes_late"], int)
    assert isinstance(data["on_time"], bool)
    assert isinstance(data["student_minutes_late"], int)


def assert_coverage_invariant(day: dict):
    """required_routes == covered_routes + uncovered_routes must hold on any day."""
    assert day["required_routes"] == day["covered_routes"] + day["uncovered_routes"], (
        f"coverage not conserved: {day['required_routes']} != "
        f"{day['covered_routes']} + {day['uncovered_routes']}"
    )
    assert day["shortage_flag"] == (day["uncovered_routes"] > 0)


def assert_deposit_split_invariant(charter: dict):
    """cancel_fee_cents + refund_cents == deposit_cents on a cancelled charter."""
    assert charter["cancel_fee_cents"] + charter["refund_cents"] == charter["deposit_cents"], (
        f"deposit not conserved: {charter['cancel_fee_cents']} + "
        f"{charter['refund_cents']} != {charter['deposit_cents']}"
    )
