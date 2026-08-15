"""Payload factories — one per creatable entity, input fields only."""
import uuid

DEFAULTS = {
    "AGENCY_NAME": "Apex Sports",
    "FEE_CAP_PCT": 0.03,
    "TEAM_NAME": "Meteor FC",
    "LEAGUE_CODE": "NBA",
    "SEASON_YEAR": 2026,
    "CAP_LIMIT_CENTS": 500_000_000,
    "LUXURY_THRESHOLD_CENTS": 600_000_000,
    "POSITION": "PG",
    "BASE_SALARY_CENTS": 10_000_000,
    "DEAL_VALUE_CENTS": 50_000_000,
    "START_DATE": "2026-08-01T00:00:00Z",
    "END_DATE": "2027-08-01T00:00:00Z",
}


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["AGENCY_NAME"],
        "fee_cap_pct": DEFAULTS["FEE_CAP_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    tag = _uniq("agent")
    defaults = {
        "full_name": f"Agent {tag}",
        "email": f"{tag}@example.com",
        "cert_number": f"CERT-{tag}",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(primary_agent_id: str, **overrides) -> dict:
    defaults = {
        "primary_agent_id": primary_agent_id,
        "full_name": f"Player {_uniq('client')}",
        "position": DEFAULTS["POSITION"],
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    defaults = {
        "name": f"{DEFAULTS['TEAM_NAME']} {_uniq('team')}",
        "league_code": DEFAULTS["LEAGUE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_cap_season_payload(**overrides) -> dict:
    defaults = {
        "season_year": DEFAULTS["SEASON_YEAR"],
        "cap_limit_cents": DEFAULTS["CAP_LIMIT_CENTS"],
        "luxury_threshold_cents": DEFAULTS["LUXURY_THRESHOLD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(team_id: str, cap_season_id: str, **overrides) -> dict:
    defaults = {
        "team_id": team_id,
        "cap_season_id": cap_season_id,
        "start_season_year": DEFAULTS["SEASON_YEAR"],
        "years": 1,
        "base_salary_cents": DEFAULTS["BASE_SALARY_CENTS"],
        "guaranteed_cents": DEFAULTS["BASE_SALARY_CENTS"],
        "signing_bonus_cents": 0,
        "incentive_cents": 0,
        "escalator_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(proposed_by_agent_id: str, **overrides) -> dict:
    defaults = {
        "proposed_by_agent_id": proposed_by_agent_id,
        "proposed_aav_cents": DEFAULTS["BASE_SALARY_CENTS"],
        "proposed_guaranteed_cents": DEFAULTS["BASE_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(**overrides) -> dict:
    defaults = {
        "brand_name": f"Brand {_uniq('brand')}",
        "deal_value_cents": DEFAULTS["DEAL_VALUE_CENTS"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_tender_option_payload(**overrides) -> dict:
    defaults = {
        "kind": "TEAM_OPTION",
        "window_open_at": "2026-08-10T00:00:00Z",
        "window_close_at": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_grievance_payload(filed_by_agent_id: str, **overrides) -> dict:
    defaults = {
        "filed_by_agent_id": filed_by_agent_id,
        "category": "NON_PAYMENT",
        "description": "Grievance narrative",
        "claimed_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults
