"""Entity assertions and domain invariant checkers.

Per PRD section 2.4, top-level resources carry id/created_at/updated_at/version.
AssignmentCharge and TelematicsReading carry only id/created_at -- both updated_at
and version are absent on those two resources.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_equipment_class(data: dict):
    _assert_common_fields(data, "EquipmentClass")
    assert isinstance(data["class_code"], str) and data["class_code"]
    for f in ("daily_rate_cents", "external_daily_rate_cents", "weekend_multiplier_bp",
              "idle_day_multiplier_bp", "service_interval_hours",
              "idle_alert_utilization_bp", "expected_life_hours", "salvage_value_cents"):
        assert isinstance(data[f], int), f"EquipmentClass.{f} must be int"


def assert_equipment(data: dict):
    _assert_common_fields(data, "Equipment")
    assert isinstance(data["unit_tag"], str) and data["unit_tag"]
    assert is_valid_uuid(data.get("class_id", "")), "Equipment.class_id must be a UUID"
    assert data["ownership"] in ("OWNED", "RENTED")
    assert data["availability_status"] in (
        "IDLE", "RESERVED", "ON_RENT", "IN_TRANSIT", "DOWN", "DISPOSED")
    assert data["maintenance_status"] in ("SERVICE_OK", "SERVICE_DUE", "IN_SERVICE")
    assert isinstance(data["engine_hours_milli"], int)
    assert isinstance(data["hours_at_last_service_milli"], int)


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert isinstance(data["project_code"], str) and data["project_code"]
    assert isinstance(data["name"], str)
    assert data["status"] in ("OPEN", "SUSPENDED", "CLOSED")
    assert isinstance(data["equipment_budget_cents"], int)
    assert isinstance(data["billed_total_cents"], int)
    assert isinstance(data["active_assignment_count"], int)


def assert_assignment(data: dict):
    _assert_common_fields(data, "Assignment")
    assert is_valid_uuid(data.get("equipment_id", "")), "Assignment.equipment_id must be a UUID"
    assert is_valid_uuid(data.get("project_id", "")), "Assignment.project_id must be a UUID"
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("RESERVED", "ACTIVE", "SUSPENDED", "CLOSED", "CANCELLED")
    assert isinstance(data["billable_days"], int)
    assert isinstance(data["idle_days"], int)
    assert isinstance(data["engine_hours_billed_milli"], int)


def assert_assignment_charge(data: dict):
    """Append-only ledger row: id + created_at only, no updated_at/version."""
    _assert_append_only_fields(data, "AssignmentCharge")
    assert is_valid_uuid(data.get("assignment_id", "")), "AssignmentCharge.assignment_id must be a UUID"
    assert is_valid_uuid(data.get("project_id", "")), "AssignmentCharge.project_id must be a UUID"
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["own_cost_cents"], int)
    assert isinstance(data["rent_cost_cents"], int)
    assert data["cheaper_variant"] in ("OWN", "RENT", "TIE")


def assert_work_order(data: dict):
    _assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data.get("equipment_id", "")), "WorkOrder.equipment_id must be a UUID"
    assert data["kind"] in ("PREVENTIVE", "REPAIR")
    assert data["status"] in ("OPEN", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["trigger_hours_milli"], int)


def assert_mechanic(data: dict):
    _assert_common_fields(data, "Mechanic")
    assert isinstance(data["mechanic_code"], str) and data["mechanic_code"]
    assert isinstance(data["name"], str)
    assert data["status"] in ("AVAILABLE", "ON_JOB", "OFF_DUTY")
    assert is_valid_uuid(data.get("home_project_id", "")), "Mechanic.home_project_id must be a UUID"
    assert isinstance(data["active_work_order_count"], int)


def assert_transport_job(data: dict):
    _assert_common_fields(data, "TransportJob")
    assert is_valid_uuid(data.get("equipment_id", "")), "TransportJob.equipment_id must be a UUID"
    assert is_valid_uuid(data.get("from_project_id", "")), "TransportJob.from_project_id must be a UUID"
    assert is_valid_uuid(data.get("to_project_id", "")), "TransportJob.to_project_id must be a UUID"
    assert is_valid_uuid(data.get("lowboy_id", "")), "TransportJob.lowboy_id must be a UUID"
    assert isinstance(data["depart_at"], str)
    assert isinstance(data["arrive_at"], str)
    assert data["status"] in ("PLANNED", "EN_ROUTE", "DELIVERED", "CANCELLED")


def assert_lowboy(data: dict):
    _assert_common_fields(data, "Lowboy")
    assert isinstance(data["lowboy_code"], str) and data["lowboy_code"]
    assert data["status"] in ("AVAILABLE", "ON_Haul", "OUT_OF_SERVICE")
    assert isinstance(data["capacity_units"], int)


def assert_telematics_reading(data: dict):
    """Append-only reading: id + created_at only, no updated_at/version."""
    _assert_append_only_fields(data, "TelematicsReading")
    assert is_valid_uuid(data.get("equipment_id", "")), "TelematicsReading.equipment_id must be a UUID"
    assert isinstance(data["recorded_date"], str)
    assert isinstance(data["engine_hours_delta_milli"], int)
    assert isinstance(data["fuel_used_milliliters"], int)
    assert data["status"] in ("ACCEPTED", "VOIDED")


def assert_damage_report(data: dict):
    _assert_common_fields(data, "DamageReport")
    assert is_valid_uuid(data.get("equipment_id", "")), "DamageReport.equipment_id must be a UUID"
    assert is_valid_uuid(data.get("project_id", "")), "DamageReport.project_id must be a UUID"
    assert isinstance(data["description"], str)
    assert isinstance(data["abuse_flag"], bool)
    assert isinstance(data["line_items"], list)
    assert data["status"] in ("FILED", "ASSESSED", "DISPUTED", "CONFIRMED", "VOIDED")
