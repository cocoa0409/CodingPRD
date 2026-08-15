"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULT_WINDOW_START = "2026-07-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-12-31T23:59:59Z"


def create_pipe_segment_payload(**overrides) -> dict:
    defaults = {
        "segment_code": "SEG-1",
        "install_year": 2010,
        "material": "STEEL",
        "diameter_inches": 6.0,
        "length_feet": 1000.0,
        "operating_pressure_psi": 60.0,
        "pressure_class": "DISTRIBUTION",
        "is_high_consequence_area": False,
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = {
        "serial_number": "I-CGI-1",
        "instrument_type": "CGI",
    }
    defaults.update(overrides)
    return defaults


def create_calibration_payload(**overrides) -> dict:
    defaults = {
        "reference_gas_ppm": 100.0,
        "observed_ppm": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_field_technician_payload(**overrides) -> dict:
    defaults = {
        "employee_code": "FT-1",
        "full_name": "Tech One",
        "qualified_methods": ["WALKING"],
        "home_region": "NORTH",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_officer_payload(**overrides) -> dict:
    defaults = {
        "employee_code": "CO-1",
        "full_name": "Officer One",
        "jurisdiction_scope": ["PHMSA"],
    }
    defaults.update(overrides)
    return defaults


def create_simple_personnel_payload(**overrides) -> dict:
    """CalibrationTech / DispatchCoordinator / IntegrityAnalyst payloads."""
    defaults = {
        "employee_code": "EMP-1",
        "full_name": "Employee One",
    }
    defaults.update(overrides)
    return defaults


def create_repair_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_code": "CR-1",
        "home_region": "NORTH",
        "is_qualified_excavation": False,
        "max_concurrent_orders": 5,
    }
    defaults.update(overrides)
    return defaults


def create_survey_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": "R-1",
        "survey_method": "WALKING",
        "scheduled_window_start": DEFAULT_WINDOW_START,
        "scheduled_window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(segment_id: str, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "sequence_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_survey_run_payload(route_id: str, instrument_id: str, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "instrument_id": instrument_id,
        "distance_covered_feet": 1000.0,
    }
    defaults.update(overrides)
    return defaults


def create_leak_payload(segment_id: str, survey_run_id: str, **overrides) -> dict:
    """Defaults grade G2 on a non-HCA segment (concentration 12000 >= 10000)."""
    defaults = {
        "segment_id": segment_id,
        "survey_run_id": survey_run_id,
        "concentration_ppm": 12000.0,
        "distance_to_building_feet": 30.0,
        "bar_hole_reading_pct_lel": 8.0,
        "is_migration_evidence": False,
    }
    defaults.update(overrides)
    return defaults


def create_regrade_payload(**overrides) -> dict:
    defaults = {
        "new_grade": "G1",
        "reason": "regrade based on follow-up readings",
    }
    defaults.update(overrides)
    return defaults


def create_schedule_repair_payload(expected_leak_version: int, **overrides) -> dict:
    defaults = {
        "repair_method": "CLAMP",
        "expected_leak_version": expected_leak_version,
    }
    defaults.update(overrides)
    return defaults


def create_apply_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": "PERMIT-1",
        "jurisdiction": "CITY-NORTH",
        "expires_at": "2026-12-31T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_cp_reading_payload(segment_id: str, **overrides) -> dict:
    """Defaults are anomalous: instant_off -800 > -850 threshold."""
    defaults = {
        "segment_id": segment_id,
        "test_point_id": "TP-1",
        "pipe_to_soil_potential_mv": -700.0,
        "instant_off_potential_mv": -800.0,
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(**overrides) -> dict:
    defaults = {
        "snapshot_label": "SNAP-1",
        "snapshot_kind": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    defaults = {
        "reporting_period_start": "2026-01-01T00:00:00Z",
        "reporting_period_end": "2026-06-30T23:59:59Z",
        "regulator": "PHMSA",
    }
    defaults.update(overrides)
    return defaults
