"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_npi_counter = itertools.count(1)


def next_npi() -> str:
    """Unique 10-digit NPI per call (PRD: npi unique across providers)."""
    return f"{1000000000 + next(_npi_counter):010d}"


def create_site_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["SITE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Crna One",
        "provider_type": "CRNA",
        "npi": next_npi(),
        "credential_expires_on": TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
        "dea_expires_on": TEST_DEFAULTS["DEA_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr. Avery",
        "provider_type": "ANESTHESIOLOGIST",
        "npi": next_npi(),
        "credential_expires_on": TEST_DEFAULTS["CREDENTIAL_EXPIRES_ON"],
        "dea_expires_on": TEST_DEFAULTS["DEA_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    defaults = {
        "procedure_code": TEST_DEFAULTS["PROCEDURE_CODE"],
        "base_units": TEST_DEFAULTS["FEE_BASE_UNITS"],
        "contracted_max_cents": TEST_DEFAULTS["FEE_CONTRACTED_MAX_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_stipend_agreement_payload(**overrides) -> dict:
    defaults = {
        "effective_from": TEST_DEFAULTS["SERVICE_DATE"],
        "effective_to": TEST_DEFAULTS["SERVICE_DATE"],
        "call_stipend_cents": TEST_DEFAULTS["CALL_STIPEND_CENTS"],
        "late_stay_rate_cents_per_minute": TEST_DEFAULTS["LATE_STAY_RATE_CENTS_PER_MINUTE"],
        "standby_full_cents": TEST_DEFAULTS["STANDBY_FULL_CENTS"],
        "standby_partial_cents": TEST_DEFAULTS["STANDBY_PARTIAL_CENTS"],
    }
    defaults.update(overrides)  # site_id supplied by caller
    return defaults


def create_roster_payload(**overrides) -> dict:
    defaults = {
        "service_date": TEST_DEFAULTS["SERVICE_DATE"],
        "required_primary_slots": TEST_DEFAULTS["REQUIRED_PRIMARY_SLOTS"],
        "scheduled_day_end_minute": TEST_DEFAULTS["SCHEDULED_DAY_END_MINUTE"],
    }
    defaults.update(overrides)  # site_id supplied by caller
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "procedure_code": TEST_DEFAULTS["PROCEDURE_CODE"],
        "physical_status": "P1",
        "scheduled_start_minute": 540,
        "scheduled_end_minute": 600,
    }
    defaults.update(overrides)  # roster_id supplied by caller
    return defaults


def create_assignment_payload(**overrides) -> dict:
    defaults = {"assignment_role": "CASE_PRIMARY"}
    defaults.update(overrides)  # provider_id + expected_case_version supplied by caller
    return defaults


def create_call_assignment_payload(**overrides) -> dict:
    defaults = {"window_start_minute": 1020, "window_end_minute": 1200}
    defaults.update(overrides)  # roster_id + provider_id supplied by caller
    return defaults


def create_attestation_payload(**overrides) -> dict:
    return dict(overrides)  # case_id + physician_id supplied by caller


def all_tefra_steps_true() -> dict:
    """All seven TEFRA step booleans true (PRD §3.5)."""
    return {
        "step_preanesthetic_exam": True,
        "step_prescribes_plan": True,
        "step_participates_key_portions": True,
        "step_ensures_qualified_personnel": True,
        "step_monitors_course": True,
        "step_available_for_emergencies": True,
        "step_post_anesthesia_care": True,
    }


def all_tefra_steps_false() -> dict:
    return {k: False for k in all_tefra_steps_true()}


def create_claim_payload(**overrides) -> dict:
    return dict(overrides)  # case_id + provider_id supplied by caller
