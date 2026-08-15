"""Payload factories — one per creatable resource, input fields only (PRD §4).

Optional inputs are included only when explicitly supplied, so the server's
own defaults and nullability rules stay under test.
"""

DEFAULT_CLOCK_TICKET_START = "2026-08-03T00:00:00Z"


def project_payload(**overrides) -> dict:
    payload = {
        "name": "Test Project",
        "contract_ref": "C-0001",
        "soil_class_default": "SOIL_B",
        "contingency_cents": 100_000_000,
        "single_co_cap_cents": 5_000_000,
    }
    payload.update(overrides)
    return payload


def utility_owner_payload(**overrides) -> dict:
    payload = {
        "name": "City Water",
        "owner_type": "WATER",
        "min_notice_hours": 48,
        "max_shutdown_hours": 8,
    }
    payload.update(overrides)
    return payload


def locate_ticket_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "ticket_number": "T-1",
        "legal_start_at": DEFAULT_CLOCK_TICKET_START,
    }
    payload.update(overrides)
    return payload


def pothole_payload(project_id, locate_ticket_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "locate_ticket_id": locate_ticket_id,
        "station_label": "STA 1+00",
        "expected_utility_type": "WATER",
        "method": "VACUUM",
        "design_depth_in": 60,
        "design_offset_in": 12,
    }
    payload.update(overrides)
    return payload


def pipe_segment_payload(project_id, utility_owner_id, **overrides) -> dict:
    """Deep segment by default (12-inch, 8.0 ft invert, CLASS_B -> 10 lifts)."""
    payload = {
        "project_id": project_id,
        "utility_owner_id": utility_owner_id,
        "segment_label": "WL-A-01",
        "pipe_material": "PVC_C900",
        "diameter_in": 12,
        "length_ft": 200.0,
        "bedding_class": "CLASS_B",
        "design_invert_depth_ft": 8.0,
        "design_slope_pct": 1.0,
        "requires_dewatering": False,
    }
    payload.update(overrides)
    return payload


def shallow_segment_payload(project_id, utility_owner_id, **overrides) -> dict:
    """Shallow 6-inch CLASS_D segment (1.0 ft invert -> 2 lifts)."""
    payload = pipe_segment_payload(
        project_id,
        utility_owner_id,
        segment_label="WL-S-01",
        pipe_material="HDPE",
        diameter_in=6,
        length_ft=100.0,
        bedding_class="CLASS_D",
        design_invert_depth_ft=1.0,
        design_slope_pct=0.5,
    )
    payload.update(overrides)
    return payload


def trench_plan_payload(project_id, pipe_segment_id, **overrides) -> dict:
    """Plan for the default deep segment (SOIL_C sloped at the 1.5 ratio).

    A ``None`` override omits the key entirely (e.g. ``slope_ratio=None`` for
    a TRENCH_BOX plan, where the ratio is not required).
    """
    payload = {
        "project_id": project_id,
        "pipe_segment_id": pipe_segment_id,
        "max_depth_ft": 9.5,
        "soil_class": "SOIL_C",
        "protective_system": "SLOPING",
        "slope_ratio": 1.5,
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None}


def shallow_trench_plan_payload(project_id, pipe_segment_id, **overrides) -> dict:
    """Plan for the shallow segment (SOIL_A sloped at the 0.75 ratio)."""
    payload = trench_plan_payload(
        project_id,
        pipe_segment_id,
        max_depth_ft=1.75,
        soil_class="SOIL_A",
        slope_ratio=0.75,
    )
    payload.update(overrides)
    return payload


def inspection_payload(pipe_segment_id, **overrides) -> dict:
    payload = {
        "pipe_segment_id": pipe_segment_id,
        "bedding_ok": True,
        "joint_ok": True,
        "slope_measured_pct": 1.0,
        "cover_depth_ft": 3.5,
    }
    payload.update(overrides)
    return payload


def shutdown_window_payload(
    project_id, utility_owner_id, pipe_segment_id, expected_project_version, **overrides
) -> dict:
    payload = {
        "project_id": project_id,
        "utility_owner_id": utility_owner_id,
        "pipe_segment_id": pipe_segment_id,
        "window_start": "2026-08-05T10:00:00Z",
        "window_end": "2026-08-05T12:00:00Z",
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def discharge_permit_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "permit_number": "DP-1",
        "max_flow_gpm": 500,
        "turbidity_limit_ntu": 50,
        "daily_volume_limit_gal": 100_000,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def discharge_reading_payload(discharge_permit_id, **overrides) -> dict:
    payload = {
        "discharge_permit_id": discharge_permit_id,
        "recorded_at": "2026-08-02T00:00:00Z",
        "flow_gpm": 100,
        "turbidity_ntu": 10,
        "duration_min": 10,
    }
    payload.update(overrides)
    return payload


def compaction_test_payload(pipe_segment_id, lift_number, **overrides) -> dict:
    payload = {
        "pipe_segment_id": pipe_segment_id,
        "lift_number": lift_number,
        "proctor_max_density_pcf": 100.0,
        "field_density_pcf": 90.0,
        "moisture_pct": 10.0,
    }
    payload.update(overrides)
    return payload


def as_built_payload(pipe_segment_id, **overrides) -> dict:
    payload = {
        "pipe_segment_id": pipe_segment_id,
        "surveyor_stamp": "SURV-1",
        "measured_length_ft": 100.5,
        "measured_invert_ft": 1.0,
    }
    payload.update(overrides)
    return payload


def unforeseen_condition_payload(project_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "condition_type": "ROCK",
        "stop_work_required": False,
        "description": "unexpected condition",
    }
    payload.update(overrides)
    return payload


def change_order_payload(
    project_id, unforeseen_condition_id, utility_owner_id, expected_project_version,
    **overrides,
) -> dict:
    """Default pricing: direct 250000, markup 37500, provisional 287500."""
    payload = {
        "project_id": project_id,
        "unforeseen_condition_id": unforeseen_condition_id,
        "utility_owner_id": utility_owner_id,
        "labor_hours": 10.0,
        "labor_rate_cents": 15_000,
        "equipment_hours": 4.0,
        "equipment_rate_cents": 20_000,
        "material_cost_cents": 20_000,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload
