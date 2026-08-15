"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

LOCATION_TYPES = ["WARD", "ICU", "ED", "OR", "IMAGING", "DISCHARGE_LOUNGE", "OTHER"]
EQUIPMENT_TYPES = ["WHEELCHAIR", "STRETCHER", "BARIATRIC_STRETCHER"]
REQUIRED_EQUIPMENT = ["PORTER_ONLY"] + EQUIPMENT_TYPES
PRIORITIES = ["ROUTINE", "URGENT", "STAT"]
ISOLATION_PRECAUTIONS = ["NONE", "CONTACT", "DROPLET", "AIRBORNE"]
REQUEST_STATUSES = ["QUEUED", "ASSIGNED", "AT_PICKUP", "IN_TRANSIT",
                    "COMPLETED", "CANCELLED", "SUPERSEDED"]
SLA_POSTURES = ["ON_TRACK", "AT_RISK", "BREACHED"]
OFFER_STATUSES = ["PENDING", "ACCEPTED", "DECLINED", "SUPERSEDED", "EXPIRED"]
ASSET_STATUSES = ["AVAILABLE", "RESERVED", "IN_USE", "AWAITING_CLEANING",
                  "IN_CLEANING", "OUT_OF_SERVICE"]
TRANSPORTER_STATUSES = ["OFF_SHIFT", "ON_SHIFT", "SUSPENDED"]
CLEANING_TASK_TYPES = ["STANDARD", "DEEP"]
CLEANING_TASK_STATUSES = ["PENDING", "IN_PROGRESS", "AWAITING_VERIFICATION", "VERIFIED"]
SHIFT_STATUSES = ["PLANNED", "CANCELLED"]
DAY_TYPES = ["WEEKDAY", "WEEKEND"]
DELAY_RECORD_KINDS = ["SLA_BREACH", "APPOINTMENT_LATE"]
DELAY_CAUSE_CODES = ["NO_TRANSPORTER", "NO_EQUIPMENT", "CLEANING_BACKLOG",
                     "PATIENT_NOT_READY", "SYSTEM", "OTHER"]
DELAY_RECORDED_VIA = ["SWEEP", "COMPLETION"]


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer")


def assert_location(data: dict):
    _assert_common_fields(data, "Location")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["location_type"] in LOCATION_TYPES
    assert isinstance(data["zone_code"], str)


def assert_travel_edge(data: dict):
    _assert_common_fields(data, "TravelEdge")
    assert is_valid_uuid(data.get("from_location_id", ""))
    assert is_valid_uuid(data.get("to_location_id", ""))
    assert isinstance(data["base_minutes"], int) and data["base_minutes"] > 0
    assert isinstance(data["airborne_minutes"], int) and data["airborne_minutes"] > 0


def assert_transporter(data: dict):
    _assert_common_fields(data, "Transporter")
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("home_location_id", ""))
    assert isinstance(data["certified_equipment"], list)
    for cert in data["certified_equipment"]:
        assert cert in EQUIPMENT_TYPES
    assert isinstance(data["oxygen_certified"], bool)
    assert isinstance(data["isolation_certified"], bool)
    assert data["status"] in TRANSPORTER_STATUSES
    assert is_valid_uuid(data.get("current_location_id", ""))


def assert_equipment_asset(data: dict):
    _assert_common_fields(data, "EquipmentAsset")
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["equipment_type"] in EQUIPMENT_TYPES
    assert data["status"] in ASSET_STATUSES
    assert is_valid_uuid(data.get("current_location_id", ""))
    assert isinstance(data["isolation_contaminated"], bool)


def assert_transport_request(data: dict):
    _assert_common_fields(data, "TransportRequest")
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert is_valid_uuid(data.get("origin_location_id", ""))
    assert is_valid_uuid(data.get("destination_location_id", ""))
    assert data["priority"] in PRIORITIES
    assert data["required_equipment"] in REQUIRED_EQUIPMENT
    assert isinstance(data["oxygen_required"], bool)
    assert data["isolation_precaution"] in ISOLATION_PRECAUTIONS
    assert isinstance(data["requested_by"], str) and data["requested_by"]
    assert data["status"] in REQUEST_STATUSES
    assert data["sla_posture"] in SLA_POSTURES
    for counter in ("escalation_count", "decline_count", "release_count",
                    "offer_seq_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"TransportRequest.{counter} must be a non-negative integer")
    assert isinstance(data["excluded_transporter_ids"], list)
    for nullable in ("assigned_transporter_id", "assigned_equipment_id",
                     "duplicate_of_id", "committed_eta_minutes", "response_minutes",
                     "at_pickup_at", "picked_up_at", "completed_at", "closed_at",
                     "cancel_reason", "scheduled_pickup_time",
                     "appointment_deadline"):
        assert nullable in data, f"TransportRequest.{nullable} must be present (null allowed)"


def assert_dispatch_offer(data: dict):
    _assert_common_fields(data, "DispatchOffer")
    assert is_valid_uuid(data.get("transport_request_id", ""))
    assert is_valid_uuid(data.get("transporter_id", ""))
    assert data["status"] in OFFER_STATUSES
    assert isinstance(data["offer_seq"], int) and data["offer_seq"] >= 1
    assert isinstance(data["estimated_travel_minutes"], int)
    assert "responded_at" in data


def assert_cleaning_task(data: dict):
    _assert_common_fields(data, "CleaningTask")
    assert is_valid_uuid(data.get("equipment_asset_id", ""))
    assert is_valid_uuid(data.get("transport_request_id", ""))
    assert data["task_type"] in CLEANING_TASK_TYPES
    assert data["status"] in CLEANING_TASK_STATUSES
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    for nullable in ("started_at", "finished_at", "verified_at",
                     "performed_by", "verified_by"):
        assert nullable in data, f"CleaningTask.{nullable} must be present (null allowed)"


def assert_staffing_shift(data: dict):
    _assert_common_fields(data, "StaffingShift")
    assert is_valid_uuid(data.get("transporter_id", ""))
    assert is_iso8601_timestamp(data.get("shift_start", ""))
    assert is_iso8601_timestamp(data.get("shift_end", ""))
    assert data["status"] in SHIFT_STATUSES


def assert_demand_curve(data: dict):
    _assert_common_fields(data, "DemandCurve")
    assert data["day_type"] in DAY_TYPES
    assert isinstance(data["hour_block"], int) and 0 <= data["hour_block"] <= 23
    assert data["priority"] in PRIORITIES
    assert data["expected_requests"] >= 0
    assert isinstance(data["mean_service_minutes"], int) and data["mean_service_minutes"] > 0


def assert_delay_record(data: dict):
    """DelayRecord is deliberately lighter: only id and created_at are
    system-managed; updated_at and version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "DelayRecord.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "DelayRecord.created_at must be ISO 8601")
    assert "updated_at" not in data, "DelayRecord must not carry updated_at"
    assert "version" not in data, "DelayRecord must not carry version"
    assert is_valid_uuid(data.get("transport_request_id", ""))
    assert data["record_kind"] in DELAY_RECORD_KINDS
    assert isinstance(data["delay_minutes"], int)
    assert isinstance(data["impact_minutes"], int)
    assert data["cause_code"] in DELAY_CAUSE_CODES
    assert data["recorded_via"] in DELAY_RECORDED_VIA
