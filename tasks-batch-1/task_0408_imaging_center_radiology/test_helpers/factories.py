"""Payload factories — one per entity, input fields only (PRD §3).

Only source=input fields appear here. Computed and system fields
(posture, now_utc, requires_contrast_screening, status, etc.) are never sent.
"""


def create_center_payload(**overrides) -> dict:
    """POST /imaging-centers — name required; the rest optional (PRD §3.1)."""
    defaults = {"name": "Test Imaging Center"}
    defaults.update(overrides)
    return defaults


def create_modality_payload(modality_type="XRAY", name="Test Modality", base_rvu=1.0, **overrides) -> dict:
    """POST /imaging-centers/{id}/modalities (PRD §3.1)."""
    defaults = {
        "modality_type": modality_type,
        "name": name,
        "base_rvu": base_rvu,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(modality_id, name="Test Room", **overrides) -> dict:
    """POST /imaging-centers/{id}/rooms (PRD §3.1)."""
    defaults = {
        "modality_id": modality_id,
        "name": name,
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(staff_role, full_name="Test Staff", credentialed_modalities=None, **overrides) -> dict:
    """POST /imaging-centers/{id}/staff (PRD §3.1)."""
    defaults = {
        "staff_role": staff_role,
        "full_name": full_name,
        "credentialed_modalities": credentialed_modalities if credentialed_modalities is not None else ["XRAY"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(modality_id, patient_mrn="MRN-1", ordering_provider_npi="NPI-1", **overrides) -> dict:
    """POST /imaging-centers/{id}/imaging-orders (PRD §3.2).

    priority defaults to ROUTINE and requires_contrast to false server-side;
    omit them here unless a test overrides them explicitly.
    """
    defaults = {
        "modality_id": modality_id,
        "patient_mrn": patient_mrn,
        "ordering_provider_npi": ordering_provider_npi,
    }
    defaults.update(overrides)
    return defaults


def create_prior_auth_payload(payer_name="Acme Health", requested_units=1, **overrides) -> dict:
    """POST /imaging-orders/{id}/prior-authorizations (PRD §3.2)."""
    defaults = {
        "payer_name": payer_name,
        "requested_units": requested_units,
    }
    defaults.update(overrides)
    return defaults


def prior_auth_decision_payload(decision, **overrides) -> dict:
    """POST /prior-authorizations/{id}/decision (PRD §3.2)."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_screening_payload(egfr_value=90, **overrides) -> dict:
    """POST /imaging-orders/{id}/contrast-screenings (PRD §3.3).

    has_contrast_allergy, is_pregnant, metal_implant_unsafe default to false
    server-side; supply them via overrides for blocking scenarios.
    """
    defaults = {"egfr_value": egfr_value}
    defaults.update(overrides)
    return defaults


def create_exam_payload(room_id, technologist_id, scheduled_start_utc, scheduled_end_utc,
                        expected_imaging_order_version, **overrides) -> dict:
    """POST /imaging-orders/{id}/exams (PRD §3.4)."""
    defaults = {
        "room_id": room_id,
        "technologist_id": technologist_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "expected_imaging_order_version": expected_imaging_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(series_label="Test Series", **overrides) -> dict:
    """POST /imaging-exams/{id}/image-series (PRD §3.5)."""
    defaults = {"series_label": series_label}
    defaults.update(overrides)
    return defaults


def finalize_series_payload(outcome, **overrides) -> dict:
    """POST /image-series/{id}/finalize (PRD §3.5)."""
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def claim_read_payload(expected_imaging_exam_version, **overrides) -> dict:
    """POST /imaging-exams/{id}/claim-read (PRD §2.10, §3.6)."""
    defaults = {"expected_imaging_exam_version": expected_imaging_exam_version}
    defaults.update(overrides)
    return defaults


def create_report_payload(findings_text="Findings text.", **overrides) -> dict:
    """POST /imaging-exams/{id}/reports (PRD §3.6).

    has_critical_finding defaults to false server-side; supply via overrides.
    """
    defaults = {"findings_text": findings_text}
    defaults.update(overrides)
    return defaults


def create_critical_result_payload(notified_party_role="ORDERING_PROVIDER", **overrides) -> dict:
    """POST /radiology-reports/{id}/critical-results (PRD §3.7)."""
    defaults = {"notified_party_role": notified_party_role}
    defaults.update(overrides)
    return defaults


def set_clock_payload(imaging_center_id, to_iso8601, **overrides) -> dict:
    """POST /_clock/set_current_utc (PRD §2.6)."""
    defaults = {
        "imaging_center_id": imaging_center_id,
        "to_iso8601": to_iso8601,
    }
    defaults.update(overrides)
    return defaults
