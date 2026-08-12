"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_it_counter = {"n": 0}


def _seq() -> int:
    _it_counter["n"] += 1
    return _it_counter["n"]


def create_home_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "license_number": f"AFH-T{n:04d}",
        "name": f"Test Home {n}",
        "licensed_bed_capacity": 4,
    }
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"label": f"Room-{n}"}
    defaults.update(overrides)
    return defaults


def create_resident_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Resident {n}",
        "date_of_birth": "1940-01-01",
        "payer_type": "PRIVATE_PAY",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "nursing_hours_per_week": 2,
        "adl_dependency_score": 1,
        "care_plan": {"diet": "REGULAR", "mobility": "WALKER",
                      "medication_assistance": "FULL"},
    }
    defaults.update(overrides)
    return defaults


def create_admission_payload(resident_id: str, bed_id: str, assessment_id: str,
                             expected_bed_version: int, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "bed_id": bed_id,
        "assessment_id": assessment_id,
        "expected_admission_date": "2026-05-25",
        "expected_bed_version": expected_bed_version,
    }
    defaults.update(overrides)
    return defaults


def create_medication_order_payload(**overrides) -> dict:
    defaults = {
        "drug_name": "Lisinopril",
        "dose": "5mg oral",
        "schedule_times": ["08:00"],
    }
    defaults.update(overrides)
    return defaults


def create_medication_log_payload(resident_id: str, order_id: str, caregiver_id: str,
                                  administered_at: str, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "order_id": order_id,
        "administered_at": administered_at,
        "outcome": "GIVEN",
        "caregiver_id": caregiver_id,
    }
    defaults.update(overrides)
    return defaults


def create_adl_log_payload(resident_id: str, caregiver_id: str,
                           performed_at: str, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "adl_type": "BATHING",
        "assistance_level": "PARTIAL",
        "performed_at": performed_at,
        "caregiver_id": caregiver_id,
    }
    defaults.update(overrides)
    return defaults


def create_caregiver_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Caregiver {n}",
        "credential_id": f"HCA-T{n:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(home_id: str, caregiver_id: str,
                         start_at: str, end_at: str,
                         expected_caregiver_version: int, **overrides) -> dict:
    defaults = {
        "home_id": home_id,
        "caregiver_id": caregiver_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_caregiver_version": expected_caregiver_version,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(resident_id: str, occurred_at: str, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "incident_type": "FALL",
        "severity": "MAJOR",
        "occurred_at": occurred_at,
        "description": "Reportable event",
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "payer_type": "PRIVATE_PAY",
        "room_and_board_daily_cents": TEST_DEFAULTS["ROOM_AND_BOARD_DAILY_CENTS"],
        "care_low_daily_cents": TEST_DEFAULTS["CARE_LOW_DAILY_CENTS"],
        "care_medium_daily_cents": TEST_DEFAULTS["CARE_MEDIUM_DAILY_CENTS"],
        "care_high_daily_cents": TEST_DEFAULTS["CARE_HIGH_DAILY_CENTS"],
        "effective_from": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_generate_payload(expected_resident_version: int, **overrides) -> dict:
    defaults = {
        "period_start": "2026-06-01",
        "period_end": "2026-06-11",
        "due_date": "2026-06-20",
        "expected_resident_version": expected_resident_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(resident_id: str, invoice_id: str, amount_cents: int,
                           **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": "CASH",
    }
    defaults.update(overrides)
    return defaults


def create_discharge_payload(**overrides) -> dict:
    defaults = {"reason": "VOLUNTARY", "notice_days": 30}
    defaults.update(overrides)
    return defaults
