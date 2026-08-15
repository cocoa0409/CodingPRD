"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

# Standard part definition used across tests: PN-100 rev A, area 2.0 m2,
# plies 200 + 300 g/m2, fiber volume 0.5 -> theoretical weight 2000.0 g.
STANDARD_PART_NUMBER = "PN-100"
STANDARD_REVISION = "A"
STANDARD_PLIES = [
    {"seq": 1, "material_code": "CF-200", "orientation_deg": 0, "areal_weight_g_m2": 200},
    {"seq": 2, "material_code": "CF-300", "orientation_deg": 90, "areal_weight_g_m2": 300},
]
STANDARD_AREA_M2 = 2.0
STANDARD_FIBER_VOLUME = 0.5

T0 = "2026-06-01T10:00:00Z"
PERMIT_PERIOD_START = "2026-06-01T00:00:00Z"
PERMIT_PERIOD_END = "2026-09-01T00:00:00Z"
STANDARD_DUE_DATE = "2026-07-01T00:00:00Z"

# Standard passing cure program and log: recorded values inside every
# dead-zone of the cure deviation score.
STANDARD_PROGRAM = {
    "ramp_rate_c_per_min": 3.0,
    "soak_temp_c": 180,
    "soak_minutes": 120,
}
STANDARD_PASS_LOG = {
    "recorded_min_temp_c": 178,
    "recorded_max_temp_c": 181,
    "recorded_soak_minutes": 120,
    "recorded_ramp_rate_c_per_min": 3.0,
}
STANDARD_WINDOW = {
    "scheduled_start": "2026-06-01T12:00:00Z",
    "scheduled_end": "2026-06-01T14:00:00Z",
}


def create_emission_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_code": "PER-Q3",
        "period_start": PERMIT_PERIOD_START,
        "period_end": PERMIT_PERIOD_END,
        "styrene_quota_kg": 50.0,
    }
    defaults.update(overrides)
    return defaults


def create_mold_payload(**overrides) -> dict:
    defaults = {
        "mold_code": "MOLD-1",
        "maintenance_interval_cycles": 10,
        "prototype_parts_required": 1,
    }
    defaults.update(overrides)
    return defaults


def create_ply_book_payload(**overrides) -> dict:
    defaults = {
        "part_number": STANDARD_PART_NUMBER,
        "revision": STANDARD_REVISION,
        "part_area_m2": STANDARD_AREA_M2,
        "plies": [dict(p) for p in STANDARD_PLIES],
        "resin_system": "POLYESTER",
        "target_fiber_volume_pct": STANDARD_FIBER_VOLUME,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(mold_id: str, ply_book_id: str, **overrides) -> dict:
    defaults = {
        "work_order_no": "WO-1",
        "part_number": STANDARD_PART_NUMBER,
        "mold_id": mold_id,
        "ply_book_id": ply_book_id,
        "quantity": 1,
        "due_date": STANDARD_DUE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_resin_batch_payload(**overrides) -> dict:
    defaults = {
        "batch_code": "BATCH-1",
        "resin_system": "POLYESTER",
        "resin_mass_g": 1000,
        "catalyst_mass_g": 20,
        "target_ratio_pct": 2.0,
        "ratio_tolerance_pct": 1.0,
        "nominal_pot_life_minutes": 600,
    }
    defaults.update(overrides)
    return defaults


def create_layup_session_payload(work_order_id: str, resin_batch_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "resin_batch_id": resin_batch_id,
        "resin_used_g": 200,
    }
    defaults.update(overrides)
    return defaults


def create_cure_equipment_payload(**overrides) -> dict:
    defaults = {
        "equipment_code": "OVEN-1",
        "kind": "OVEN",
        "max_parts_per_cycle": 10,
        "turnaround_minutes": 0,
        "max_temperature_c": 200,
        "max_pressure_bar": 0,
    }
    defaults.update(overrides)
    return defaults


def create_cure_cycle_payload(work_order_id: str, equipment_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "equipment_id": equipment_id,
    }
    defaults.update(STANDARD_PROGRAM)
    defaults.update(STANDARD_WINDOW)
    defaults.update(overrides)
    return defaults


def create_cure_log_payload(**overrides) -> dict:
    defaults = dict(STANDARD_PASS_LOG)
    defaults.update(overrides)
    return defaults


def create_inspection_payload(work_order_id: str, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "method": "ULTRASONIC",
        "void_content_pct": 1.0,
        "delamination_area_cm2": 0.0,
    }
    defaults.update(overrides)
    return defaults
