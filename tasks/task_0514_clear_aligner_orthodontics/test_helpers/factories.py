"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PATIENT_EMAIL": "patient@example.com",
    "PATIENT_NAME": "Test Patient",
    "STATE_CODE": "CA",
    "DOB": "1990-01-01",
    "CLINICIAN_NAME": "Dr Test",
    "LIST_PRICE_CENTS": 300000,
}


def create_patient_payload(**overrides) -> dict:
    """POST /patients input: email, full_name, state_code, date_of_birth."""
    defaults = {
        "email": DEFAULTS["PATIENT_EMAIL"],
        "full_name": DEFAULTS["PATIENT_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "date_of_birth": DEFAULTS["DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_clinician_payload(**overrides) -> dict:
    """POST /clinicians input: full_name, license_state_codes, role_type, active?."""
    defaults = {
        "full_name": DEFAULTS["CLINICIAN_NAME"],
        "license_state_codes": ["CA"],
        "role_type": "DENTIST",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(patient_id, **overrides) -> dict:
    """POST /cases input: patient_id, intake_channel, list_price_cents."""
    defaults = {
        "patient_id": patient_id,
        "intake_channel": "IMPRESSION_KIT",
        "list_price_cents": DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_intake_record_payload(**overrides) -> dict:
    """POST /cases/{id}/intake-records input: channel, quality_score,
    kit_tracking_number?, scan_clinic_state_code?."""
    defaults = {
        "channel": "IMPRESSION_KIT",
        "quality_score": 0.9,
        "kit_tracking_number": "TRK-DEFAULT",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(case_id, author_clinician_id, **overrides) -> dict:
    """POST /plans input: case_id, author_clinician_id, proposed_step_count,
    weeks_per_step, discount_code?."""
    defaults = {
        "case_id": case_id,
        "author_clinician_id": author_clinician_id,
        "proposed_step_count": 10,
        "weeks_per_step": 2,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(step_id, **overrides) -> dict:
    """POST /shipments input: step_id, carrier_code, window_start, window_end."""
    defaults = {
        "step_id": step_id,
        "carrier_code": "GROUND",
        "window_start": "2026-05-02T00:00:00Z",
        "window_end": "2026-05-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_checkin_payload(**overrides) -> dict:
    """POST /cases/{id}/checkins input: reported_step_index, photo_quality_score."""
    defaults = {
        "reported_step_index": 1,
        "photo_quality_score": 0.9,
    }
    defaults.update(overrides)
    return defaults


def create_refinement_payload(case_id, triggering_checkin_id, **overrides) -> dict:
    """POST /refinements input: case_id, triggering_checkin_id, additional_step_count."""
    defaults = {
        "case_id": case_id,
        "triggering_checkin_id": triggering_checkin_id,
        "additional_step_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_financing_plan_payload(case_id, **overrides) -> dict:
    """POST /financing-plans input: case_id, term_months, down_payment_cents, apr_bps."""
    defaults = {
        "case_id": case_id,
        "term_months": 12,
        "down_payment_cents": 0,
        "apr_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_refund_payload(case_id, expected_case_version, **overrides) -> dict:
    """POST /refunds input: case_id, reason, expected_case_version."""
    defaults = {
        "case_id": case_id,
        "reason": "PATIENT_CANCEL",
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_retainer_payload(case_id, **overrides) -> dict:
    """POST /retainers input: case_id, cadence, per_shipment_fee_cents."""
    defaults = {
        "case_id": case_id,
        "cadence": "QUARTERLY",
        "per_shipment_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults
