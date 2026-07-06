"""Payload factories — one per entity, input fields only (PRD §3).

Only fields the client supplies are emitted; server/computed fields are never sent.
Every factory takes **overrides so tests can control the values that matter and rely
on sensible defaults for the rest.
"""

DEFAULTS = {
    "OWNER_NAME": "Homeowner",
    "OWNER_USER_ID": "owner-1",
    "SITE_ADDRESS": "1 Pool Ln",
    "CONTRACT_PRICE_CENTS": 500000,
    "POOL_GALLONS": 20000,
    "LENGTH_FT": 30,
    "WIDTH_FT": 15,
    "AVG_DEPTH_FT": 5,
    "PHASE_BUDGET_CENTS": 100000,
    "INSPECTOR_NAME": "Insp",
    "SCHEDULED_AT": "2026-06-01T10:00:00Z",
    "COMPANY_NAME": "S",
    "TRADE": "GENERAL",
}


def create_pool_project_payload(**overrides) -> dict:
    payload = {
        "owner_name": DEFAULTS["OWNER_NAME"],
        "owner_user_id": DEFAULTS["OWNER_USER_ID"],
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "contract_price_cents": DEFAULTS["CONTRACT_PRICE_CENTS"],
        "pool_gallons": DEFAULTS["POOL_GALLONS"],
    }
    payload.update(overrides)
    return payload


def create_design_plan_payload(pool_project_id, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "length_ft": DEFAULTS["LENGTH_FT"],
        "width_ft": DEFAULTS["WIDTH_FT"],
        "avg_depth_ft": DEFAULTS["AVG_DEPTH_FT"],
    }
    payload.update(overrides)
    return payload


def create_phase_gate_payload(pool_project_id, phase, budget_cents=None, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "phase": phase,
        "budget_cents": budget_cents if budget_cents is not None else DEFAULTS["PHASE_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(pool_project_id, phase_gate_id, scheduled_at=None,
                              inspector_name=None, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "phase_gate_id": phase_gate_id,
        "inspector_name": inspector_name if inspector_name is not None else DEFAULTS["INSPECTOR_NAME"],
        "scheduled_at": scheduled_at if scheduled_at is not None else DEFAULTS["SCHEDULED_AT"],
    }
    payload.update(overrides)
    return payload


def create_subcontractor_payload(company_name=None, trade=None, **overrides) -> dict:
    payload = {
        "company_name": company_name if company_name is not None else DEFAULTS["COMPANY_NAME"],
        "trade": trade if trade is not None else DEFAULTS["TRADE"],
    }
    payload.update(overrides)
    return payload


def create_crew_assignment_payload(pool_project_id, subcontractor_id, phase_gate_id,
                                   start_at, end_at, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "subcontractor_id": subcontractor_id,
        "phase_gate_id": phase_gate_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_change_order_payload(pool_project_id, category, description,
                                price_delta_cents, phase=None, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "category": category,
        "description": description,
        "price_delta_cents": price_delta_cents,
    }
    if phase is not None:
        payload["phase"] = phase
    payload.update(overrides)
    return payload


def create_draw_request_payload(pool_project_id, phase_gate_id, requested_cents,
                                expected_pool_project_version, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "phase_gate_id": phase_gate_id,
        "requested_cents": requested_cents,
        "expected_pool_project_version": expected_pool_project_version,
    }
    payload.update(overrides)
    return payload


def create_punch_item_payload(pool_project_id, description, severity, **overrides) -> dict:
    payload = {
        "pool_project_id": pool_project_id,
        "description": description,
        "severity": severity,
    }
    payload.update(overrides)
    return payload
