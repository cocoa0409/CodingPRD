"""Payload factories — one per entity, input fields only.

Only `source: input` fields appear here; computed/system fields (status, ids,
totals, version) are never sent. Field names are exactly as named in the PRD.
"""


def create_operatory_payload(**overrides) -> dict:
    defaults = {"name": "Operatory 1", "cleanup_buffer_minutes": 30}
    defaults.update(overrides)
    return defaults


def create_kennel_payload(**overrides) -> dict:
    defaults = {"name": "Kennel Block A", "capacity": 2}
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {"account_name": "The Test Family"}
    defaults.update(overrides)
    return defaults


def create_deposit_payload(household_id: str, amount_cents: int,
                           expected_household_version: int, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "amount_cents": amount_cents,
        "expected_household_version": expected_household_version,
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(household_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "full_name": "Jane Doe",
        "email": "jane.doe@example.com",
        "is_primary": False,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(household_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "name": "Rex",
        "species": "DOG",
        "weight_kg": 12.5,
    }
    defaults.update(overrides)
    return defaults


def create_wellness_plan_payload(patient_id: str, tier: str = "BASIC", **overrides) -> dict:
    defaults = {"patient_id": patient_id, "tier": tier}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(patient_id: str,
                               scheduled_start: str = "2026-07-01T09:00:00Z",
                               scheduled_end: str = "2026-07-01T10:00:00Z",
                               **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "visit_reason": "Wellness check",
    }
    defaults.update(overrides)
    return defaults


def create_vaccination_payload(patient_id: str, vaccine_code: str = "RABIES",
                               administered_at: str = "2026-06-01T10:00:00Z",
                               **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "vaccine_code": vaccine_code,
        "administered_at": administered_at,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(patient_id: str, refills_authorized: int = 2,
                                **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "drug_name": "Amoxicillin",
        "refills_authorized": refills_authorized,
        "is_controlled": False,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(patient_id: str, line_items=None,
                            deposit_required_cents: int = 0, **overrides) -> dict:
    if line_items is None:
        line_items = [
            {"service_code": "EXAM", "qty": 1, "unit_price_cents": 10000,
             "eligible_for_plan_discount": False}
        ]
    defaults = {
        "patient_id": patient_id,
        "line_items": line_items,
        "deposit_required_cents": deposit_required_cents,
    }
    defaults.update(overrides)
    return defaults


def create_surgery_payload(appointment_id: str, operatory_id: str, estimate_id: str,
                           window_start: str = "2026-07-01T09:00:00Z",
                           window_end: str = "2026-07-01T10:00:00Z",
                           **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "operatory_id": operatory_id,
        "estimate_id": estimate_id,
        "procedure_name": "Spay",
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_boarding_stay_payload(patient_id: str, kennel_id: str,
                                 check_in_date: str = "2026-07-01T00:00:00Z",
                                 check_out_date: str = "2026-07-03T00:00:00Z",
                                 nightly_rate_cents: int = 5000, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "kennel_id": kennel_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "nightly_rate_cents": nightly_rate_cents,
    }
    defaults.update(overrides)
    return defaults


def create_lab_order_payload(appointment_id: str, order_type: str = "BLOODWORK",
                             fee_cents: int = 6000, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "order_type": order_type,
        "fee_cents": fee_cents,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(household_id: str, appointment_id: str,
                           expected_household_version: int, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "appointment_id": appointment_id,
        "expected_household_version": expected_household_version,
    }
    defaults.update(overrides)
    return defaults
