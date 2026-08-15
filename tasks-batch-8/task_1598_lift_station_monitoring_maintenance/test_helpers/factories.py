"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

_code_counter = {"n": 0}


def _next_seq() -> int:
    _code_counter["n"] += 1
    return _code_counter["n"]


def station_code(seq: int = None) -> str:
    """Unique regulatory station code matching ^LS-[0-9]{4}$ (PRD §3.1)."""
    n = _next_seq() if seq is None else seq
    return f"LS-{n % 10000:04d}"


def employee_code(seq: int = None) -> str:
    n = _next_seq() if seq is None else seq
    return f"OP-{n % 10000:04d}"


def asset_tag(seq: int = None) -> str:
    n = _next_seq() if seq is None else seq
    return f"SP-{n % 10000:04d}"


def create_station_payload(**overrides) -> dict:
    defaults = {
        "station_code": station_code(),
        "service_zone": "Z1",
        "design_capacity_gpm": 300,
        "pump_count": 2,
        "has_backup_generator": False,
        "wet_well_volume_gal": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_pump_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "position_index": 1,
        "rated_gpm": 100,
    }
    defaults.update(overrides)
    return defaults


def create_runtime_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-08-01T00:00:00Z",
        "run_hours_delta": 1.0,
        "starts_count": 1,
        "source": "SCADA",
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "employee_code": employee_code(),
        "full_name": "Test Operator",
        "certifications": ["CSE_1", "COLLECTIONS_2"],
        "home_zone": "Z1",
    }
    defaults.update(overrides)
    return defaults


def create_alarm_ticket_payload(**overrides) -> dict:
    defaults = {
        "alarm_class": "MINOR",
        "alarm_code": "HI_LEVEL",
        "raised_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_pump_rebuild_payload(pump_id: str, **overrides) -> dict:
    defaults = {
        "pump_id": pump_id,
        "work_order_ref": "WO-1000",
        "started_at": "2026-08-01T00:00:00Z",
        "cost_usd": 10000.00,
    }
    defaults.update(overrides)
    return defaults


def create_cleaning_payload(crew_lead_operator_id: str, **overrides) -> dict:
    defaults = {
        "scheduled_for": "2026-08-01T00:00:00Z",
        "grease_depth_inches_pre": 4.0,
        "crew_lead_operator_id": crew_lead_operator_id,
        "requires_confined_space_entry": False,
    }
    defaults.update(overrides)
    return defaults


def create_generator_test_payload(**overrides) -> dict:
    defaults = {
        "scheduled_for": "2026-08-01T00:00:00Z",
        "test_kind": "NO_LOAD",
        "load_percent": 0,
    }
    defaults.update(overrides)
    return defaults


def create_sso_event_payload(expected_station_version: int, **overrides) -> dict:
    defaults = {
        "started_at": "2026-08-01T00:00:00Z",
        "cause_code": "GREASE_BLOCKAGE",
        "reached_surface_water": False,
        "expected_station_version": expected_station_version,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(entrant_id: str, attendant_id: str, supervisor_id: str, **overrides) -> dict:
    defaults = {
        "work_description": "wet well inspection",
        "authorized_entrant_id": entrant_id,
        "attendant_operator_id": attendant_id,
        "entry_supervisor_id": supervisor_id,
        "gas_test_passed": True,
    }
    defaults.update(overrides)
    return defaults


def create_capital_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_year": 2090,
        "budget_total_usd": 100000.00,
    }
    defaults.update(overrides)
    return defaults


def create_capital_project_payload(plan_id: str, station_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "station_id": station_id,
        "project_name": "Replacement project",
        "estimated_cost_usd": 10000.00,
        "consequence_of_failure": 5,
        "likelihood_of_failure": 5,
    }
    defaults.update(overrides)
    return defaults


def create_spare_pump_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": asset_tag(),
        "rated_gpm": 200,
        "compatible_zone": "Z1",
    }
    defaults.update(overrides)
    return defaults
