"""Payload factories — one per entity, input fields only."""


def create_project_payload(**overrides) -> dict:
    defaults = {"site_name": "Test Site", "client_name": "Test Client"}
    defaults.update(overrides)
    return defaults


def create_segment_payload(**overrides) -> dict:
    """area_sqft and thickness_in are required; finish_grade/reinforcement default
    server-side (BROOM/NONE) when omitted."""
    defaults = {"label": "slab", "area_sqft": 400, "thickness_in": 4}
    defaults.update(overrides)
    return defaults


def create_estimate_payload(**overrides) -> dict:
    # No input fields — server computes everything.
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def approve_estimate_payload(estimate_id: str, expected_project_version: int, **overrides) -> dict:
    defaults = {"estimate_id": estimate_id, "expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {"jurisdiction": "City", "permit_number": "P-1"}
    defaults.update(overrides)
    return defaults


def create_material_order_payload(**overrides) -> dict:
    defaults = {
        "mix_type": "STANDARD",
        "pour_scheduled_start": "2026-07-01T12:00:00Z",
        "pour_duration_hours": 4,
    }
    defaults.update(overrides)
    return defaults


def start_pour_payload(**overrides) -> dict:
    # force_override optional
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def complete_pour_payload(completed_at: str, **overrides) -> dict:
    defaults = {"completed_at": completed_at}
    defaults.update(overrides)
    return defaults


def create_weather_reading_payload(reading_at: str, temp_f: float, precip_pct: float, **overrides) -> dict:
    defaults = {"reading_at": reading_at, "temp_f": temp_f, "precip_pct": precip_pct}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {"crew_name": "Crew 1", "skill": "FLATWORK", "headcount": 4}
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {"asset_name": "Pump-1", "asset_type": "PUMP_TRUCK"}
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(crew_id: str, window_start: str, window_end: str, **overrides) -> dict:
    defaults = {"crew_id": crew_id, "window_start": window_start, "window_end": window_end}
    defaults.update(overrides)
    return defaults


def create_change_order_payload(description: str, delta_amount: float, **overrides) -> dict:
    defaults = {"description": description, "delta_amount": delta_amount}
    defaults.update(overrides)
    return defaults


def resubmit_change_order_payload(delta_amount: float, **overrides) -> dict:
    defaults = {"delta_amount": delta_amount}
    defaults.update(overrides)
    return defaults


def approve_change_order_payload(expected_project_version: int, **overrides) -> dict:
    defaults = {"expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults


def create_draw_payload(draw_type: str, amount: float, **overrides) -> dict:
    defaults = {"draw_type": draw_type, "amount": amount}
    defaults.update(overrides)
    return defaults


def release_draw_payload(expected_project_version: int, **overrides) -> dict:
    defaults = {"expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults


def create_warranty_payload(term_months: int = 12, **overrides) -> dict:
    defaults = {"term_months": term_months}
    defaults.update(overrides)
    return defaults


def file_claim_payload(**overrides) -> dict:
    # defect_note optional
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
