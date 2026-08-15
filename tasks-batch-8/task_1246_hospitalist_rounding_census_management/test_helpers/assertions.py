"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert isinstance(data, dict), "entity payload must be a dict"
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_hospitalist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("specialty") in ("INTERNAL_MEDICINE", "FAMILY_MEDICINE", "ICU")
    assert data.get("employment_status") in ("ACTIVE", "ON_LEAVE", "INACTIVE")
    assert isinstance(data.get("max_census_cap"), int) and data["max_census_cap"] >= 1
    assert isinstance(data.get("night_eligible"), bool)
    assert isinstance(data.get("current_census"), int) and data["current_census"] >= 0
    assert isinstance(data.get("pending_offers"), int) and data["pending_offers"] >= 0
    assert isinstance(data.get("distribution_eligible"), bool)


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("mrn"), str) and data["mrn"]
    assert data.get("acuity") in ("HIGH", "MEDIUM", "LOW")
    assert data.get("admit_source") in ("ED", "DIRECT", "TRANSFER")
    assert data.get("stay_type") in ("INPATIENT", "OBSERVATION")
    assert is_iso8601_timestamp(data.get("admitted_at", ""))
    assert data.get("admission_status") in ("ADMITTED", "DISCHARGED")
    assert data.get("observation_status") in ("NONE", "OBS_ACTIVE", "OBS_CONVERTED", "OBS_CLOSED")
    assert isinstance(data.get("los_midnights"), int)
    assert isinstance(data.get("los_blocks"), int)
    assert isinstance(data.get("los_alert_flag"), bool)


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("hospitalist_id", ""))
    assert data.get("shift_type") in ("DAY", "NIGHT")
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data.get("state") in ("SCHEDULED", "ACTIVE", "CLOSED")


def assert_admission(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data.get("status") in ("QUEUED", "OFFERED", "ACCEPTED")
    assert isinstance(data.get("declined_hospitalist_ids"), list)


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("hospitalist_id", ""))
    assert data.get("status") in ("ACTIVE", "PENDING_TRANSFER", "CLOSED")
    assert isinstance(data.get("continuity_flag"), bool)
    assert is_iso8601_timestamp(data.get("assigned_at", ""))


def assert_discharge_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("ordering_hospitalist_id", ""))
    assert data.get("status") in ("PLANNED", "ORDERED", "EXECUTED")
    assert is_iso8601_timestamp(data.get("target_discharge_at", ""))


def assert_handoff(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("receiving_hospitalist_id", ""))
    assert isinstance(data.get("patient_ids"), list)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED")
    assert isinstance(data.get("required_patient_count"), int)
    assert isinstance(data.get("covered_patient_count"), int)
    assert isinstance(data.get("open_item_count"), int)


def assert_consult_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("requesting_hospitalist_id", ""))
    assert data.get("specialty") in (
        "CARDIOLOGY", "NEUROLOGY", "SURGERY", "INFECTIOUS_DISEASE", "NEPHROLOGY"
    )
    assert data.get("priority") in ("STAT", "URGENT", "ROUTINE")
    assert data.get("status") in (
        "OPEN", "ACKNOWLEDGED", "COMPLETED", "ESCALATED", "REOPENED", "CLOSED"
    )
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert is_iso8601_timestamp(data.get("sla_deadline", ""))
    assert isinstance(data.get("sla_breached"), bool)
    assert isinstance(data.get("escalation_count"), int)


def assert_encounter(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("hospitalist_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data.get("encounter_type") in (
        "ADMISSION_HCP", "SUBSEQUENT_VISIT", "DISCHARGE_DAY", "CONSULT_NOTE"
    )
    assert isinstance(data.get("occurred_on"), str)
    assert data.get("status") in ("RECORDED", "VOIDED")


def assert_productivity_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("hospitalist_id", ""))
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert data.get("status") in ("PROVISIONAL", "FINALIZED", "REOPENED")
    assert isinstance(data.get("encounter_count"), int)
    assert is_iso8601_timestamp(data.get("generated_at", ""))


def assert_coverage_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("window_date"), str)
    assert data.get("window_type") in ("NIGHT_PRIMARY", "NIGHT_CROSS_COVER")
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data.get("capacity"), int) and data["capacity"] >= 1
    assert isinstance(data.get("enrolled_hospitalist_ids"), list)
    assert isinstance(data.get("enrolled_count"), int)
    assert data.get("status") in ("OPEN", "FULL", "LOCKED", "CLOSED")
