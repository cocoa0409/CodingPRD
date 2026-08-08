"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "OPERATOR_NAME": "CableCo",
    "TERRITORY_NAME": "North Ward",
    "HOMES_IN_TERRITORY": 10000,
    "ROAD_MILES": 50,
    "FEE_RATE_PCT": 0.05,
    "TERM_START": "2026-01-01",
    "TERM_END": "2036-01-01",
}


def create_franchise_payload(**overrides) -> dict:
    payload = {
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "territory_name": DEFAULTS["TERRITORY_NAME"],
        "homes_in_territory": DEFAULTS["HOMES_IN_TERRITORY"],
        "road_miles": DEFAULTS["ROAD_MILES"],
        "fee_rate_pct": DEFAULTS["FEE_RATE_PCT"],
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
    }
    payload.update(overrides)
    return payload


def create_row_segment_payload(**overrides) -> dict:
    payload = {
        "name": "Main St 100-400",
        "length_miles": 0.4,
        "homes_along": 120,
    }
    payload.update(overrides)
    return payload


def create_row_permit_payload(franchise_id, row_segment_id, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "row_segment_id": row_segment_id,
        "window_start": "2026-06-01T00:00:00Z",
        "window_end": "2026-06-02T00:00:00Z",
        "purpose": "conduit",
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(franchise_id, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "label": "Y2 density",
        "deadline_date": "2026-08-01",
        "required_pct": 0.60,
    }
    payload.update(overrides)
    return payload


def create_revenue_report_payload(franchise_id, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "period_start_date": "2026-01-01",
        "period_end_date": "2026-03-31",
        "residential_gross_cents": 100010,
        "commercial_gross_cents": 50010,
        "advertising_gross_cents": 33330,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(franchise_id, target_report_id, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "target_report_id": target_report_id,
        "period_start_date": "2026-01-01",
        "period_end_date": "2026-03-31",
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(franchise_id, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "category": "SERVICE_INTERRUPTION",
        "description": "No service since morning",
    }
    payload.update(overrides)
    return payload


def create_peg_contribution_payload(franchise_id, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "amount_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_application_payload(franchise_id, application_type, expected_franchise_version, **overrides) -> dict:
    payload = {
        "franchise_id": franchise_id,
        "application_type": application_type,
        "expected_franchise_version": expected_franchise_version,
    }
    payload.update(overrides)
    return payload
