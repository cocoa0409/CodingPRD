"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Program",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "companion_guide_version": TEST_DEFAULTS["COMPANION_GUIDE_VERSION"],
        "penalty_threshold_cents": TEST_DEFAULTS["SAFE_PENALTY_THRESHOLD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "medicaid_id": "M-DEFAULT",
        "aid_category": "TANF",
        "enrolled_from": TEST_DEFAULTS["ENROLLED_FROM"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "npi": TEST_DEFAULTS["NPI"],
        "taxonomy_code": TEST_DEFAULTS["TAXONOMY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_submitter_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "DELEGATE-1",
        "trading_partner_id": "TP1",
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "label": TEST_DEFAULTS["CYCLE_LABEL"],
        "window_start_at": TEST_DEFAULTS["WINDOW_START"],
        "window_end_at": TEST_DEFAULTS["WINDOW_END"],
        "submission_deadline_at": TEST_DEFAULTS["SUBMISSION_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "aid_category": "TANF",
        "pmpm_cents": TEST_DEFAULTS["PMPM_TANF_CENTS"],
        "effective_from": TEST_DEFAULTS["RATE_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["RATE_EFFECTIVE_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_encounter_line(**overrides) -> dict:
    defaults = {
        "line_number": 1,
        "procedure_code": TEST_DEFAULTS["PROCEDURE_CODE"],
        "units": 1,
        "billed_amount_cents": TEST_DEFAULTS["PAID_AMOUNT_CENTS"],
        "paid_amount_cents": TEST_DEFAULTS["PAID_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_encounter_payload(program_id, member_id, provider_id, **overrides) -> dict:
    line = overrides.pop("lines", None) or [create_encounter_line()]
    defaults = {
        "program_id": program_id,
        "member_id": member_id,
        "provider_id": provider_id,
        "encounter_ref": "E1",
        "service_from_date": "2026-08-10",
        "service_to_date": "2026-08-10",
        "place_of_service": TEST_DEFAULTS["PLACE_OF_SERVICE"],
        "diagnosis_codes": ["Z00"],
        "paid_amount_cents": sum(l["paid_amount_cents"] for l in line),
        "lines": line,
    }
    defaults.update(overrides)
    return defaults


def create_replace_payload(**overrides) -> dict:
    line = overrides.pop("lines", None) or [create_encounter_line()]
    defaults = {
        "encounter_ref": "E1R",
        "service_from_date": "2026-08-10",
        "service_to_date": "2026-08-10",
        "place_of_service": TEST_DEFAULTS["PLACE_OF_SERVICE"],
        "diagnosis_codes": ["Z00"],
        "paid_amount_cents": sum(l["paid_amount_cents"] for l in line),
        "lines": line,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(cycle_id, **overrides) -> dict:
    defaults = {"cycle_id": cycle_id}
    defaults.update(overrides)
    return defaults


def create_audit_payload(cycle_id, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "sample_size": 10,
        "defect_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(cycle_id, **overrides) -> dict:
    defaults = {"cycle_id": cycle_id}
    defaults.update(overrides)
    return defaults


def create_acknowledge_outcome(encounter_id, outcome="ACCEPTED", edit_code=None) -> dict:
    entry = {"encounter_id": encounter_id, "outcome": outcome}
    if edit_code is not None:
        entry["edit_code"] = edit_code
    return entry


def create_extension_request_payload(**overrides) -> dict:
    defaults = {
        "requested_new_deadline_at": "2026-09-29T00:00:00Z",
        "reason": "clearinghouse outage",
    }
    defaults.update(overrides)
    return defaults
