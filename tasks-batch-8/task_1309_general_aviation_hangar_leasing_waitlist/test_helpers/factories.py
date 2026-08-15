"""Payload factories — one per writable endpoint, input fields only (PRD §3, §4)."""
from .constants import (
    DEFAULT_AIRPORT_CONFIG,
    DEFAULT_INSURANCE_EFFECTIVE_FROM,
    DEFAULT_INSURANCE_EFFECTIVE_TO,
    MIN_LIABILITY_COVERAGE_CENTS,
)

_n_counter = [0]


def next_n_number() -> str:
    """Generate a unique tail number per call (tests share a fresh DB per test,
    but several aircraft may be created within one test)."""
    _n_counter[0] += 1
    return f"N{100 + _n_counter[0]}TT"


def create_airport_payload(**overrides) -> dict:
    defaults = {
        "airport_code": "KTST",
        "name": "Test Field",
        "escalation_pct": DEFAULT_AIRPORT_CONFIG["escalation_pct"],
        "escalation_policy": DEFAULT_AIRPORT_CONFIG["escalation_policy"],
        "offer_acceptance_window_hours": DEFAULT_AIRPORT_CONFIG["offer_acceptance_window_hours"],
        "cure_window_days": DEFAULT_AIRPORT_CONFIG["cure_window_days"],
        "late_fee_grace_days": DEFAULT_AIRPORT_CONFIG["late_fee_grace_days"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "airport_id": None,
        "size_class": "T_HANGAR",
        "monthly_rate_cents": 90000,
        "effective_from": "2026-07-01T00:00:00Z",
        "effective_to": "OPEN",
    }
    defaults.update(overrides)
    return defaults


def create_hangar_payload(**overrides) -> dict:
    defaults = {
        "airport_id": None,
        "hangar_code": "T-1",
        "size_class": "T_HANGAR",
        "door_type": "SLIDING",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "airport_id": None,
        "applicant_name": "Test Applicant",
        "applicant_contact": "applicant@example.com",
        "size_class_requested": "T_HANGAR",
        "aircraft_n_number": next_n_number(),
        "is_based_tenant_transfer": False,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "airport_id": None,
        "hangar_id": None,
        "application_id": None,
    }
    defaults.update(overrides)
    return defaults


def accept_offer_payload(**overrides) -> dict:
    """Acceptance payload (PRD §3.4): OCC guard, attestations, initial
    insurance evidence, and the first based aircraft."""
    defaults = {
        "expected_hangar_version": None,
        "aeronautical_use_attested": True,
        "sublease_allowed": False,
        "insurance_policy_number": "POL-TEST",
        "insurance_insurer_name": "Avemco",
        "insurance_liability_coverage_cents": MIN_LIABILITY_COVERAGE_CENTS,
        "insurance_effective_from": DEFAULT_INSURANCE_EFFECTIVE_FROM,
        "insurance_effective_to": DEFAULT_INSURANCE_EFFECTIVE_TO,
        "aircraft_n_number": next_n_number(),
        "aircraft_make_model": "Cessna 172",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": 0}
    defaults.update(overrides)
    return defaults


def terminate_lease_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "n_number": next_n_number(),
        "make_model": "Piper PA-28",
        "is_primary": False,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(**overrides) -> dict:
    defaults = {
        "insurer_name": "Avemco",
        "policy_number": "POL-TEST",
        "liability_coverage_cents": MIN_LIABILITY_COVERAGE_CENTS,
        "effective_from": DEFAULT_INSURANCE_EFFECTIVE_FROM,
        "effective_to": DEFAULT_INSURANCE_EFFECTIVE_TO,
    }
    defaults.update(overrides)
    return defaults


def create_environmental_record_payload(**overrides) -> dict:
    defaults = {
        "record_type": "FUEL_STORAGE_PERMIT",
        "expires_at": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def review_environmental_record_payload(**overrides) -> dict:
    defaults = {"review_note": "reviewed"}
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "condition_rating": "GOOD",
        "maintenance_responsibility": "AIRPORT",
        "deficiency_note": "none",
    }
    defaults.update(overrides)
    return defaults


def close_inspection_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def file_audit_finding_payload(**overrides) -> dict:
    defaults = {"finding_type": "NON_AERONAUTICAL_USE"}
    defaults.update(overrides)
    return defaults


def file_eviction_case_payload(**overrides) -> dict:
    defaults = {"reason": "DELINQUENCY"}
    defaults.update(overrides)
    return defaults


def execute_eviction_case_payload(**overrides) -> dict:
    defaults = {"expected_lease_version": None}
    defaults.update(overrides)
    return defaults


def set_clock_payload(**overrides) -> dict:
    defaults = {"to_iso8601": "2026-08-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults
