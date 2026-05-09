"""Per-entity structural assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


_VALID_ROOM_TYPES = {"GENERAL_OR", "CARDIAC_OR", "NEURO_OR", "OBSTETRIC_OR"}
_VALID_SPECIALTIES = {"GENERAL", "CARDIAC", "NEURO", "OBSTETRIC"}
_VALID_STAFF_QUALIFICATIONS = {"GENERAL", "CARDIAC", "NEURO", "OBSTETRIC", "PEDIATRIC"}
_VALID_STAFF_ROLES = {"ANESTHESIOLOGIST", "SCRUB_NURSE", "CIRCULATING_NURSE"}
_VALID_ROLES_IN_CASE = {"LEAD_ANESTHESIOLOGIST", "SCRUB_NURSE", "CIRCULATING_NURSE"}
_VALID_CASE_PRIORITY = {"ROUTINE", "URGENT", "EMERGENCY"}
_VALID_CASE_STATUS = {
    "REQUESTED",
    "APPROVED",
    "REJECTED",
    "SCHEDULED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "PREEMPTED",
}
_VALID_ASSIGNMENT_STATUS = {"RESERVED", "CONFIRMED", "COMPLETED", "RELEASED", "PREEMPTED"}
_VALID_STERILIZATION_STATUS = {
    "SOILED",
    "IN_STERILIZATION",
    "CLEAN_STERILIZED",
    "CHECKED_OUT",
    "EXPIRED",
}
_VALID_BOOKING_STATUS = {"RESERVED", "CHECKED_OUT", "RETURNED_SOILED", "RELEASED", "PREEMPTED"}
_VALID_SETTLEMENT_STATUS = {"DRAFT", "PRE_AUTHORIZED", "ITEMIZED", "SETTLED", "REFUNDED"}


def _assert_common_fields(data: dict, entity_label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label} id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label} created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label} updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label} version must be int >= 1"
    )


def assert_operating_room(data: dict):
    _assert_common_fields(data, "OperatingRoom")
    assert isinstance(data["room_number"], str) and len(data["room_number"]) > 0
    assert data["room_type"] in _VALID_ROOM_TYPES
    assert isinstance(data["equipment_list"], list)
    assert data["specialty_required"] in _VALID_SPECIALTIES
    assert isinstance(data["turnover_buffer_minutes"], int) and data["turnover_buffer_minutes"] >= 0
    assert isinstance(data["hourly_rate"], (int, float)) and data["hourly_rate"] >= 0
    assert_cost_precision(data["hourly_rate"])


def assert_surgical_case(data: dict):
    _assert_common_fields(data, "SurgicalCase")
    assert isinstance(data["patient_id"], str) and len(data["patient_id"]) > 0
    assert isinstance(data["surgery_type"], str) and len(data["surgery_type"]) > 0
    assert data["specialty_required"] in _VALID_SPECIALTIES
    assert data["priority"] in _VALID_CASE_PRIORITY
    assert isinstance(data["pre_op_assessment_attached"], bool)
    assert isinstance(data["informed_consent_verified"], bool)
    assert data["status"] in _VALID_CASE_STATUS
    if data.get("implant_cost_estimate") is not None:
        assert_cost_precision(data["implant_cost_estimate"])
        assert data["implant_cost_estimate"] >= 0


def assert_staff_member(data: dict):
    _assert_common_fields(data, "StaffMember")
    assert isinstance(data["staff_name"], str)
    assert data["staff_role"] in _VALID_STAFF_ROLES
    assert isinstance(data["qualifications"], list)
    for q in data["qualifications"]:
        assert q in _VALID_STAFF_QUALIFICATIONS, f"unknown qualification: {q}"
    assert_cost_precision(data["hourly_rate"])
    assert isinstance(data["shift_start_minute"], int)
    assert isinstance(data["shift_end_minute"], int)
    assert data["shift_end_minute"] > data["shift_start_minute"]
    assert isinstance(data["on_call"], bool)
    assert isinstance(data["planned_workload_minutes"], int)
    assert isinstance(data["actual_workload_minutes"], int)
    assert data["planned_workload_minutes"] >= 0
    assert data["actual_workload_minutes"] >= 0


def assert_case_assignment(data: dict):
    _assert_common_fields(data, "CaseAssignment")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["staff_id"])
    assert data["role_in_case"] in _VALID_ROLES_IN_CASE
    assert isinstance(data["assigned_start_minute"], int)
    assert isinstance(data["assigned_end_minute"], int)
    assert data["assigned_end_minute"] > data["assigned_start_minute"]
    assert data["status"] in _VALID_ASSIGNMENT_STATUS


def assert_instrument_set(data: dict):
    _assert_common_fields(data, "InstrumentSet")
    assert isinstance(data["set_name"], str)
    assert data["specialty"] in _VALID_SPECIALTIES
    assert data["sterilization_status"] in _VALID_STERILIZATION_STATUS
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0


def assert_instrument_booking(data: dict):
    _assert_common_fields(data, "InstrumentBooking")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["instrument_set_id"])
    assert data["status"] in _VALID_BOOKING_STATUS


def assert_settlement(data: dict):
    _assert_common_fields(data, "Settlement")
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in _VALID_SETTLEMENT_STATUS
    if data.get("estimated_total_amount") is not None:
        assert_cost_precision(data["estimated_total_amount"])
    if data.get("final_total_amount") is not None:
        assert_cost_precision(data["final_total_amount"])
    assert isinstance(data["line_items"], list)
    assert isinstance(data["insurance_split"], list)
    assert isinstance(data["per_payer_amounts"], list)
    assert_cost_precision(data["implant_cost"])
    assert_cost_precision(data["refund_amount"])


def assert_audit_entry(data: dict):
    """AuditEntry is append-only — has only id + created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "AuditEntry id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "AuditEntry created_at must be ISO 8601"
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["entity_type"], str)
    assert is_valid_uuid(data["entity_id"]) or isinstance(data["entity_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["payload"], dict)
    assert isinstance(data["occurred_at_minute"], int)
