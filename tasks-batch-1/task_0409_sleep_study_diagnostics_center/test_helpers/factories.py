"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PATIENT_NAME": "Test Patient",
    "DOB": "1985-01-01",
    "PAYER": "Acme",
    "NPI": "1234567890",
    "INDICATION": "suspected_OSA",
    "BED_LABEL": "Room-1-Bed-A",
    "NIGHT_START": "2026-07-01T22:00:00Z",
    "NIGHT_END": "2026-07-02T06:00:00Z",
    "PRESSURE": 9.0,
    "INTERPRETATION": "Interpretation complete",
}


def create_patient_payload(**overrides) -> dict:
    """Patient: full_name, date_of_birth, insurance_payer required;
    baseline_epworth_score optional (defaults to 0 server-side)."""
    payload = {
        "full_name": DEFAULTS["PATIENT_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
        "insurance_payer": DEFAULTS["PAYER"],
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id: str, **overrides) -> dict:
    """Referral: patient_id, referring_provider_npi, requested_modality,
    clinical_indication required; prior_auth_required optional (defaults true)."""
    payload = {
        "patient_id": patient_id,
        "referring_provider_npi": DEFAULTS["NPI"],
        "requested_modality": "HSAT",
        "clinical_indication": DEFAULTS["INDICATION"],
    }
    payload.update(overrides)
    return payload


def approve_auth_payload(**overrides) -> dict:
    """approve-auth body: prior_auth_number, prior_auth_expires_on required."""
    payload = {
        "prior_auth_number": "PA-DEFAULT",
        "prior_auth_expires_on": "2026-12-31",
    }
    payload.update(overrides)
    return payload


def create_bed_payload(**overrides) -> dict:
    """SleepBed: bed_label required; turnover_buffer_minutes optional (defaults 60)."""
    payload = {
        "bed_label": DEFAULTS["BED_LABEL"],
    }
    payload.update(overrides)
    return payload


def create_study_order_payload(referral_id: str, expected_referral_version, **overrides) -> dict:
    """StudyOrder: referral_id, modality, expected_referral_version required."""
    payload = {
        "referral_id": referral_id,
        "modality": "HSAT",
        "expected_referral_version": expected_referral_version,
    }
    payload.update(overrides)
    return payload


def schedule_study_payload(**overrides) -> dict:
    """schedule body: night_start_utc, night_end_utc required; bed_id optional."""
    payload = {
        "night_start_utc": DEFAULTS["NIGHT_START"],
        "night_end_utc": DEFAULTS["NIGHT_END"],
    }
    payload.update(overrides)
    return payload


def score_study_payload(total_recording_minutes, respiratory_event_count,
                        expected_study_order_version, **overrides) -> dict:
    """score body: total_recording_minutes, respiratory_event_count,
    expected_study_order_version required; titration_optimal_cmh2o optional."""
    payload = {
        "total_recording_minutes": total_recording_minutes,
        "respiratory_event_count": respiratory_event_count,
        "expected_study_order_version": expected_study_order_version,
    }
    payload.update(overrides)
    return payload


def interpret_payload(**overrides) -> dict:
    """interpret body: interpretation_text required; physician_recommends_cpap optional."""
    payload = {
        "interpretation_text": DEFAULTS["INTERPRETATION"],
        "physician_recommends_cpap": True,
    }
    payload.update(overrides)
    return payload


def create_dme_order_payload(study_order_id: str, **overrides) -> dict:
    """DMEOrder: study_order_id, device_type, prescribed_pressure_cmh2o required;
    supersedes_dme_order_id + expected_supersedes_version optional (resupply only)."""
    payload = {
        "study_order_id": study_order_id,
        "device_type": "CPAP",
        "prescribed_pressure_cmh2o": DEFAULTS["PRESSURE"],
    }
    payload.update(overrides)
    return payload


def create_compliance_record_payload(dme_order_id: str, window_start_utc, window_end_utc,
                                     nights_used_4h_plus, total_usage_minutes, **overrides) -> dict:
    """ComplianceRecord: dme_order_id, window_start_utc, window_end_utc,
    nights_used_4h_plus, total_usage_minutes all required."""
    payload = {
        "dme_order_id": dme_order_id,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "nights_used_4h_plus": nights_used_4h_plus,
        "total_usage_minutes": total_usage_minutes,
    }
    payload.update(overrides)
    return payload


def create_follow_up_payload(study_order_id: str, **overrides) -> dict:
    """FollowUp: study_order_id, scheduled_for_utc required."""
    payload = {
        "study_order_id": study_order_id,
        "scheduled_for_utc": "2026-09-01T15:00:00Z",
    }
    payload.update(overrides)
    return payload
