"""Payload factories — one per creating/updating endpoint, input fields only.

Every factory returns a dict carrying only fields the endpoint declares as
client input, and accepts ``**overrides`` so a test can vary exactly the value
under examination.  Passing ``field=None`` explicitly keeps the key with a null
value; use ``pop`` on the returned dict to omit a key entirely.
"""

DEFAULTS = {
    "BRANCH_NAME": "Tampa Bay",
    "STATE_CODE": "FL",
    "PATIENT_NAME": "Marta Alvarez",
    "MRN": "MRN-0001",
    "SERIAL_NUMBER": "SC-1001",
    "MODEL_CODE": "CONC-5L",
    "PORTABLE_SERIAL": "PC-2001",
    "PORTABLE_MODEL": "POC-3L",
    "NPI": "1234567893",
    "TESTED_AT": "2026-07-25T14:00:00Z",
    "SERVICE_DATE": "2026-08-01",
    "SHIFT_START": "2026-08-01T12:00:00Z",
    "SHIFT_END": "2026-08-01T22:00:00Z",
    "WINDOW_START": "2026-08-01T13:00:00Z",
    "WINDOW_END": "2026-08-01T14:00:00Z",
    "NEXT_PM_DUE_DATE": "2027-06-01",
    "DRIVER_USER_ID": "u-drv-1",
}


def create_branch_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["BRANCH_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "competitive_bid_area": True,
        "liquid_oxygen_certified": False,
        "refill_capacity_per_day": 4,
        "tank_exchange_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


def update_branch_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_patient_payload(branch_id: str = None, **overrides) -> dict:
    payload = {
        "mrn": DEFAULTS["MRN"],
        "full_name": DEFAULTS["PATIENT_NAME"],
        "branch_id": branch_id,
        "payer_type": "MEDICARE_COMPETITIVE_BID",
        "mobility_profile": "LIMITED_AMBULATORY",
        "altitude_feet": 500,
    }
    payload.update(overrides)
    return payload


def update_patient_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_qualifying_test_payload(patient_id: str = None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "test_type": "RESTING_ROOM_AIR",
        "tested_at": DEFAULTS["TESTED_AT"],
        "ordering_physician_npi": DEFAULTS["NPI"],
        "spo2_percent": 87,
    }
    payload.update(overrides)
    return payload


def create_cmn_payload(
    patient_id: str = None,
    qualifying_test_id: str = None,
    expected_patient_version: int = None,
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "qualifying_test_id": qualifying_test_id,
        "form_type": "INITIAL",
        "prescribed_lpm": 3.0,
        "hours_per_day": 24,
        "portable_prescribed": False,
        "length_of_need_months": 99,
        "narrative_element_count": 3,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def update_cmn_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def return_for_correction_payload(**overrides) -> dict:
    payload = {"correction_notes": "Narrative incomplete; revise and resubmit."}
    payload.update(overrides)
    return payload


def void_cmn_payload(**overrides) -> dict:
    payload = {"void_reason": "Prescription withdrawn by ordering clinician."}
    payload.update(overrides)
    return payload


def create_rental_contract_payload(
    patient_id: str = None, cmn_id: str = None, **overrides
) -> dict:
    payload = {
        "patient_id": patient_id,
        "cmn_id": cmn_id,
        "pricing_basis": "COMPETITIVE_BID_SINGLE_PAYMENT",
        "cap_month_limit": 36,
    }
    payload.update(overrides)
    return payload


def create_equipment_unit_payload(branch_id: str = None, **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "model_code": DEFAULTS["MODEL_CODE"],
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 5.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": DEFAULTS["NEXT_PM_DUE_DATE"],
    }
    payload.update(overrides)
    return payload


def portable_equipment_unit_payload(branch_id: str = None, **overrides) -> dict:
    payload = create_equipment_unit_payload(
        branch_id,
        serial_number=DEFAULTS["PORTABLE_SERIAL"],
        model_code=DEFAULTS["PORTABLE_MODEL"],
        equipment_class="PORTABLE_CONCENTRATOR",
        max_continuous_lpm=3.0,
        max_pulse_setting=5,
    )
    payload.update(overrides)
    return payload


def create_equipment_assignment_payload(role: str = "PRIMARY_STATIONARY", **overrides) -> dict:
    payload = {"role": role}
    payload.update(overrides)
    return payload


def create_delivery_route_payload(branch_id: str = None, **overrides) -> dict:
    payload = {
        "branch_id": branch_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "driver_user_id": DEFAULTS["DRIVER_USER_ID"],
        "shift_start_utc": DEFAULTS["SHIFT_START"],
        "shift_end_utc": DEFAULTS["SHIFT_END"],
    }
    payload.update(overrides)
    return payload


def create_route_stop_payload(
    route_id: str = None, contract_id: str = None, **overrides
) -> dict:
    payload = {
        "route_id": route_id,
        "contract_id": contract_id,
        "stop_type": "SETUP_DELIVERY",
        "window_start_utc": DEFAULTS["WINDOW_START"],
        "window_end_utc": DEFAULTS["WINDOW_END"],
        "service_minutes": 60,
        "cylinders_requested": 0,
    }
    payload.update(overrides)
    return payload


def complete_setup_payload(**overrides) -> dict:
    payload = {
        "smoking_in_home": False,
        "electrical_pass": True,
        "patient_teachback_score": 5,
        "education_topics_covered": [
            "EQUIPMENT_OPERATION",
            "FIRE_SAFETY",
            "EMERGENCY_CONTACT",
        ],
    }
    payload.update(overrides)
    return payload


def malfunction_payload(symptom: str = "NO_FLOW", oxygen_gap_minutes: int = 0, **overrides) -> dict:
    payload = {"symptom": symptom, "oxygen_gap_minutes": oxygen_gap_minutes}
    payload.update(overrides)
    return payload


def create_recall_notice_payload(model_code: str = None, severity: str = "CLASS_I", **overrides) -> dict:
    payload = {"model_code": model_code or DEFAULTS["MODEL_CODE"], "severity": severity}
    payload.update(overrides)
    return payload


def create_travel_authorization_payload(
    expected_contract_version: int = None, **overrides
) -> dict:
    payload = {
        "depart_utc": "2026-08-05T08:00:00Z",
        "return_utc": "2026-08-06T08:00:00Z",
        "receiving_branch_id": None,
        "destination_altitude_feet": 0,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def deny_travel_payload(**overrides) -> dict:
    payload = {"denial_reason": "Destination hand-off could not be arranged."}
    payload.update(overrides)
    return payload


def create_transfer_request_payload(
    receiving_branch_id: str = None, transfer_effective_date: str = "2026-08-15", **overrides
) -> dict:
    payload = {
        "receiving_branch_id": receiving_branch_id,
        "transfer_effective_date": transfer_effective_date,
    }
    payload.update(overrides)
    return payload


def post_billing_month_payload(service_month: str = "2026-08", **overrides) -> dict:
    payload = {"service_month": service_month}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
