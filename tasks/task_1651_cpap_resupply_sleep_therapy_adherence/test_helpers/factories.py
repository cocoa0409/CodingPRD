"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
import uuid

DEFAULTS = {
    "PAYER_NAME": "Payer A",
    "PLAN_CODE": "PAYER-A",
    "COMPLIANCE_THRESHOLD_PCT": 70,
    "COMPLIANCE_MIN_HOURS_PER_NIGHT": 4.0,
    "COMPLIANCE_WINDOW_DAYS": 30,
    "COMPLIANCE_MIN_NIGHTS": 21,
    "RENTAL_MONTHS_TO_OWN": 3,
    "MASK_CADENCE_DAYS": 90,
    "CUSHION_CADENCE_DAYS": 30,
    "FILTER_CADENCE_DAYS": 14,
    "TUBING_CADENCE_DAYS": 90,
    "MASK_EXCHANGE_WINDOW_DAYS": 30,
    "MAX_EXCHANGES_PER_WINDOW": 1,
    "REQUIRES_PRIOR_AUTH": False,
    "FULL_NAME": "Test Patient",
    "DATE_OF_BIRTH": "1980-01-01",
    "PRESCRIBING_CLINICIAN_NPI": "1234567890",
    "DEVICE_MODEL": "Airsense-11",
    "ACQUISITION_TYPE": "PURCHASE",
    "EXCHANGE_REASON": "FIT_LEAK",
    "DISCONTINUATION_REASON": "THERAPY_DISCONTINUED",
    "DENIAL_REASON_CODE": "PAYER_DENIED",
}


def create_payer_policy_payload(**overrides) -> dict:
    """Input fields for POST /sleep-therapy/payer-policies (PRD §3.1)."""
    defaults = {
        "payer_name": DEFAULTS["PAYER_NAME"],
        # plan_code must be unique across policies; suffix with a random tag.
        "plan_code": f"{DEFAULTS['PLAN_CODE']}-{uuid.uuid4().hex[:8]}",
        "compliance_threshold_pct": DEFAULTS["COMPLIANCE_THRESHOLD_PCT"],
        "compliance_min_hours_per_night": DEFAULTS["COMPLIANCE_MIN_HOURS_PER_NIGHT"],
        "compliance_window_days": DEFAULTS["COMPLIANCE_WINDOW_DAYS"],
        "compliance_min_nights": DEFAULTS["COMPLIANCE_MIN_NIGHTS"],
        "rental_months_to_own": DEFAULTS["RENTAL_MONTHS_TO_OWN"],
        "mask_cadence_days": DEFAULTS["MASK_CADENCE_DAYS"],
        "cushion_cadence_days": DEFAULTS["CUSHION_CADENCE_DAYS"],
        "filter_cadence_days": DEFAULTS["FILTER_CADENCE_DAYS"],
        "tubing_cadence_days": DEFAULTS["TUBING_CADENCE_DAYS"],
        "mask_exchange_window_days": DEFAULTS["MASK_EXCHANGE_WINDOW_DAYS"],
        "max_exchanges_per_window": DEFAULTS["MAX_EXCHANGES_PER_WINDOW"],
        "requires_prior_auth": DEFAULTS["REQUIRES_PRIOR_AUTH"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(payer_policy_id: str, **overrides) -> dict:
    """Input fields for POST /sleep-therapy/patients (PRD §3.2)."""
    defaults = {
        "full_name": DEFAULTS["FULL_NAME"],
        "date_of_birth": DEFAULTS["DATE_OF_BIRTH"],
        "payer_policy_id": payer_policy_id,
        "prescribing_clinician_npi": DEFAULTS["PRESCRIBING_CLINICIAN_NPI"],
    }
    defaults.update(overrides)
    return defaults


def create_device_enrollment_payload(patient_id: str, **overrides) -> dict:
    """Input fields for POST /sleep-therapy/device-enrollments (PRD §3.2)."""
    defaults = {
        "patient_id": patient_id,
        # device_serial is unique across enrollments; mint a fresh one per call.
        "device_serial": f"SN-{uuid.uuid4().hex[:10].upper()}",
        "device_model": DEFAULTS["DEVICE_MODEL"],
        "acquisition_type": DEFAULTS["ACQUISITION_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_resupply_order_payload(patient_id: str, component_supply_plan_id: str,
                                  requested_quantity: int, expected_patient_version: int,
                                  **overrides) -> dict:
    """Input fields for POST /sleep-therapy/resupply-orders (PRD §3.5)."""
    defaults = {
        "patient_id": patient_id,
        "component_supply_plan_id": component_supply_plan_id,
        "requested_quantity": requested_quantity,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_adherence_report_payload(patient_id: str, device_enrollment_id: str,
                                    window_end_on: str, nights_reported: int,
                                    compliant_nights: int, **overrides) -> dict:
    """Input fields for POST /sleep-therapy/adherence-reports (PRD §3.4)."""
    defaults = {
        "patient_id": patient_id,
        "device_enrollment_id": device_enrollment_id,
        "window_end_on": window_end_on,
        "nights_reported": nights_reported,
        "compliant_nights": compliant_nights,
    }
    defaults.update(overrides)
    return defaults


def create_mask_exchange_payload(patient_id: str, device_enrollment_id: str,
                                 original_mask_plan_id: str, **overrides) -> dict:
    """Input fields for POST /sleep-therapy/mask-exchanges (PRD §3.6)."""
    defaults = {
        "patient_id": patient_id,
        "device_enrollment_id": device_enrollment_id,
        "original_mask_plan_id": original_mask_plan_id,
        "reason_code": DEFAULTS["EXCHANGE_REASON"],
    }
    defaults.update(overrides)
    return defaults


def initiate_discontinuation_payload(**overrides) -> dict:
    """Input fields for POST /sleep-therapy/patients/{id}/initiate-discontinuation."""
    defaults = {"reason_code": DEFAULTS["DISCONTINUATION_REASON"]}
    defaults.update(overrides)
    return defaults


def occ_payload(expected_patient_version: int) -> dict:
    """OCC body carried by order authorization and order shipment (PRD §2.6)."""
    return {"expected_patient_version": expected_patient_version}
