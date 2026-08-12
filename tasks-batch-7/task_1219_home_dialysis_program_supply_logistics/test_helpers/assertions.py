"""Entity assertions and domain invariant checkers (PRD sections 2.2–2.4)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["review_cadence_treatments"], int)
    assert data["review_cadence_treatments"] >= 1
    assert isinstance(data["max_missed_log_streak"], int)
    assert data["max_missed_log_streak"] >= 1
    assert 0 < data["waste_ratio_alert_threshold"] <= 1
    assert isinstance(data["supply_catalog"], list)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["prescription_treatments_per_week"], int)
    assert 1 <= data["prescription_treatments_per_week"] <= 7
    assert isinstance(data["prescription_units_per_treatment"], int)
    assert data["prescription_units_per_treatment"] >= 1
    assert data["program_status"] in (
        "TRAINING", "ACTIVE_HOME", "SUSPENDED", "TRANSITIONED_OUT")
    assert data["posture"] in ("NOT_READY", "HOME_READY", "AT_RISK", "BLOCKED")
    assert isinstance(data["ever_home_ready"], bool)
    assert isinstance(data["retraining_required"], bool)
    assert isinstance(data["waste_alert_active"], bool)
    assert isinstance(data["storage_cap_units"], int)
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["missed_log_streak"], int)
    assert isinstance(data["no_show_count"], int)


def assert_training_attempt(data: dict):
    _assert_common(data)
    assert data["module_code"] in (
        "WATER_HANDLING", "MACHINE_OPERATION", "ASEPTIC_TECHNIQUE",
        "EMERGENCY_RESPONSE", "SUPPLY_STORAGE")
    assert isinstance(data["score_pct"], int) and 0 <= data["score_pct"] <= 100
    assert isinstance(data["is_passing"], bool)
    assert data["status"] in ("RECORDED", "SIGNED_OFF")


def assert_home_assessment(data: dict):
    _assert_common(data)
    assert data["assessment_kind"] in ("INITIAL", "REASSESSMENT", "POST_MODIFICATION")
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["storage_cap_units"], int)
    assert data["status"] in (
        "SUBMITTED", "ACCEPTED", "REMEDIATION_REQUIRED", "SUPERSEDED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["work_type"] in ("PLUMBING", "ELECTRICAL", "STORAGE_BUILDOUT")
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "COMPLETED", "INSPECTED_PASS",
        "INSPECTED_FAIL", "CANCELLED")


def assert_machine(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "IN_STOCK", "ASSIGNED", "UNDER_MAINTENANCE", "DECOMMISSIONED")
    assert isinstance(data["total_runtime_hours"], (int, float))
    assert isinstance(data["runtime_hours_at_last_service"], (int, float))
    assert isinstance(data["maintenance_due"], bool)


def assert_maintenance_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in ("PREVENTIVE", "REPAIR", "DECONTAMINATION")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_backup_plan(data: dict):
    _assert_common(data)
    assert data["plan_mode"] in ("IN_CENTER_CHAIR", "BACKUP_MACHINE", "BOTH")
    assert data["status"] in ("ACTIVE", "EXPIRED", "SUPERSEDED", "CLOSED")


def assert_supply_order(data: dict):
    _assert_common(data)
    assert data["order_status"] in (
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "CLOSED",
        "SUPERSEDED", "CANCELLED")
    assert data["fulfillment_status"] in (
        "UNFULFILLED", "PARTIALLY_DELIVERED", "DELIVERED")
    assert isinstance(data["provisional_total_units"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["handling_fee_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["grand_total_cents"], int)
    assert isinstance(data["delivered_units_total"], int)


def assert_delivery_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "DELIVERED", "FAILED", "CANCELLED")


def assert_treatment_log(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "REVIEWED", "FLAGGED")
    assert isinstance(data["consumption_units"], int)
    assert isinstance(data["duration_minutes"], int)


def assert_clinical_review(data: dict):
    _assert_common(data)
    assert data["due_reason"] in ("CADENCE", "ESCALATION")
    assert data["status"] in ("PENDING", "SIGNED_OFF", "ESCALATED")


def assert_chair(data: dict):
    _assert_common(data)
    assert isinstance(data["chair_code"], str)
    assert isinstance(data["in_service"], bool)


def assert_slot_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_waste_return_record(data: dict):
    _assert_common(data)
    assert data["record_type"] in ("WASTE", "RETURN")
    assert data["status"] in ("REPORTED", "VERIFIED", "CREDITED", "REJECTED")
    assert isinstance(data["total_units"], int)
    assert isinstance(data["credit_cents"], int)


def assert_transition_record(data: dict):
    _assert_common(data)
    assert data["direction"] in ("HOME_TO_CENTER", "CENTER_TO_HOME")
    assert data["reason_code"] in (
        "PATIENT_CHOICE", "MEDICAL_COMPLICATION", "SUPPLY_FAILURE",
        "MACHINE_FAILURE", "HOME_UNSUITABLE", "TRAINING_INCOMPLETE",
        "NON_ADHERENCE")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DENIED", "ACTIVE", "COMPLETED", "REVERSED")


def assert_envelope_success(resp_json: dict):
    """PRD 2.2 success envelope shape."""
    assert "meta" in resp_json, "meta present"
    assert resp_json["meta"].get("api_request_id"), "api_request_id non-empty"
    assert is_iso8601_timestamp(resp_json["meta"].get("api_request_timestamp", "")), \
        "api_request_timestamp must be ISO 8601"
    assert resp_json.get("response_type") in ("object", "array")
    assert "data" in resp_json


def assert_envelope_error(resp_json: dict):
    """PRD 2.2 error envelope shape."""
    assert resp_json.get("response_type") == "error"
    assert resp_json["data"].get("error_id"), "error_id non-empty"
    assert resp_json["data"].get("message"), "message non-empty"
    assert "meta" in resp_json
