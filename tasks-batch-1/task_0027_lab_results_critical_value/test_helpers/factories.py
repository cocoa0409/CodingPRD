"""Payload factories — one per input-bearing endpoint (PRD §3.1–§3.9).

Every factory accepts **overrides so tests can dial specific values (e.g., the
boundary test that needs numeric_value=6.00 exactly). Required fields must be
supplied either as positional/keyword args or via overrides.
"""
from typing import Optional


# ─── Patient (PRD §3.1) ──────────────────────────────────────────────────────


def create_patient_payload(
    mrn: str = "MRN-AAA001",
    full_name: str = "Test Patient",
    date_of_birth: str = "1980-01-01",
    **overrides,
) -> dict:
    payload = {
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    }
    payload.update(overrides)
    return payload


# ─── Clinician (PRD §3.1) ────────────────────────────────────────────────────


def create_clinician_payload(
    npi: str,
    full_name: str,
    role_type: str,
    phone_e164: str,
    backup_clinician_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "npi": npi,
        "full_name": full_name,
        "role_type": role_type,
        "phone_e164": phone_e164,
    }
    if backup_clinician_id is not None:
        payload["backup_clinician_id"] = backup_clinician_id
    payload.update(overrides)
    return payload


# ─── LabOrder (PRD §3.2) ─────────────────────────────────────────────────────


def create_lab_order_payload(
    ordering_clinician_id: str,
    panel_code: str = "CMP",
    priority: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "ordering_clinician_id": ordering_clinician_id,
        "panel_code": panel_code,
    }
    if priority is not None:
        payload["priority"] = priority
    payload.update(overrides)
    return payload


# ─── Specimen (PRD §3.3) ─────────────────────────────────────────────────────


def create_specimen_payload(
    collector_clinician_id: str,
    container_code: str = "GREEN",
    **overrides,
) -> dict:
    payload = {
        "collector_clinician_id": collector_clinician_id,
        "container_code": container_code,
    }
    payload.update(overrides)
    return payload


def reject_specimen_payload(reject_reason: str = "HEMOLYZED", **overrides) -> dict:
    payload = {"reject_reason": reject_reason}
    payload.update(overrides)
    return payload


# ─── Instrument & InstrumentRun (PRD §3.4) ───────────────────────────────────


def create_instrument_payload(
    instrument_code: str,
    analyte_panels_supported: list,
    qc_buffer_minutes: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "instrument_code": instrument_code,
        "analyte_panels_supported": analyte_panels_supported,
    }
    if qc_buffer_minutes is not None:
        payload["qc_buffer_minutes"] = qc_buffer_minutes
    payload.update(overrides)
    return payload


def create_instrument_run_payload(
    instrument_id: str,
    specimen_id: str,
    scheduled_start: str,
    scheduled_end: str,
    **overrides,
) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "specimen_id": specimen_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


# ─── Result (PRD §3.5, §3.8) ─────────────────────────────────────────────────


def create_result_payload(
    lab_order_id: str,
    specimen_id: str,
    run_id: str,
    analyte_code: str = "K",
    numeric_value: float = 4.20,
    unit: str = "mmol/L",
    reference_low: float = 3.50,
    reference_high: float = 5.10,
    critical_low: float = 2.50,
    critical_high: float = 6.00,
    **overrides,
) -> dict:
    payload = {
        "lab_order_id": lab_order_id,
        "specimen_id": specimen_id,
        "run_id": run_id,
        "analyte_code": analyte_code,
        "numeric_value": numeric_value,
        "unit": unit,
        "reference_low": reference_low,
        "reference_high": reference_high,
        "critical_low": critical_low,
        "critical_high": critical_high,
    }
    payload.update(overrides)
    return payload


def release_result_payload(expected_lab_order_version: int, **overrides) -> dict:
    payload = {"expected_lab_order_version": expected_lab_order_version}
    payload.update(overrides)
    return payload


def amend_result_payload(
    expected_result_version: int, numeric_value: float, **overrides
) -> dict:
    payload = {
        "expected_result_version": expected_result_version,
        "numeric_value": numeric_value,
    }
    payload.update(overrides)
    return payload


# ─── Acknowledgement (PRD §3.7) ──────────────────────────────────────────────


def create_acknowledgement_payload(
    ack_method: str = "WEB_UI",
    attestation_text: str = "Reviewed and acknowledged.",
    **overrides,
) -> dict:
    payload = {
        "ack_method": ack_method,
        "attestation_text": attestation_text,
    }
    payload.update(overrides)
    return payload


# ─── RetestRequest (PRD §3.8) ────────────────────────────────────────────────


def create_retest_request_payload(
    reason: str = "CLINICIAN_DOUBT", **overrides
) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Test clock (PRD §3.9) ───────────────────────────────────────────────────


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
