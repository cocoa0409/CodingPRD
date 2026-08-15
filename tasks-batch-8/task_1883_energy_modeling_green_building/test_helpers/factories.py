"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "GROSS_FLOOR_AREA_SQFT": 120000,
    "FEE_BUDGET_CENTS": 5000000,
    "BASELINE_MODELED_CENTS": 12000000,
    "BASELINE_CONFIRMED_CENTS": 12000000,
    "PROPOSED_MODELED_CENTS": 11400000,
    "PROPOSED_CONFIRMED_CENTS": 11400000,
    "MODELING_STANDARD": "ASHRAE_90_1_2019",
    "CX_START": "2026-09-01T09:00:00Z",
    "CX_END": "2026-09-01T12:00:00Z",
    "INCREMENTAL_COST_CENTS": 50000000,
    "ACTUAL_ENERGY_COST_CENTS": 12000000,
}


def create_team_member_payload(**overrides) -> dict:
    """Team member registration payload (PRD §3.1). is_independent is omitted by
    default so the server-side default (false) applies."""
    defaults = {
        "full_name": "Pat Person",
        "email": "pat@example.com",
        "specialty": "MANAGEMENT",
    }
    defaults.update(overrides)
    return defaults


def create_credit_library_entry_payload(**overrides) -> dict:
    defaults = {
        "credit_code": "WEc1",
        "title": "Water Efficiency",
        "category": "WATER",
        "points_possible": 10,
        "is_prerequisite": False,
        "phase_eligibility": "DESIGN",
        "requires_energy_model": False,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {
        "project_name": "Test Tower",
        "rating_system": "LEED_BD_C",
        "compliance_path": "PRESCRIPTIVE",
        "gross_floor_area_sqft": DEFAULTS["GROSS_FLOOR_AREA_SQFT"],
        "target_level": "CERTIFIED",
        "fee_budget_cents": DEFAULTS["FEE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_energy_model_payload(project_id, expected_project_version, **overrides) -> dict:
    """Energy model create payload (PRD §3.3); OCC-guarded on the project version."""
    defaults = {
        "project_id": project_id,
        "model_type": "BASELINE",
        "modeling_standard": DEFAULTS["MODELING_STANDARD"],
        "annual_energy_cost_modeled_cents": DEFAULTS["BASELINE_MODELED_CENTS"],
        "annual_energy_cost_confirmed_only_cents": DEFAULTS["BASELINE_CONFIRMED_CENTS"],
        "includes_unconfirmed_measures": False,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_credit_attempt_payload(project_id, credit_library_entry_id,
                                  documentation_owner_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "credit_library_entry_id": credit_library_entry_id,
        "phase": "DESIGN",
        "documentation_owner_id": documentation_owner_id,
    }
    defaults.update(overrides)
    return defaults


def create_review_comment_payload(credit_attempt_id, **overrides) -> dict:
    defaults = {
        "credit_attempt_id": credit_attempt_id,
        "severity": "CLARIFICATION",
        "comment_text": "Please clarify the documentation scope.",
    }
    defaults.update(overrides)
    return defaults


def create_commissioning_task_payload(project_id, agent_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "task_type": "FUNCTIONAL_TESTING",
        "agent_id": agent_id,
        "scheduled_start": DEFAULTS["CX_START"],
        "scheduled_end": DEFAULTS["CX_END"],
        "is_prerequisite_linked": True,
    }
    defaults.update(overrides)
    return defaults


def create_incentive_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": "State Green Grant",
        "incentive_type": "GRANT",
        "benefit_amount_cents": 8000000,
        "minimum_certification_level": "CERTIFIED",
        "is_combinable": True,
    }
    defaults.update(overrides)
    return defaults


def create_project_incentive_payload(project_id, incentive_program_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "incentive_program_id": incentive_program_id,
    }
    defaults.update(overrides)
    return defaults


def create_cost_premium_analysis_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "incremental_construction_cost_cents": DEFAULTS["INCREMENTAL_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_performance_report_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "period_start": "2027-01-01T00:00:00Z",
        "period_end": "2027-12-31T00:00:00Z",
        "actual_annual_energy_cost_cents": DEFAULTS["ACTUAL_ENERGY_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults
