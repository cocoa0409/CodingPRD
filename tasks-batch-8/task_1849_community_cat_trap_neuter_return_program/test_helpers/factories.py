"""Payload factories — one per entity, input fields only (PRD §3)."""

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


DEFAULTS = {
    "PHONE": "555-0100",
    "VOUCHER_REIMBURSEMENT_CENTS": 10000,
    "FACE_VALUE_CENTS": 5000,
    "SURGEON_INITIALS": "DR",
}


def create_caretaker_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Caretaker {n}",
        "phone": DEFAULTS["PHONE"],
        "email": f"caretaker{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_colony_payload(caretaker_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Colony {n}",
        "address": f"{n} Colony Way",
        "caretaker_id": caretaker_id,
        "estimated_population": 3,
    }
    defaults.update(overrides)
    return defaults


def create_cat_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "intake_tag": f"TAG-{n}",
        "sex": "MALE",
        "approximate_age_months": 24,
    }
    defaults.update(overrides)
    return defaults


def create_partner_clinic_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Clinic {n}",
        "voucher_reimbursement_cents": DEFAULTS["VOUCHER_REIMBURSEMENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_clinic_day_payload(clinic_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "service_date": "2026-08-20T00:00:00Z",
        "base_capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(cat_id, clinic_slot_id, expected_clinic_day_version,
                               **overrides) -> dict:
    defaults = {
        "cat_id": cat_id,
        "clinic_slot_id": clinic_slot_id,
        "trap_date": "2026-08-19T00:00:00Z",
        "expected_clinic_day_version": expected_clinic_day_version,
    }
    defaults.update(overrides)
    return defaults


def create_surgery_record_payload(appointment_id, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "surgeon_initials": DEFAULTS["SURGEON_INITIALS"],
        "ear_tipped": True,
        "rabies_vaccinated": True,
        "outcome": "STERILIZED",
    }
    defaults.update(overrides)
    return defaults


def create_voucher_payload(caretaker_id, **overrides) -> dict:
    defaults = {
        "caretaker_id": caretaker_id,
        "face_value_cents": DEFAULTS["FACE_VALUE_CENTS"],
        "funding_source": "MUNICIPAL_GRANT",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "complainant_name": f"Neighbor {n}",
        "category": "NOISE",
    }
    defaults.update(overrides)
    return defaults


def create_foster_home_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "volunteer_name": f"Foster Home {n}",
        "capacity_kittens": 2,
    }
    defaults.update(overrides)
    return defaults


def create_foster_placement_payload(cat_id, foster_home_id, **overrides) -> dict:
    defaults = {
        "cat_id": cat_id,
        "foster_home_id": foster_home_id,
    }
    defaults.update(overrides)
    return defaults


def create_population_survey_payload(**overrides) -> dict:
    defaults = {
        "surveyed_on": "2026-08-01T00:00:00Z",
        "observed_count": 3,
        "eartipped_count": 1,
    }
    defaults.update(overrides)
    return defaults
