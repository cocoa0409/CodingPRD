"""Payload factories — one per writable endpoint, input fields only (PRD §3)."""
from .constants import ELIGIBLE_TEMPLATE_BASE, TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    """POST /api/survey-programs input: name, sampling_protocol, admin_mode."""
    defaults = {
        "name": "Test Program",
        "sampling_protocol": "CENSUS",
        "admin_mode": "MAIL_ONLY",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(program_id: str, expected_program_version: int,
                          **overrides) -> dict:
    """POST /api/vendors input; expected_program_version is the OCC field
    required by PRD §2.10."""
    defaults = {
        "program_id": program_id,
        "name": "Vendor 1",
        "cycle_budget_cents": TEST_DEFAULTS["VENDOR_BUDGET_CENTS"],
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": "Unit 1",
        "unit_code": "U1",
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "full_name": "Dr A",
        "npi": "NPI1",
        "specialty": "IM",
    }
    defaults.update(overrides)
    return defaults


def create_discharge_payload(program_id: str, unit_id: str, provider_id: str,
                             **overrides) -> dict:
    """POST /api/discharges input. Defaults describe an eligible patient."""
    defaults = {
        "program_id": program_id,
        "mrn": "M-001",
        "unit_id": unit_id,
        "provider_id": provider_id,
    }
    defaults.update(ELIGIBLE_TEMPLATE_BASE)
    defaults.update(overrides)
    return defaults


def create_discharge_import_payload(program_id: str, unit_id: str,
                                    provider_id: str, count: int,
                                    **template_overrides) -> dict:
    """POST /api/discharges/import input: count + shared template (PRD §3.2)."""
    template = {"mrn_prefix": "M", "unit_id": unit_id, "provider_id": provider_id}
    template.update(ELIGIBLE_TEMPLATE_BASE)
    template.update(template_overrides)
    return {"program_id": program_id, "count": count, "template": template}


def create_cycle_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "label": "Q1",
        "cycle_index": 1,
        "discharge_window_start": TEST_DEFAULTS["DISCHARGE_WINDOW_START"],
        "discharge_window_end": TEST_DEFAULTS["DISCHARGE_WINDOW_END"],
        "fielding_start_date": TEST_DEFAULTS["FIELDING_START_DATE"],
        "fielding_end_date": TEST_DEFAULTS["FIELDING_END_DATE"],
        "target_sample_size": TEST_DEFAULTS["TARGET_SAMPLE_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_sample_case_payload(cycle_id: str, discharge_id: str,
                               **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "discharge_id": discharge_id,
        "mode_assigned": "MAIL",
        "postage_cost_cents": TEST_DEFAULTS["POSTAGE_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_sample_case_import_payload(cycle_id: str, discharge_ids: list,
                                      **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "discharge_ids": list(discharge_ids),
        "mode_assigned": "MAIL",
        "postage_cost_cents": TEST_DEFAULTS["POSTAGE_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_response_payload(case_id: str, **overrides) -> dict:
    """POST /api/responses input; default scores are all top-box (4)."""
    defaults = {
        "case_id": case_id,
        "mode_used": "MAIL",
        "nurse_comm_score": 4,
        "doctor_comm_score": 4,
        "cleanliness_score": 4,
        "overall_rating_score": 4,
    }
    defaults.update(overrides)
    return defaults


def create_response_import_payload(case_ids: list, **overrides) -> dict:
    defaults = {
        "case_ids": list(case_ids),
        "mode_used": "MAIL",
        "nurse_comm_score": 4,
        "doctor_comm_score": 4,
        "cleanliness_score": 4,
        "overall_rating_score": 4,
    }
    defaults.update(overrides)
    return defaults


def adjudicate_payload(decision: str) -> dict:
    return {"decision": decision}


def void_response_payload(reason: str = "duplicate submission") -> dict:
    return {"reason": reason}


def create_initiative_payload(unit_id: str, domain: str, baseline_cycle_id: str,
                              evaluation_cycle_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "domain": domain,
        "baseline_cycle_id": baseline_cycle_id,
        "evaluation_cycle_id": evaluation_cycle_id,
        "target_score": 85.0,
    }
    defaults.update(overrides)
    return defaults


def replan_initiative_payload(evaluation_cycle_id: str, target_score: float) -> dict:
    return {
        "evaluation_cycle_id": evaluation_cycle_id,
        "target_score": target_score,
    }


def create_ticket_payload(unit_id: str, response_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "response_id": response_id,
        "domain": "OVERALL_RATING",
        "priority": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def resolve_ticket_payload(resolution_note: str = "called patient") -> dict:
    return {"resolution_note": resolution_note}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
