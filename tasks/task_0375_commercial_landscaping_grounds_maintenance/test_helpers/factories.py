"""Payload factories — one per entity, input fields only (PRD Section 3)."""


def create_account_payload(**overrides) -> dict:
    payload = {"name": "Greens Co", "region_code": "NE"}
    payload.update(overrides)
    return payload


def create_site_payload(service_account_id, **overrides) -> dict:
    payload = {
        "service_account_id": service_account_id,
        "name": "Plaza",
        "address": "1 Main",
        "turf_area_sqft": 5000,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(service_account_id, site_id, **overrides) -> dict:
    payload = {
        "service_account_id": service_account_id,
        "site_id": site_id,
        "annual_budget_cents": 100000000,
        "billing_cycle": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_plan_payload(service_contract_id, **overrides) -> dict:
    payload = {
        "service_contract_id": service_contract_id,
        "service_type": "MOWING",
        "frequency": "WEEKLY",
        "base_rate_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_crew_payload(service_account_id, **overrides) -> dict:
    payload = {
        "service_account_id": service_account_id,
        "name": "Crew A",
        "hourly_rate_cents": 6000,
    }
    payload.update(overrides)
    return payload


def create_route_payload(crew_id, **overrides) -> dict:
    payload = {
        "crew_id": crew_id,
        "route_date": "2026-06-01",
        "shift_start_minute": 400,
        "shift_end_minute": 800,
    }
    payload.update(overrides)
    return payload


def create_visit_payload(service_plan_id, route_schedule_id, expected_service_contract_version, **overrides) -> dict:
    payload = {
        "service_plan_id": service_plan_id,
        "route_schedule_id": route_schedule_id,
        "slot_start_minute": 480,
        "slot_duration_minute": 90,
        "expected_service_contract_version": expected_service_contract_version,
    }
    payload.update(overrides)
    return payload


def create_addon_payload(service_visit_id, **overrides) -> dict:
    payload = {
        "service_visit_id": service_visit_id,
        "addon_type": "MULCH_INSTALL",
        "quantity": 15,
        "unit_price_cents": 333,
    }
    payload.update(overrides)
    return payload


def create_equipment_payload(service_account_id, **overrides) -> dict:
    payload = {
        "service_account_id": service_account_id,
        "name": "Mower 3",
        "hourly_usage_cost_cents": 3000,
        "service_interval_hours": 100,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(equipment_asset_id, service_visit_id, **overrides) -> dict:
    payload = {
        "equipment_asset_id": equipment_asset_id,
        "service_visit_id": service_visit_id,
        "window_start_minute": 480,
        "window_end_minute": 600,
    }
    payload.update(overrides)
    return payload


def create_storm_event_payload(site_id, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "snowfall_inches": 5,
        "response_deadline_minute": 600,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(service_visit_id, **overrides) -> dict:
    payload = {"service_visit_id": service_visit_id}
    payload.update(overrides)
    return payload


def create_invoice_payload(service_contract_id, period_label, **overrides) -> dict:
    payload = {
        "service_contract_id": service_contract_id,
        "period_label": period_label,
    }
    payload.update(overrides)
    return payload
