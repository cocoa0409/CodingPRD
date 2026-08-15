"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_opportunity_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "sponsor_code": "NSF",
        "title": f"Opportunity {n}",
        "activity_codes_allowed": ["RESEARCH_ON_CAMPUS"],
        "sponsor_deadline_at": TEST_DEFAULTS["SPONSOR_DEADLINE_AT"],
        "internal_lead_days": 5,
        "requires_cost_share": False,
        "min_cost_share_pct_of_request": 0,
    }
    defaults.update(overrides)
    return defaults


def create_pi_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"PI {n}",
        "department_code": "BIO",
        "rank": "FULL",
        "delinquent_report_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_fa_rate_agreement_payload(**overrides) -> dict:
    defaults = {
        "rate_type": "ON_CAMPUS_RESEARCH",
        "rate_pct": TEST_DEFAULTS["RATE_PCT"],
        "effective_start_on": TEST_DEFAULTS["RATE_WINDOW_START"],
        "effective_end_on": TEST_DEFAULTS["RATE_WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_subrecipient_org_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "legal_name": f"Sub Org {n}",
        "uei": f"UEI-{n:08d}",
        "single_audit_status": "CURRENT",
        "audit_finding_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(opportunity_id, pi_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "opportunity_id": opportunity_id,
        "pi_id": pi_id,
        "title": f"Proposal {n}",
        "activity_code": "RESEARCH_ON_CAMPUS",
        "project_start_on": TEST_DEFAULTS["PROJECT_START_ON"],
        "project_end_on": TEST_DEFAULTS["PROJECT_END_ON"],
        "pi_effort_pct": 20.00,
        "fa_base_type": "TDC",
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "category": "PERSONNEL",
        "description": f"line {n}",
        "fiscal_year": 2027,
        "amount_cents": TEST_DEFAULTS["LINE_AMOUNT_CENTS"],
        "is_cost_share": False,
    }
    defaults.update(overrides)
    return defaults


def create_cost_share_payload(**overrides) -> dict:
    defaults = {
        "source_type": "DEPARTMENT",
        "amount_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {"review_type": "IRB"}
    defaults.update(overrides)
    return defaults


def create_sub_commitment_payload(subrecipient_org_id, **overrides) -> dict:
    defaults = {
        "subrecipient_org_id": subrecipient_org_id,
        "subaward_amount_cents": 1_000_000,
        "statement_of_work_received": True,
        "budget_received": True,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(expected_proposal_version, **overrides) -> dict:
    defaults = {
        "expected_proposal_version": expected_proposal_version,
        "origin": "SPONSOR",
        "offered_total_cents": 14_000_000,
    }
    defaults.update(overrides)
    return defaults
