"""
Payload builders for every write endpoint.

Each builder returns a valid minimal payload and accepts keyword overrides so a
test can vary exactly the one field it is about. Human-readable codes are made
unique per call because the PRD reports a code collision as ERR_DUPLICATE_CODE;
a test that wants a collision passes the colliding code explicitly.

Numeric fields are emitted as real numbers, never as strings.
"""

import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def unique_code(prefix: str) -> str:
    """A short, unique, human-readable code."""
    return f"{prefix}-{next(_counter):05d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override whose value is None removes the field."""
    out = dict(base)
    for key, value in overrides.items():
        if value is None and key in out:
            del out[key]
        else:
            out[key] = value
    return out


# --- Plant and its assets -------------------------------------------------

def plant_payload(**overrides) -> Dict[str, Any]:
    """A plant at grid origin with a wide market radius and all equipment."""
    return _merge(
        {
            "plant_code": unique_code("PL"),
            "name": "Riverbend Brick Works",
            "grid_x": 0,
            "grid_y": 0,
            "market_radius_miles": 300,
            "freight_rate_cents_per_ton_mile": 42,
            "base_capacity_green_units_per_day": 40000,
            "unloading_equipment_available": [
                "CUSTOMER_FORKLIFT",
                "TRUCK_MOUNTED_FORKLIFT",
                "CRANE",
            ],
        },
        overrides,
    )


def clay_pit_payload(**overrides) -> Dict[str, Any]:
    """A clay pit with a large proven reserve."""
    return _merge(
        {
            "pit_name": unique_code("PIT"),
            "material_type": "CLAY",
            "proven_reserve_tons": 5000.00,
            "iron_oxide_pct": 7.500,
            "lime_pct": 1.200,
        },
        overrides,
    )


def shale_pit_payload(**overrides) -> Dict[str, Any]:
    """A shale pit; shale share drives part of the absorption index."""
    return _merge(
        {
            "pit_name": unique_code("PIT"),
            "material_type": "SHALE",
            "proven_reserve_tons": 5000.00,
            "iron_oxide_pct": 5.000,
            "lime_pct": 0.800,
        },
        overrides,
    )


def kiln_payload(**overrides) -> Dict[str, Any]:
    """A five-position tunnel kiln with a six-hour cooldown buffer."""
    return _merge(
        {
            "kiln_code": unique_code("K"),
            "position_count": 5,
            "setpoint_peak_c": 1050,
            "cooldown_buffer_hours": 6.0,
        },
        overrides,
    )


def kiln_car_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"car_code": unique_code("CAR"), "capacity_green_units": 12000},
        overrides,
    )


# --- Body formulation -----------------------------------------------------

def formulation_payload(plant_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "formulation_code": unique_code("F"),
            "target_color_family": "RED",
            "target_cdi": 20.00,
            "target_soak_hours": 3.0,
            "clay_tons_per_thousand_units": 3.20,
        },
        overrides,
    )


def formulation_component_payload(
    pit_id: str, share_pct: float, expected_formulation_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "pit_id": pit_id,
            "share_pct": share_pct,
            "expected_formulation_version": expected_formulation_version,
        },
        overrides,
    )


# --- Production and firing -----------------------------------------------

def production_run_payload(
    plant_id: str, formulation_id: str, kiln_car_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "plant_id": plant_id,
            "formulation_id": formulation_id,
            "kiln_car_id": kiln_car_id,
            "run_code": unique_code("PR"),
            "texture": "WIRE_CUT",
            "green_units_set": 10000,
        },
        overrides,
    )


def close_green_payload(green_loss_units: int = 400, **overrides) -> Dict[str, Any]:
    return _merge({"green_loss_units": green_loss_units}, overrides)


def kiln_run_payload(kiln_id: str, formulation_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "kiln_id": kiln_id,
            "formulation_id": formulation_id,
            "run_code": unique_code("KR"),
            "start_at": "2026-08-05T00:00:00Z",
            "end_at": "2026-08-07T00:00:00Z",
            "planned_peak_temp_c": 1050,
            "planned_soak_hours": 3.0,
        },
        overrides,
    )


def kiln_load_payload(
    production_run_id: str, kiln_position: int, expected_kiln_run_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "production_run_id": production_run_id,
            "kiln_position": kiln_position,
            "expected_kiln_run_version": expected_kiln_run_version,
        },
        overrides,
    )


def grade_payload(
    actual_peak_temp_c: int = 1040, actual_soak_hours: float = 3.0, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "actual_peak_temp_c": actual_peak_temp_c,
            "actual_soak_hours": actual_soak_hours,
        },
        overrides,
    )


def quarantine_payload(reason: str = "Efflorescence observed on face", **overrides):
    return _merge({"quarantine_reason": reason}, overrides)


# --- Orders ---------------------------------------------------------------

def order_payload(**overrides) -> Dict[str, Any]:
    """
    A 9600-unit SW order for a jobsite 60 rectilinear miles from grid origin.
    """
    return _merge(
        {
            "order_code": unique_code("ORD"),
            "jobsite_grid_x": 30,
            "jobsite_grid_y": 30,
            "requested_units": 9600,
            "color_family": "RED",
            "texture": "WIRE_CUT",
            "durability_grade": "SW",
            "unloading_equipment_required": "TRUCK_MOUNTED_FORKLIFT",
            "banding_type": "STEEL",
        },
        overrides,
    )


def package_payload(pallet_count: int, band_count: int, **overrides) -> Dict[str, Any]:
    return _merge({"pallet_count": pallet_count, "band_count": band_count}, overrides)


def deliver_payload(
    unloading_equipment_provided: str = "TRUCK_MOUNTED_FORKLIFT", **overrides
) -> Dict[str, Any]:
    return _merge(
        {"unloading_equipment_provided": unloading_equipment_provided}, overrides
    )


def cancel_payload(reason: str = "Jobsite schedule slipped", **overrides):
    return _merge({"cancellation_reason": reason}, overrides)


# --- Blends ---------------------------------------------------------------

def blend_payload(
    requested_units: int,
    target_color_index_min: float = 45.00,
    target_color_index_max: float = 55.00,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "blend_code": unique_code("BL"),
            "target_color_index_min": target_color_index_min,
            "target_color_index_max": target_color_index_max,
            "requested_units": requested_units,
        },
        overrides,
    )


def blend_component_payload(
    fired_lot_id: str, units: int, expected_blend_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "fired_lot_id": fired_lot_id,
            "units": units,
            "expected_blend_version": expected_blend_version,
        },
        overrides,
    )


def compose_payload(auto_fill: bool = False, **overrides) -> Dict[str, Any]:
    return _merge({"auto_fill": auto_fill}, overrides)


def reject_payload(reason: str = "Colour spread too wide for the elevation", **overrides):
    return _merge({"rejection_reason": reason}, overrides)


# --- Sample panels --------------------------------------------------------

def sample_panel_payload(
    formulation_id: str,
    dye_lot_id: str,
    panel_color_index: float,
    tolerance_delta_e: float = 1.00,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "panel_code": unique_code("PAN"),
            "formulation_id": formulation_id,
            "dye_lot_id": dye_lot_id,
            "panel_color_index": panel_color_index,
            "tolerance_delta_e": tolerance_delta_e,
        },
        overrides,
    )


def revision_payload(note: str = "Lighten the range by one dye lot", **overrides):
    return _merge({"revision_note": note}, overrides)
