"""Payload factories — one per entity, input fields only (PRD §3)."""

_DEFAULT_OPERATOR_EXPIRY = "2027-01-01T00:00:00Z"


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Plant",
        "state_code": "TX",
        "header_pressure_psi": 150,
    }
    defaults.update(overrides)
    return defaults


def create_boiler_payload(**overrides) -> dict:
    defaults = {
        "tag": "B-101",
        "rated_capacity_lb_hr": 30000,
        "relief_valve_setpoint_psi": 165,
        "relief_valve_tolerance_pct": 3.0,
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Operator",
        "license_class": "CLASS_1",
        "license_state": "TX",
        "license_expires_on": _DEFAULT_OPERATOR_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_log_entry_payload(**overrides) -> dict:
    defaults = {
        "recorded_by_operator_id": None,
        "recorded_at": "2026-08-05T10:00:00Z",
        "header_pressure_reading_psi": 150,
        "steam_generated_lb": 1000,
        "fuel_burned_gal": 8,
        "feedwater_intake_gal": 130,
        "blowdown_gal": 10,
    }
    defaults.update(overrides)
    return defaults


def create_chemistry_log_payload(**overrides) -> dict:
    defaults = {
        "recorded_by_operator_id": None,
        "recorded_at": "2026-08-05T08:00:00Z",
        "conductivity_boiler_umho": 5000,
        "conductivity_feedwater_umho": 1000,
        "sulfite_residual_ppm": 30,
        "phosphate_residual_ppm": 40,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_kind": "ANNUAL_EXTERNAL",
        "scheduled_on": "2026-08-10T08:00:00Z",
        "inspector_name": "Inspector A",
        "inspector_license_no": "LIC-1",
    }
    defaults.update(overrides)
    return defaults


def create_steam_trap_payload(**overrides) -> dict:
    defaults = {
        "tag": "ST-207",
        "location": "HDR-A",
        "orifice_diameter_in": 0.25,
        "design_pressure_psi": 144,
    }
    defaults.update(overrides)
    return defaults


def create_load_dispatch_payload(**overrides) -> dict:
    defaults = {
        "window_start_at": "2026-08-10T00:00:00Z",
        "window_end_at": "2026-08-10T08:00:00Z",
        "target_steam_lb_hr": 20000,
        "assigned_boiler_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "raised_by_operator_id": None,
        "severity": "LOW",
        "kind": "OTHER",
        "raised_at": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fuel_delivery_payload(**overrides) -> dict:
    defaults = {
        "delivered_at": "2026-08-01T08:00:00Z",
        "quantity_gal": 1000,
        "supplier": "Acme Fuel Co",
    }
    defaults.update(overrides)
    return defaults
