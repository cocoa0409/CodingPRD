"""Payload factories — one per entity, input fields only (PRD §3)."""

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_client_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "name": f"Client {n}",
        "contact_email": f"ops{n}@client.example",
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(client_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "client_id": client_id,
        "name": f"Facility {n}",
        "address": f"{n} Industrial Way",
        "gross_square_feet": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_asset_system_payload(facility_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "facility_id": facility_id,
        "system_category": "HVAC",
        "name": f"System {n}",
        "install_year": 2010,
        "design_life_years": 25,
        "replacement_cost_cents": 100_000_000,
        "condition_rating": 3,
    }
    defaults.update(overrides)
    return defaults


def create_deficiency_payload(asset_system_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "asset_system_id": asset_system_id,
        "description": f"Finding {n}",
        "cost_estimate_cents": 1_000_000,
        "severity": 3,
        "urgency": 3,
        "recommended_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_capital_plan_payload(facility_id, expected_facility_version,
                                **overrides) -> dict:
    n = _seq()
    defaults = {
        "facility_id": facility_id,
        "title": f"Capital Plan {n}",
        "start_year": 2027,
        "horizon_years": 1,
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults


def create_funding_scenario_payload(capital_plan_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "capital_plan_id": capital_plan_id,
        "name": f"Scenario {n}",
        "annual_budget_cents": 500_000_000,
        "escalation_rate": 0.0,
    }
    defaults.update(overrides)
    return defaults


def run_scenario_payload(expected_capital_plan_version) -> dict:
    return {"expected_capital_plan_version": expected_capital_plan_version}


def create_project_bundle_payload(capital_plan_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "capital_plan_id": capital_plan_id,
        "name": f"Bundle {n}",
        "phase_number": 1,
    }
    defaults.update(overrides)
    return defaults


def assess_payload(condition_rating, note=None) -> dict:
    payload = {"condition_rating": condition_rating}
    if note is not None:
        payload["note"] = note
    return payload
