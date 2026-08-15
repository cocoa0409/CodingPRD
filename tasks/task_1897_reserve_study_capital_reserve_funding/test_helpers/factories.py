"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import RULE_CA, RULE_NV, RULE_TX

_RULES_BY_STATE = {r["state_code"]: r for r in (RULE_CA, RULE_NV, RULE_TX)}


def create_state_rule_payload(**overrides) -> dict:
    """State-rule payload seeded from the canonical preset for its
    `state_code` (constants.RULE_*); unknown codes fall back to RULE_CA's
    shape with the caller's state_code applied."""
    state_code = overrides.get("state_code", "CA")
    defaults = dict(_RULES_BY_STATE.get(state_code, RULE_CA))
    defaults["state_code"] = state_code
    defaults.update(overrides)
    return defaults


def create_association_payload(state_code="CA", **overrides) -> dict:
    defaults = {
        "name": "Test HOA",
        "state_code": state_code,
        "fiscal_year_end_month": 12,
        "reserve_cash_balance_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_study_payload(association_id, **overrides) -> dict:
    defaults = {
        "association_id": association_id,
        "fiscal_year": 2026,
        "study_type": "FULL",
        "inflation_rate": 0.03,
        "interest_rate": 0.02,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "name": "Roof",
        "category": "ROOFING",
        "useful_life_years": 5,
        "remaining_useful_life_years": 2,
        "current_replacement_cost_cents": 100000,
        "is_included_in_funding": True,
    }
    defaults.update(overrides)
    return defaults


def create_funding_plan_payload(plan_type, expected_study_version) -> dict:
    return {
        "plan_type": plan_type,
        "expected_study_version": expected_study_version,
    }


def create_site_visit_payload(association_id, visit_date="2026-06-30",
                              **overrides) -> dict:
    defaults = {
        "association_id": association_id,
        "visit_date": visit_date,
    }
    defaults.update(overrides)
    return defaults


def create_expenditure_payload(association_id, component_id, **overrides) -> dict:
    defaults = {
        "association_id": association_id,
        "component_id": component_id,
        "amount_cents": 5000,
        "incurred_date": "2026-05-10",
        "kind": "UNPLANNED_REPAIR",
    }
    defaults.update(overrides)
    return defaults
