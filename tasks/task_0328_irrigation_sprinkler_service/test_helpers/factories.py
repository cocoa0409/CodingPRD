"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Test Customer Co",
        "contact_email": "test@example.com",
        "billing_zip": "94016",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Technician",
        "shift_start_sec": 28800,   # 08:00
        "shift_end_sec": 64800,     # 18:00
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_address": "1 Test St",
        "lat": 37.7,
        "lng": -122.4,
    }
    defaults.update(overrides)
    return defaults


def create_system_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "controller_model": "Hunter",
        "static_psi": 60,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(system_id, zone_number, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "zone_number": zone_number,
        "plant_type": "TURF",
        "head_count": 8,
        "gpm_per_head": 18,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(system_id, slots, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "slots": slots,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(property_id, quote_type, line_items, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "quote_type": quote_type,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(system_id, job_type, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "job_type": job_type,
        "estimated_minutes": 30,
        "estimated_cost_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def complete_work_order_payload(**overrides) -> dict:
    defaults = {
        "actual_labor_cents": 0,
        "actual_parts_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(property_id, tier, visits_per_year, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "tier": tier,
        "visits_per_year": visits_per_year,
    }
    defaults.update(overrides)
    return defaults


def create_backflow_test_payload(system_id, tester_technician_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "tester_technician_id": tester_technician_id,
        "relief_open_psi": 5,
        "checkvalve_hold_psi": 3,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(technician_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "route_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(route_id, work_order_id, expected_route_version, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "work_order_id": work_order_id,
        "arrival_start_sec": 28800,
        "window_minutes": 60,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults
