"""Entity assertions (PRD §2.4, §3.1–§3.8).

Each `assert_<entity>` verifies the response shape for the named entity using
the framework's generic UUID and ISO-8601 validators. The AcknowledgementReceipt
assertion deliberately omits `updated_at`/`version` because the receipt is
immutable by design (PRD §2.4).
"""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ─── Common field checks ─────────────────────────────────────────────────────


def assert_common_fields(data: dict) -> None:
    """PRD §2.4: id (UUID), created_at, updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def assert_minimal_audit_fields(data: dict) -> None:
    """PRD §2.4: AcknowledgementReceipt exposes only id + created_at (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ─── Patient (PRD §3.1) ──────────────────────────────────────────────────────


def assert_patient(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("mrn"), str) and data["mrn"], "mrn required"
    assert isinstance(data.get("full_name"), str) and data["full_name"], "full_name required"
    assert isinstance(data.get("date_of_birth"), str), "date_of_birth required"
    assert data.get("age_band") in {"NEONATE", "INFANT", "PEDIATRIC", "ADULT"}, (
        f"age_band must be one of NEONATE/INFANT/PEDIATRIC/ADULT, got {data.get('age_band')!r}"
    )
    assert isinstance(data.get("results_release_count"), int), "results_release_count must be int"
    assert isinstance(data.get("critical_incidents_count"), int), "critical_incidents_count must be int"


# ─── Clinician (PRD §3.1) ────────────────────────────────────────────────────


def assert_clinician(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("npi"), str) and data["npi"], "npi required"
    assert data.get("role_type") in {
        "ORDERING_PROVIDER", "PHLEBOTOMIST", "LAB_TECH", "LAB_DIRECTOR"
    }, f"role_type invalid: {data.get('role_type')!r}"
    assert isinstance(data.get("phone_e164"), str) and data["phone_e164"].startswith("+"), (
        f"phone_e164 must be E.164, got {data.get('phone_e164')!r}"
    )


# ─── LabOrder (PRD §3.2) ─────────────────────────────────────────────────────


def assert_lab_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", "")), "patient_id must be UUID"
    assert is_valid_uuid(data.get("ordering_clinician_id", "")), "ordering_clinician_id must be UUID"
    assert data.get("panel_code") in {"CMP", "CBC", "TROP", "GLUC"}, (
        f"panel_code invalid: {data.get('panel_code')!r}"
    )
    assert data.get("priority") in {"STAT", "ROUTINE"}, (
        f"priority invalid: {data.get('priority')!r}"
    )
    assert data.get("status") in {"DRAFT", "ACCESSIONED", "RESULTED", "CANCELLED"}, (
        f"status invalid: {data.get('status')!r}"
    )
    assert is_iso8601_timestamp(data.get("ordered_at", "")), (
        f"ordered_at must be ISO 8601, got {data.get('ordered_at')!r}"
    )
    assert isinstance(data.get("specimens_count"), int), "specimens_count must be int"
    assert isinstance(data.get("accessioned_count"), int), "accessioned_count must be int"
    assert isinstance(data.get("compliance_incident"), bool), "compliance_incident must be bool"


# ─── Specimen (PRD §3.3) ─────────────────────────────────────────────────────


def assert_specimen(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lab_order_id", "")), "lab_order_id must be UUID"
    assert is_valid_uuid(data.get("collector_clinician_id", "")), "collector_clinician_id must be UUID"
    assert data.get("container_code") in {"RED", "LAVENDER", "GREEN", "GRAY"}, (
        f"container_code invalid: {data.get('container_code')!r}"
    )
    assert data.get("status") in {"DRAFT", "COLLECTED", "IN_TRANSIT", "ACCESSIONED", "REJECTED"}, (
        f"status invalid: {data.get('status')!r}"
    )


# ─── Instrument (PRD §3.4) ───────────────────────────────────────────────────


def assert_instrument(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("instrument_code"), str) and data["instrument_code"], (
        "instrument_code required"
    )
    assert isinstance(data.get("analyte_panels_supported"), list), (
        "analyte_panels_supported must be list"
    )
    qc = data.get("qc_buffer_minutes")
    assert isinstance(qc, int) and 0 <= qc <= 60, (
        f"qc_buffer_minutes must be 0..60, got {qc!r}"
    )


# ─── InstrumentRun (PRD §3.4) ────────────────────────────────────────────────


def assert_instrument_run(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("instrument_id", "")), "instrument_id must be UUID"
    assert is_valid_uuid(data.get("specimen_id", "")), "specimen_id must be UUID"
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), (
        f"scheduled_start must be ISO 8601, got {data.get('scheduled_start')!r}"
    )
    assert is_iso8601_timestamp(data.get("scheduled_end", "")), (
        f"scheduled_end must be ISO 8601, got {data.get('scheduled_end')!r}"
    )
    assert data.get("status") in {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "FAILED"}, (
        f"status invalid: {data.get('status')!r}"
    )


# ─── Result (PRD §3.5) ───────────────────────────────────────────────────────


def assert_result(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("lab_order_id", "")), "lab_order_id must be UUID"
    assert is_valid_uuid(data.get("specimen_id", "")), "specimen_id must be UUID"
    assert is_valid_uuid(data.get("run_id", "")), "run_id must be UUID"
    assert data.get("analyte_code") in {"K", "GLUCOSE", "TROPONIN", "HGB"}, (
        f"analyte_code invalid: {data.get('analyte_code')!r}"
    )
    assert data.get("status") in {"PROVISIONAL", "RELEASED", "AMENDED", "INVALIDATED"}, (
        f"status invalid: {data.get('status')!r}"
    )


# ─── CriticalNotification (PRD §3.7) ─────────────────────────────────────────


def assert_critical_notification(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("result_id", "")), "result_id must be UUID"
    assert is_valid_uuid(data.get("recipient_clinician_id", "")), (
        "recipient_clinician_id must be UUID"
    )
    assert data.get("channel") in {"SMS", "PHONE"}, (
        f"channel invalid: {data.get('channel')!r}"
    )
    assert data.get("status") in {"PENDING", "SENT", "ACKNOWLEDGED", "ESCALATED", "VOIDED"}, (
        f"status invalid: {data.get('status')!r}"
    )
    assert isinstance(data.get("attempt_count"), int), "attempt_count must be int"


# ─── AcknowledgementReceipt (PRD §2.4, §3.7) ─────────────────────────────────


def assert_acknowledgement_receipt(data: dict) -> None:
    """PRD §2.4 — immutable: only id and created_at.

    PRD §2.4: "AcknowledgementReceipt rows expose only `id` and `created_at`;
    they carry no `updated_at` and no `version` field."
    """
    assert_minimal_audit_fields(data)
    assert is_valid_uuid(data.get("critical_notification_id", "")), (
        "critical_notification_id must be UUID"
    )
    assert is_valid_uuid(data.get("acknowledging_clinician_id", "")), (
        "acknowledging_clinician_id must be UUID"
    )
    assert data.get("ack_method") in {"SMS_REPLY", "IVR_KEYPRESS", "WEB_UI"}, (
        f"ack_method invalid: {data.get('ack_method')!r}"
    )
    attestation = data.get("attestation_text")
    assert isinstance(attestation, str) and 1 <= len(attestation) <= 500, (
        f"attestation_text must be 1..500 chars, got len={len(attestation) if isinstance(attestation, str) else 'N/A'}"
    )


# ─── RetestRequest (PRD §3.8) ────────────────────────────────────────────────


def assert_retest_request(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("original_result_id", "")), (
        "original_result_id must be UUID"
    )
    assert data.get("reason") in {"DELTA_CHECK_FAIL", "CLINICIAN_DOUBT", "INSTRUMENT_QC_FAIL"}, (
        f"reason invalid: {data.get('reason')!r}"
    )
    assert data.get("status") in {"REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"}, (
        f"status invalid: {data.get('status')!r}"
    )
