"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying the required input fields with sensible
defaults; pass **overrides to control any field a test needs to pin.
"""


def create_service_area_payload(**overrides) -> dict:
    defaults = {
        "zip_code": "11201",
        "name": "BK North",
        "travel_surcharge_cents": 0,
        "euthanasia_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_clinician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Tech Default",
        "clinician_role": "TECH",
    }
    defaults.update(overrides)
    return defaults


def create_vet_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Vet",
        "clinician_role": "VET",
        "dea_number": "AV1234567",
        "dea_expires_on": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rolling_clinic_payload(**overrides) -> dict:
    defaults = {
        "plate": "VAN-1",
        "controlled_stock_ml": 50,
        "vaccine_stock_count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "owner_name": "Owner",
        "species": "DOG",
        "weight_kg": 30,
        "home_zip": "11201",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "visit_type": "EXAM",
        "requested_start": "2026-02-01T09:00:00Z",
        "requested_end": "2026-02-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_route_day_payload(**overrides) -> dict:
    defaults = {
        "clinician_id": None,
        "rolling_clinic_id": None,
        "service_date": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(**overrides) -> dict:
    defaults = {
        "appointment_id": None,
        "window_start": "2026-02-01T09:00:00Z",
        "window_end": "2026-02-01T10:00:00Z",
        "expected_route_day_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(**overrides) -> dict:
    defaults = {
        "appointment_id": None,
        "line_items": [{"code": "EXAM_FEE", "label": "Exam", "unit_cents": 9000, "qty": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "estimate_id": None,
        "amount_cents": 9000,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_euthanasia_log_payload(**overrides) -> dict:
    defaults = {
        "rolling_clinic_id": None,
        "administering_vet_id": None,
        "entry_type": "DISPENSE",
        "amount_ml": 6.0,
    }
    defaults.update(overrides)
    return defaults


def create_specimen_payload(**overrides) -> dict:
    defaults = {
        "appointment_id": None,
        "specimen_type": "BLOOD",
    }
    defaults.update(overrides)
    return defaults


def create_wellness_plan_payload(**overrides) -> dict:
    defaults = {
        "patient_id": None,
        "interval_days": 30,
        "anchor_date": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def refer_payload(**overrides) -> dict:
    defaults = {
        "hospital_name": "City Animal ER",
        "reason": "acute abdomen",
    }
    defaults.update(overrides)
    return defaults
