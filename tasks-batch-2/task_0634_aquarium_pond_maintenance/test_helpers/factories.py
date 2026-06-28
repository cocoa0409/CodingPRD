"""Payload factories — one per entity, input fields only."""


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "customer_name": "Acme Aquatics",
        "customer_user_id": "owner-1",
        "service_tier": "BASIC",
        "route_day": "MON",
    }
    defaults.update(overrides)
    return defaults


def create_system_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "label": "Display Tank",
        "system_kind": "FRESHWATER",
        "nominal_volume_l": 200,
    }
    defaults.update(overrides)
    return defaults


def create_livestock_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "common_name": "Tetra",
        "species_class": "COMMUNITY",
        "adult_length_cm": 4,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "device_kind": "FILTER",
        "media_interval_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "tech_user_id": "tech-1",
        "full_name": "Tia Tech",
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(system_id, technician_id, expected_system_version, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "technician_id": technician_id,
        "scheduled_start": "2026-02-02T09:00:00Z",
        "scheduled_end": "2026-02-02T10:00:00Z",
        "expected_system_version": expected_system_version,
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(labor_minutes=30, **overrides) -> dict:
    defaults = {"labor_minutes": labor_minutes}
    defaults.update(overrides)
    return defaults


def create_water_test_payload(**overrides) -> dict:
    defaults = {
        "parameter": "PH",
        "measured_value": 7.0,
        "target_value": 8.0,
        "product_strength_ppm_per_ml": 50,
    }
    defaults.update(overrides)
    return defaults


def create_install_payload(contract_id, system_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "system_id": system_id,
        "labor_estimate_cents": 40000,
        "equipment_estimate_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def handoff_install_payload(actual_labor_minutes=360, actual_equipment_cents=135000, **overrides) -> dict:
    defaults = {
        "actual_labor_minutes": actual_labor_minutes,
        "actual_equipment_cents": actual_equipment_cents,
    }
    defaults.update(overrides)
    return defaults


def create_emergency_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "severity": "HIGH",
        "reported_at": "2026-02-03T08:00:00Z",
        "trip_fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def dispatch_emergency_payload(technician_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "scheduled_start": "2026-02-03T09:00:00Z",
        "scheduled_end": "2026-02-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_repair_payload(equipment_id, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "reported_symptom": "leak",
    }
    defaults.update(overrides)
    return defaults


def create_quarantine_payload(livestock_id, quarantine_tank_id, expected_tank_version, **overrides) -> dict:
    defaults = {
        "livestock_id": livestock_id,
        "quarantine_tank_id": quarantine_tank_id,
        "window_start": "2026-03-01T00:00:00Z",
        "window_end": "2026-03-03T00:00:00Z",
        "expected_tank_version": expected_tank_version,
    }
    defaults.update(overrides)
    return defaults


def create_feeding_plan_payload(system_id, **overrides) -> dict:
    defaults = {
        "system_id": system_id,
        "window_start": "2026-07-01T00:00:00Z",
        "window_end": "2026-07-10T00:00:00Z",
        "feedings_per_day": 2,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
