"""Request payload builders for the LED Display Manufacturing API.

Every builder returns a plain dict with valid defaults that any test may
override field by field. Monetary amounts are always integer counts of cents and
are never emitted as strings; measurement precision follows the document's
rounding conventions.
"""

import itertools
from typing import Any, Dict, Optional

_serial_counter = itertools.count(1)


def next_serial(prefix: str = "M") -> str:
    """A factory serial number that is unique across the whole test session."""
    return f"{prefix}-{next(_serial_counter):05d}"


# ---------------------------------------------------------------------------
# Display models — three canonical product families
# ---------------------------------------------------------------------------

#: One module per cabinet, 1024 pixels per cabinet, 100.00 kg/sqm required load,
#: a 976.56 ppm dead-pixel ceiling and a 24 hour soak.
FP10_IN = {
    "name": "FP10-IN",
    "pixel_pitch_mm": 10.0,
    "rated_brightness_nits": 5000,
    "environmental_rating": "IP43_INDOOR",
    "module_width_mm": 320,
    "module_height_mm": 320,
    "module_pixel_cols": 32,
    "module_pixel_rows": 32,
    "cabinet_width_mm": 320,
    "cabinet_height_mm": 320,
    "modules_per_cabinet": 1,
    "cabinet_weight_kg": 10.24,
    "price_per_sqm_cents": 1000000,
    "dead_pixel_ppm_limit": 976.56,
    "module_dead_pixel_max": 3,
    "module_cluster_max": 1,
    "reference_color_x": 0.3128,
    "reference_color_y": 0.3290,
    "burn_in_hours_required": 24,
    "max_drive_pct": 90,
}

FP10_IN_DERIVED = {
    "module_area_sqm": 0.1024,
    "cabinet_area_sqm": 0.1024,
    "module_pixel_count": 1024,
    "cabinet_pixel_count": 1024,
    "recommended_min_viewing_distance_m": 10.0,
    "required_load_kg_per_sqm": 100.00,
}

#: Two modules per cabinet, 4096 pixels per cabinet, 150.00 kg/sqm required
#: load, a 500.00 ppm ceiling and a 24 hour soak.
FP16_STD = {
    "name": "FP16-STD",
    "pixel_pitch_mm": 5.0,
    "rated_brightness_nits": 5000,
    "environmental_rating": "IP65_FULL",
    "module_width_mm": 320,
    "module_height_mm": 160,
    "module_pixel_cols": 64,
    "module_pixel_rows": 32,
    "cabinet_width_mm": 320,
    "cabinet_height_mm": 320,
    "modules_per_cabinet": 2,
    "cabinet_weight_kg": 15.36,
    "price_per_sqm_cents": 1000000,
    "dead_pixel_ppm_limit": 500.00,
    "module_dead_pixel_max": 3,
    "module_cluster_max": 1,
    "reference_color_x": 0.3128,
    "reference_color_y": 0.3290,
    "burn_in_hours_required": 24,
    "max_drive_pct": 90,
}

FP16_STD_DERIVED = {
    "module_area_sqm": 0.0512,
    "cabinet_area_sqm": 0.1024,
    "module_pixel_count": 2048,
    "cabinet_pixel_count": 4096,
    "recommended_min_viewing_distance_m": 5.0,
    "required_load_kg_per_sqm": 150.00,
}

#: Four modules per cabinet, 32768 pixels per cabinet, 100.10 kg/sqm required
#: load, a 122.07 ppm ceiling and a 48 hour soak.
FP25_OUT = {
    "name": "FP25-OUT",
    "pixel_pitch_mm": 2.5,
    "rated_brightness_nits": 5000,
    "environmental_rating": "IP65_FRONT_IP54_REAR",
    "module_width_mm": 320,
    "module_height_mm": 160,
    "module_pixel_cols": 128,
    "module_pixel_rows": 64,
    "cabinet_width_mm": 640,
    "cabinet_height_mm": 320,
    "modules_per_cabinet": 4,
    "cabinet_weight_kg": 20.5,
    "price_per_sqm_cents": 1234567,
    "dead_pixel_ppm_limit": 122.07,
    "module_dead_pixel_max": 3,
    "module_cluster_max": 1,
    "reference_color_x": 0.3128,
    "reference_color_y": 0.3290,
    "burn_in_hours_required": 48,
    "max_drive_pct": 90,
}

