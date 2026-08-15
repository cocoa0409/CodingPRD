"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import STANDARD_LIST_DATE, STANDARD_LOAN, STANDARD_VACATE_DATE

_counter = {"n": 0}


def _unique(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


def create_loan_payload(**overrides) -> dict:
    defaults = dict(STANDARD_LOAN)
    defaults["loan_number"] = _unique("LN")
    defaults.update(overrides)
    return defaults


def create_borrower_payload(**overrides) -> dict:
    defaults = {
        "full_name": "A. Borrower",
        "email": "borrower@example.com",
        "hardship_type": "MEDICAL",
        "self_reported_condition_grade": "B",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(loan_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "address_line": "1 Main St",
        "county": "Maricopa",
        "state_code": "AZ",
        "occupancy_type": "OWNER_OCCUPIED",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(loan_id, borrower_id, **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "borrower_id": borrower_id,
        "program_type": "DEED_IN_LIEU",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "list_date": STANDARD_LIST_DATE,
        "list_price_cents": 19000000,
    }
    defaults.update(overrides)
    return defaults


def create_title_commitment_payload(case_id, **overrides) -> dict:
    defaults = {"case_id": case_id}
    defaults.update(overrides)
    return defaults


def create_lien_payload(**overrides) -> dict:
    defaults = {
        "lienholder_name": "HOA Corp",
        "amount_cents": 50000,
        "position": 2,
    }
    defaults.update(overrides)
    return defaults


def create_lien_release_payload(lien_id, settlement_amount_cents, expected_title_commitment_version, **overrides) -> dict:
    defaults = {
        "lien_id": lien_id,
        "settlement_amount_cents": settlement_amount_cents,
        "expected_title_commitment_version": expected_title_commitment_version,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(expected_case_version, **overrides) -> dict:
    defaults = {
        "vacate_date": STANDARD_VACATE_DATE,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "inspector_id": "insp_1",
        "appointment_type": "HANDOVER",
        "scheduled_start": "2026-09-01T10:00:00Z",
        "scheduled_end": "2026-09-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "broom_clean_verified": True,
        "keys_returned_count": 2,
        "line_items": [],
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(agreement_id, amount_cents, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_deed_recording_payload(**overrides) -> dict:
    defaults = {"county": "Maricopa"}
    defaults.update(overrides)
    return defaults
