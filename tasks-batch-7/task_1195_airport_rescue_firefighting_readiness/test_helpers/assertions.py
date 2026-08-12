"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_airport_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["airport_code"], str) and data["airport_code"]
    assert data["certificated_index"] in ["A", "B", "C", "D", "E"]
    assert data["required_index_by_aircraft"] in ["A", "B", "C", "D", "E"]
    assert data["supported_index_by_equipment"] in ["A", "B", "C", "D", "E", "NONE"]
    assert data["supported_index_by_staffing"] in ["A", "B", "C", "D", "E", "NONE"]
    assert data["effective_index"] in ["A", "B", "C", "D", "E", "NONE"]
    assert data["index_compliance_status"] in [
        "COMPLIANT",
        "DOWNGRADED",
        "NONCOMPLIANT",
    ]


def assert_aircraft(data: dict):
    _assert_common(data)
    assert isinstance(data["model_name"], str)
    assert isinstance(data["length_ft"], (int, float)) and data["length_ft"] > 0
    assert (
        isinstance(data["avg_daily_departures"], (int, float))
        and data["avg_daily_departures"] >= 0
    )
    assert isinstance(data["in_scheduled_service"], bool)
    assert isinstance(data["qualifies_for_index"], bool)
    assert data["index_band"] in ["A", "B", "C", "D", "E"]


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["call_sign"], str) and data["call_sign"]
    assert (
        isinstance(data["water_capacity_gal"], (int, float))
        and data["water_capacity_gal"] > 0
    )
    assert (
        isinstance(data["dry_chem_capacity_lb"], (int, float))
        and data["dry_chem_capacity_lb"] >= 0
    )
    assert data["status"] in ["IN_SERVICE", "OUT_OF_SERVICE"]
    assert data["latest_readiness_result"] in ["PASS", "FAIL", "NONE"]


def assert_readiness_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert (
        isinstance(data["water_available_gal"], (int, float))
        and data["water_available_gal"] >= 0
    )
    assert (
        isinstance(data["dry_chem_available_lb"], (int, float))
        and data["dry_chem_available_lb"] >= 0
    )
    assert isinstance(data["discharge_system_ok"], bool)
    assert is_iso8601_timestamp(data.get("checked_at", ""))
    assert data["result"] in ["PASS", "FAIL"]


def assert_firefighter(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_no"], str) and data["employee_no"]
    assert isinstance(data["full_name"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    last = data.get("last_live_fire_completed_on")
    assert last is None or isinstance(last, str)
    assert isinstance(data["is_training_current"], bool)
    assert isinstance(data["is_deployable"], bool)


def assert_training_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("firefighter_id", ""))
    assert isinstance(data["completed_on"], str)
    assert data["drill_type"] in ["AIRCRAFT", "STRUCTURAL"]
    assert data["result"] in ["PASS", "FAIL"]


def assert_response_drill(data: dict):
    _assert_common(data)
    assert isinstance(data["runway_designator"], str)
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in ["SCHEDULED", "EXECUTED", "CERTIFIED", "FAILED"]
    assert data.get("outcome") in [None, "PASS", "FAIL"]


def assert_index_determination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("largest_aircraft_id", ""))
    assert data["new_certificated_index"] in ["A", "B", "C", "D", "E"]
    assert data["required_index"] in ["A", "B", "C", "D", "E"]
    assert isinstance(data["vehicle_requirement_met"], bool)
    assert isinstance(data["staffing_requirement_met"], bool)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_incident(data: dict):
    _assert_common(data)
    assert data["alert_level"] in ["ALERT_1", "ALERT_2", "ALERT_3"]
    assert isinstance(data["location"], str)
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data["status"] in ["REPORTED", "RESPONDING", "CONTROLLED", "CLOSED"]


def assert_mutual_aid_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["partner_airport_code"], str)
    assert data["max_alert_level"] in ["ALERT_1", "ALERT_2", "ALERT_3"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]


def assert_mutual_aid_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["units_requested"], int) and data["units_requested"] >= 1
    assert data["status"] in ["REQUESTED", "DEPLOYED", "RELEASED", "DECLINED"]


def assert_out_of_service_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", ""))
    assert isinstance(data["reason"], str)
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert data["status"] in ["OPEN", "RESTORED"]


def assert_index_downgrade_notification(data: dict):
    _assert_common(data)
    assert data["prior_index"] in ["A", "B", "C", "D", "E", "NONE"]
    assert data["downgraded_index"] in ["A", "B", "C", "D", "E", "NONE"]
    assert data["cause"] in ["EQUIPMENT", "STAFFING"]
    assert is_iso8601_timestamp(data.get("notified_at", ""))
    assert is_iso8601_timestamp(data.get("cure_deadline", ""))
    assert data["status"] in ["PENDING", "ACKNOWLEDGED", "RESOLVED", "OVERDUE"]


def assert_incident_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_id", ""))
    assert isinstance(data["author_user_id"], str)
    assert isinstance(data["narrative"], str)
    assert isinstance(data["agent_expenditure_lines"], list)
    assert isinstance(data["agent_expense_total_cents"], int)
    assert isinstance(data["review_cycle_count"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED"]


def assert_post_incident_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("incident_report_id", ""))
    assert isinstance(data["findings"], str)
    assert (
        isinstance(data["corrective_actions_open"], int)
        and data["corrective_actions_open"] >= 0
    )
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_faa_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data["inspection_year"], int)
    assert isinstance(data["scheduled_on"], str)
    assert data["status"] in [
        "SCHEDULED",
        "IN_PROGRESS",
        "FINDINGS_ISSUED",
        "CLOSED_PASS",
        "CLOSED_FAIL",
    ]
