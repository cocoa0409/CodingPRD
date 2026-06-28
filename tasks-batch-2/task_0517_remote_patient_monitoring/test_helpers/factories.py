"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PAYER_NAME": "Test Payer",
    "PAYER_TYPE": "MEDICARE",
    "RATE_99453": 1965,
    "RATE_99454": 4774,
    "RATE_99457": 4877,
    "DIAGNOSIS_CODE": "I10",
    "GOAL_TEXT": "BP control",
    "DEVICE_TYPE": "BP_CUFF",
    "CONSENT_TYPE": "BOTH",
    "EFFECTIVE_AT": "2026-05-01T00:00:00Z",
}


def create_payer_payload(**overrides) -> dict:
    """Payer input fields (§3.1). requires_active_consent / timely_filing_days optional."""
    defaults = {
        "name": DEFAULTS["PAYER_NAME"],
        "payer_type": DEFAULTS["PAYER_TYPE"],
        "rate_99453_cents": DEFAULTS["RATE_99453"],
        "rate_99454_cents": DEFAULTS["RATE_99454"],
        "rate_99457_cents": DEFAULTS["RATE_99457"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(payer_id, **overrides) -> dict:
    """Patient input fields (§3.1): payer_id, mrn, full_name."""
    defaults = {
        "payer_id": payer_id,
        "mrn": "M-TEST-1",
        "full_name": "Test Patient",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    """ConsentRecord input fields (§3.1): consent_type, effective_at."""
    defaults = {
        "consent_type": DEFAULTS["CONSENT_TYPE"],
        "effective_at": DEFAULTS["EFFECTIVE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(**overrides) -> dict:
    """CarePlan input fields (§3.2): diagnosis_code, goal_text, required_care_minutes?."""
    defaults = {
        "diagnosis_code": DEFAULTS["DIAGNOSIS_CODE"],
        "goal_text": DEFAULTS["GOAL_TEXT"],
        "required_care_minutes": 20,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    """Device input fields (§3.4): device_type, serial_number."""
    defaults = {
        "device_type": DEFAULTS["DEVICE_TYPE"],
        "serial_number": "SN-TEST-1",
    }
    defaults.update(overrides)
    return defaults


def create_vitals_payload(device_id, reading_value, measured_at, **overrides) -> dict:
    """VitalsReading input fields (§3.5): device_id, reading_value, secondary_value?, measured_at."""
    defaults = {
        "device_id": device_id,
        "reading_value": reading_value,
        "measured_at": measured_at,
    }
    defaults.update(overrides)
    return defaults


def create_care_activity_payload(billing_period_id, clinician_user_id, minutes,
                                 performed_at, activity_type="REVIEW", **overrides) -> dict:
    """CareActivity input fields (§3.7)."""
    defaults = {
        "billing_period_id": billing_period_id,
        "clinician_user_id": clinician_user_id,
        "activity_type": activity_type,
        "minutes": minutes,
        "performed_at": performed_at,
    }
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(period_year=2026, period_month=6, **overrides) -> dict:
    """BillingPeriod input fields (§3.8): period_year, period_month."""
    defaults = {
        "period_year": period_year,
        "period_month": period_month,
    }
    defaults.update(overrides)
    return defaults


def finalize_payload(expected_billing_period_version, **overrides) -> dict:
    """Finalize input field (§2.7): expected_billing_period_version (OCC guard)."""
    defaults = {"expected_billing_period_version": expected_billing_period_version}
    defaults.update(overrides)
    return defaults


def remit_payload(remittance_cents, **overrides) -> dict:
    """Remit input field (§3.9): remittance_cents."""
    defaults = {"remittance_cents": remittance_cents}
    defaults.update(overrides)
    return defaults
