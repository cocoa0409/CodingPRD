"""Payload factories — one per entity, input fields only (PRD section 4).

Default dates are consistent with the logical clock's startup default of
2026-08-01T00:00:00Z (PRD section 2.5): requested delivery dates fall on or
after the default clock date, and adverse-event awareness defaults 12 hours
before it (inside the 24-hour reporting window).
"""
from .constants import TEST_DEFAULTS


def create_drug_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Prog",
        "manufacturer_name": "Mfr",
        "diagnosis_code": TEST_DEFAULTS["DIAGNOSIS_CODE"],
        "requires_injection_training": False,
        "requires_cold_chain": False,
        "max_transit_hours": 0,
        "min_days_between_fills": TEST_DEFAULTS["MIN_DAYS_BETWEEN_FILLS"],
        "copay_card_per_fill_cap_cents": TEST_DEFAULTS["CARD_PER_FILL_CAP_CENTS"],
        "copay_card_annual_cap_cents": TEST_DEFAULTS["CARD_ANNUAL_CAP_CENTS"],
        "default_days_supply": TEST_DEFAULTS["DEFAULT_DAYS_SUPPLY"],
    }
    defaults.update(overrides)
    return defaults


def create_foundation_pool_payload(**overrides) -> dict:
    defaults = {
        "name": "Fund",
        "diagnosis_code": TEST_DEFAULTS["DIAGNOSIS_CODE"],
        "total_funding_cents": TEST_DEFAULTS["POOL_TOTAL_FUNDING_CENTS"],
        "grant_amount_cents": TEST_DEFAULTS["POOL_GRANT_AMOUNT_CENTS"],
        "coverage_pct": TEST_DEFAULTS["POOL_COVERAGE_PCT"],
        "start_date": TEST_DEFAULTS["POOL_START_DATE"],
        "end_date": TEST_DEFAULTS["POOL_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "patient_ref": "PAT-1",
        "diagnosis_code": TEST_DEFAULTS["DIAGNOSIS_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_bi_payload(**overrides) -> dict:
    defaults = {
        "payer_name": "Acme",
        "member_id": "M-1",
        "requires_prior_auth": False,
        "plan_has_accumulator": False,
        "patient_cost_share_cents": TEST_DEFAULTS["PATIENT_COST_SHARE_CENTS"],
        "oop_max_cents": TEST_DEFAULTS["OOP_MAX_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pa_payload(**overrides) -> dict:
    defaults = {
        "clinical_notes": "notes",
        "payer_reference": "PA-1",
    }
    defaults.update(overrides)
    return defaults


def pa_decision_payload(outcome="APPROVED", **overrides) -> dict:
    defaults = {"outcome": outcome, "rationale": "criteria met"}
    defaults.update(overrides)
    return defaults


def pa_appeal_payload(**overrides) -> dict:
    defaults = {"clinical_notes": "additional chart notes"}
    defaults.update(overrides)
    return defaults


def match_assistance_payload(expected_enrollment_version,
                             assistance_type="COPAY_CARD", **overrides) -> dict:
    defaults = {
        "assistance_type": assistance_type,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "requested_delivery_date": "2026-08-03",
        "transit_hours": TEST_DEFAULTS["TRANSIT_HOURS"],
        "days_supply": TEST_DEFAULTS["DEFAULT_DAYS_SUPPLY"],
    }
    defaults.update(overrides)
    return defaults


def deliver_shipment_payload(delivered_date="2026-08-03", **overrides) -> dict:
    defaults = {"delivered_date": delivered_date}
    defaults.update(overrides)
    return defaults


def create_nurse_visit_payload(**overrides) -> dict:
    defaults = {
        "nurse_id": "nurse-1",
        "window_start": "2026-08-02T14:00:00Z",
        "window_end": "2026-08-02T15:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def resolve_visit_payload(outcome="COMPLETED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_adverse_event_payload(**overrides) -> dict:
    # 12 hours before the startup-default clock: inside the 24-hour window.
    defaults = {
        "awareness_at": "2026-07-31T12:00:00Z",
        "seriousness": "NON_SERIOUS",
        "description": "mild rash",
    }
    defaults.update(overrides)
    return defaults


def create_outcome_report_payload(expected_enrollment_version,
                                  **overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01",
        "period_end": "2026-09-01",
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
