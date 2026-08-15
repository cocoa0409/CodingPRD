"""Entity assertions and domain invariant helpers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_patient(data: dict):
    _assert_common(data, "patient")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]


def assert_referral_order(data: dict):
    _assert_common(data, "referral_order")
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["requested_study_type"] in (
        "PSG_DIAGNOSTIC", "HST", "SPLIT_NIGHT", "TITRATION_PAP")
    assert data["priority"] in ("ROUTINE", "STAT")
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert data["status"] in (
        "RECEIVED", "AUTH_IN_PROGRESS", "AUTHORIZED", "AUTH_DENIED",
        "SCHEDULED", "NEEDS_PROVIDER_REVIEW", "FULFILLED", "CANCELLED",
        "EXPIRED")


def assert_authorization(data: dict):
    _assert_common(data, "authorization")
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["approved_nights"], int)
    assert 1 <= data["approved_nights"] <= 2
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED", "EXPIRED", "WITHDRAWN")


def assert_bed(data: dict):
    _assert_common(data, "bed")
    assert isinstance(data["room_label"], str) and data["room_label"]
    assert isinstance(data["titration_capable"], bool)
    assert isinstance(data["is_active"], bool)


def assert_technologist(data: dict):
    _assert_common(data, "technologist")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential"] in ("RPSGT", "CPSGT")
    assert isinstance(data["is_active"], bool)


def assert_scorer(data: dict):
    _assert_common(data, "scorer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential"] in ("RPSGT", "RST")
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["reliability_pool"], bool)
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["consecutive_nonconcordant"], int)
    assert data["consecutive_nonconcordant"] >= 0
    assert data["reliability_status"] in (
        "PROVISIONAL", "CONSISTENT", "WATCH", "REMEDIATION")


def assert_physician(data: dict):
    _assert_common(data, "physician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["board_certified"], bool)
    assert isinstance(data["is_active"], bool)


def assert_staffing_assignment(data: dict):
    _assert_common(data, "staffing_assignment")
    assert is_valid_uuid(data.get("technologist_id", ""))
    assert isinstance(data["shift_date"], str)
    assert isinstance(data["patient_capacity"], int)
    assert 1 <= data["patient_capacity"] <= 4
    assert data["status"] in ("PLANNED", "CONFIRMED", "CANCELLED")


def assert_sleep_study(data: dict):
    _assert_common(data, "sleep_study")
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert data["study_type"] in (
        "PSG_DIAGNOSTIC", "HST", "SPLIT_NIGHT", "TITRATION_PAP")
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "SCORING_QUEUED", "SCORING_IN_PROGRESS",
        "SCORED", "INTERPRETATION_IN_PROGRESS", "INTERPRETED",
        "REPORT_FINALIZED", "NO_SHOW", "CANCELLED", "TECHNICAL_FAILURE")
    if data["study_type"] == "HST":
        assert data.get("bed_id") is None, "HST studies must not carry a bed"
    else:
        assert is_valid_uuid(data.get("bed_id", "")), \
            "in-lab studies must carry a bed"


def assert_scoring_task(data: dict):
    _assert_common(data, "scoring_task")
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("scorer_id", ""))
    assert data["assignment_kind"] in ("PRIMARY", "RELIABILITY_RESCORE")
    assert data["status"] in (
        "ASSIGNED", "IN_PROGRESS", "SUBMITTED", "ACCEPTED",
        "RETURNED_FOR_REVISION", "RECALLED")


def assert_interpretation_report(data: dict):
    _assert_common(data, "interpretation_report")
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("physician_id", ""))
    assert is_valid_uuid(data.get("primary_scoring_task_id", ""))
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert isinstance(data["addendum_count"], int) and data["addendum_count"] >= 0
    assert data["status"] in (
        "DRAFT", "SIGNED", "FINALIZED", "ADDENDUM_OPEN", "SUPERSEDED")
    if data["status"] in ("SIGNED", "FINALIZED", "ADDENDUM_OPEN"):
        assert data["severity"] in ("NORMAL", "MILD", "MODERATE", "SEVERE")
        assert isinstance(data["sla_breached"], bool)


def assert_therapy_prescription(data: dict):
    _assert_common(data, "therapy_prescription")
    assert is_valid_uuid(data.get("report_id", ""))
    assert is_valid_uuid(data.get("study_id", ""))
    assert data["device_type"] in ("CPAP", "APAP", "BIPAP")
    assert data["mask_type"] in ("NASAL", "FULL_FACE", "NASAL_PILLOWS")
    assert data["status"] in (
        "DRAFT", "ORDERED", "FULFILLED", "CANCELLED", "SUPERSEDED")


def assert_dme_order(data: dict):
    _assert_common(data, "dme_order")
    assert is_valid_uuid(data.get("prescription_id", ""))
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert data["status"] in (
        "DISPATCHED", "DELIVERED", "DECLINED", "CANCELLED",
        "FOLLOW_UP_PASSED", "ADHERENCE_REVIEW", "FOLLOW_UP_RESOLVED")


def assert_inter_rater_case(data: dict):
    _assert_common(data, "inter_rater_case")
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("primary_task_id", ""))
    assert is_valid_uuid(data.get("rescore_task_id", ""))
    assert data["status"] in ("OPEN", "ADJUDICATED")


def assert_index_precision(value: float, label: str):
    """Respiratory indexes are pinned to 1 decimal place, round-half-up."""
    assert abs(value * 10 - round(value * 10)) < 1e-9, (
        f"{label} must carry exactly 1 decimal place, got {value}")


def assert_agreement_precision(value: float, label: str):
    """Inter-rater agreement metrics are pinned to 2 decimal places."""
    assert abs(value * 100 - round(value * 100)) < 1e-9, (
        f"{label} must carry exactly 2 decimal places, got {value}")
