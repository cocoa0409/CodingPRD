"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def patient_payload(**overrides):
    body = {
        "full_name": "Test Patient",
        "medicare_id": _uniq("MED"),
        "home_zip": "19100",
        "home_lat": 40.0,
        "home_lon": -75.2,
    }
    body.update(overrides)
    return body


def clinician_payload(**overrides):
    body = {
        "full_name": "Test Clinician",
        "discipline": "RN",
        "license_active": True,
        "base_lat": 40.0,
        "base_lon": -75.0,
        "weekly_visit_cap": 40,
    }
    body.update(overrides)
    return body


def oasis_payload(patient_id, clinician_id, **overrides):
    body = {
        "patient_id": patient_id,
        "clinician_id": clinician_id,
        "assessment_type": "START_OF_CARE",
        "assessment_date": "2026-02-01T08:00:00Z",
        "clinical_group": "WOUND",
        "functional_level": "HIGH",
        "comorbidity_count": 2,
    }
    body.update(overrides)
    return body


def rate_config_payload(**overrides):
    body = {
        "clinical_group": "WOUND",
        "base_30day_rate": 2000.00,
        "functional_weight_low": 0.95,
        "functional_weight_medium": 1.00,
        "functional_weight_high": 1.05,
        "lupa_threshold": 5,
        "active": True,
    }
    body.update(overrides)
    return body


def plan_payload(expected_episode_version, **overrides):
    body = {
        "planned_rn_visits": 6,
        "planned_pt_visits": 0,
        "planned_ot_visits": 0,
        "planned_slp_visits": 0,
        "companion_hours_authorized": 0,
        "expected_episode_version": expected_episode_version,
    }
    body.update(overrides)
    return body


def visit_payload(clinician_id, **overrides):
    body = {
        "clinician_id": clinician_id,
        "discipline": "RN",
        "scheduled_start": "2026-02-03T09:00:00Z",
        "scheduled_end": "2026-02-03T10:00:00Z",
    }
    body.update(overrides)
    return body


def companion_shift_payload(clinician_id, **overrides):
    body = {
        "clinician_id": clinician_id,
        "shift_start": "2026-02-03T13:00:00Z",
        "shift_end": "2026-02-03T13:30:00Z",
    }
    body.update(overrides)
    return body


def mileage_claim_payload(**overrides):
    body = {"claimed_miles": 20.0}
    body.update(overrides)
    return body