FP25_OUT_DERIVED = {
    "module_area_sqm": 0.0512,
    "cabinet_area_sqm": 0.2048,
    "module_pixel_count": 8192,
    "cabinet_pixel_count": 32768,
    "recommended_min_viewing_distance_m": 2.5,
    "required_load_kg_per_sqm": 100.10,
}


def display_model_payload(base: Optional[Dict[str, Any]] = None, **overrides) -> Dict[str, Any]:
    """A product family registration payload, FP10-IN unless another base is given."""
    payload = dict(base if base is not None else FP10_IN)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Chambers and crews
# ---------------------------------------------------------------------------


def burn_in_chamber_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "CH-1",
        "slot_capacity": 4,
        "turnaround_minutes": 60,
        "certified_max_drive_pct": 90,
    }
    payload.update(overrides)
    return payload


def commissioning_crew_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Crew West",
        "region_code": "NAW",
        "certification_level": "L3",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def project_payload(display_model_id: str, **overrides) -> Dict[str, Any]:
    """A 1x1 RETAIL wall on FP10-IN with generous control-system headroom."""
    payload = {
        "customer_name": "Retail Seven",
        "install_environment": "RETAIL",
        "site_region_code": "NAW",
        "display_model_id": display_model_id,
        "cabinet_grid_cols": 1,
        "cabinet_grid_rows": 1,
        "min_viewing_distance_m": 10.0,
        "target_brightness_nits": 5000,
        "redundancy_mode": "NONE",
        "output_port_count": 1,
        "port_bandwidth_mbps": 1000,
        "color_depth_bits": 10,
        "refresh_rate_hz": 60,
        "player_count": 1,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Drawing revisions
# ---------------------------------------------------------------------------


def drawing_revision_payload(project_id: str, **overrides) -> Dict[str, Any]:
    """A revision that clears the FP10-IN load floor and the RETAIL wind floor."""
    payload = {
        "project_id": project_id,
        "structural_load_kg_per_sqm": 100.00,
        "wind_load_kph": 100,
        "mounting_type": "WALL",
        "service_access_side": "FRONT",
    }
    payload.update(overrides)
    return payload


def review_payload(decision: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------


def module_payload(display_model_id: str, serial_no: Optional[str] = None) -> Dict[str, Any]:
    return {
        "display_model_id": display_model_id,
        "serial_no": serial_no if serial_no is not None else next_serial(),
    }


def pixel_test_payload(dead_pixel_count: int = 1, max_cluster_size: int = 1) -> Dict[str, Any]:
    return {"dead_pixel_count": dead_pixel_count, "max_cluster_size": max_cluster_size}


def calibrate_payload(
    measured_brightness_nits: int = 4900,
    measured_color_x: float = 0.3130,
    measured_color_y: float = 0.3292,
) -> Dict[str, Any]:
    """Chroma error 0.0002 against the canonical reference, so the module bins A1."""
    return {
        "measured_brightness_nits": measured_brightness_nits,
        "measured_color_x": measured_color_x,
        "measured_color_y": measured_color_y,
    }


# ---------------------------------------------------------------------------
# Cabinets
# ---------------------------------------------------------------------------


def cabinet_payload(project_id: str, grid_row: int = 1, grid_col: int = 1) -> Dict[str, Any]:
    return {"project_id": project_id, "grid_row": grid_row, "grid_col": grid_col}


def install_module_payload(
    module_id: str, slot_index: int, expected_cabinet_version: int
) -> Dict[str, Any]:
    return {
        "module_id": module_id,
        "slot_index": slot_index,
        "expected_cabinet_version": expected_cabinet_version,
    }


def remove_module_payload(module_id: str, expected_cabinet_version: int) -> Dict[str, Any]:
    return {"module_id": module_id, "expected_cabinet_version": expected_cabinet_version}


# ---------------------------------------------------------------------------
# Burn-in runs
# ---------------------------------------------------------------------------


def burn_in_run_payload(
    cabinet_id: str,
    burn_in_chamber_id: str,
    window_start: str = "2026-08-02T00:00:00.000Z",
    window_end: str = "2026-08-03T00:00:00.000Z",
    slots_required: int = 1,
    drive_pct: int = 80,
    ambient_c: float = 45.0,
) -> Dict[str, Any]:
    return {
        "cabinet_id": cabinet_id,
        "burn_in_chamber_id": burn_in_chamber_id,
        "window_start": window_start,
        "window_end": window_end,
        "slots_required": slots_required,
        "drive_pct": drive_pct,
        "ambient_c": ambient_c,
    }


def complete_run_payload(
    new_dead_pixel_count: int = 0,
    measured_brightness_nits: int = 4900,
    measured_uniformity_pct: float = 95.00,
) -> Dict[str, Any]:
    return {
        "new_dead_pixel_count": new_dead_pixel_count,
        "measured_brightness_nits": measured_brightness_nits,
        "measured_uniformity_pct": measured_uniformity_pct,
    }


def abort_run_payload(reason: str = "Chamber humidity sensor out of calibration") -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Commissioning visits
# ---------------------------------------------------------------------------


def commissioning_visit_payload(
    project_id: str,
    commissioning_crew_id: str,
    window_start: str = "2026-08-05T08:00:00.000Z",
    window_end: str = "2026-08-05T16:00:00.000Z",
) -> Dict[str, Any]:
    return {
        "project_id": project_id,
        "commissioning_crew_id": commissioning_crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def visit_calibrate_payload(
    measured_brightness_nits: int = 4900, measured_uniformity_pct: float = 95.00
) -> Dict[str, Any]:
    return {
        "measured_brightness_nits": measured_brightness_nits,
        "measured_uniformity_pct": measured_uniformity_pct,
    }


# ---------------------------------------------------------------------------
# Service contracts
# ---------------------------------------------------------------------------


def service_contract_payload(
    project_id: str, tier: str = "GOLD", spare_pct_bp: int = 300, term_months: int = 60
) -> Dict[str, Any]:
    return {
        "project_id": project_id,
        "tier": tier,
        "spare_pct_bp": spare_pct_bp,
        "term_months": term_months,
    }


def spare_reservation_payload(
    expected_service_contract_version: int, module_id: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_service_contract_version": expected_service_contract_version
    }
    if module_id is not None:
        payload["module_id"] = module_id
    return payload


def spare_release_payload(
    module_id: str, expected_service_contract_version: int
) -> Dict[str, Any]:
    return {
        "module_id": module_id,
        "expected_service_contract_version": expected_service_contract_version,
    }


# ---------------------------------------------------------------------------
# Service cases
# ---------------------------------------------------------------------------


def module_fault_case_payload(
    service_contract_id: str,
    cabinet_id: str,
    faulty_module_id: str,
    severity: str = "MAJOR",
    symptom: str = "Quadrant one is dark",
) -> Dict[str, Any]:
    """A module-fault claim: it nominates the failed module and omits the measurement."""
    return {
        "service_contract_id": service_contract_id,
        "cabinet_id": cabinet_id,
        "case_type": "MODULE_FAULT",
        "severity": severity,
        "symptom": symptom,
        "faulty_module_id": faulty_module_id,
    }


def degradation_case_payload(
    service_contract_id: str,
    cabinet_id: str,
    measured_brightness_nits: int = 4600,
    severity: str = "MAJOR",
    symptom: str = "Measured 4600 nits against a 5000 nit rating",
) -> Dict[str, Any]:
    """A brightness-degradation claim: it carries the measurement and omits the module."""
    return {
        "service_contract_id": service_contract_id,
        "cabinet_id": cabinet_id,
        "case_type": "BRIGHTNESS_DEGRADATION",
        "severity": severity,
        "symptom": symptom,
        "measured_brightness_nits": measured_brightness_nits,
    }


def assess_payload(
    decision: str,
    assessment_basis: Optional[str] = None,
    denial_reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if assessment_basis is not None:
        payload["assessment_basis"] = assessment_basis
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def fulfil_payload(
    expected_cabinet_version: int, replacement_module_id: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_cabinet_version": expected_cabinet_version}
    if replacement_module_id is not None:
        payload["replacement_module_id"] = replacement_module_id
    return payload
