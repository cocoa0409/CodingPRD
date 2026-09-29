"""Request-body builders.

Each factory returns only the client-supplied fields for one create or action
payload and accepts ``**overrides`` so a test can vary a single figure without
restating the whole body.  Server-computed fields are never produced here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

#: The narrow-body airframe used throughout: 162 seats, index constant 1000,
#: reference arm at the leading edge of the mean aerodynamic chord.
BASE_AIRCRAFT: Dict[str, Any] = {
    "registration": "HB-AAA",
    "type_code": "B738",
    "basic_empty_weight_kg": 41400,
    "basic_index": 66.56,
    "max_takeoff_weight_kg": 79000,
    "max_landing_weight_kg": 66360,
    "max_zero_fuel_weight_kg": 62730,
    "max_taxi_weight_kg": 79200,
    "ref_arm_m": 17.0,
    "lemac_m": 17.0,
    "mac_length_m": 4.2,
    "index_c": 1000,
    "index_k": 50,
    "fuel_arm_m": 17.9,
    "seat_count": 162,
    "zfw_fwd_limit_pct_mac": 6.0,
    "zfw_aft_limit_pct_mac": 30.0,
    "tow_fwd_limit_pct_mac": 5.0,
    "tow_aft_limit_pct_mac": 28.0,
    "tow_knee_weight_kg": 60000,
    "tow_aft_knee_adjust_pct_mac": -1.5,
}


def aircraft_payload(registration: str = "HB-AAA", **overrides: Any) -> Dict[str, Any]:
    payload = dict(BASE_AIRCRAFT)
    payload["registration"] = registration
    payload.update(overrides)
    return payload


def compartment_payload(
    aircraft_id: str,
    code: str,
    kind: str,
    arm_m: float,
    max_weight_kg: float,
    running_load_limit_kg_per_m: float,
    length_m: float,
    seat_capacity: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "aircraft_id": aircraft_id,
        "code": code,
        "kind": kind,
        "arm_m": arm_m,
        "max_weight_kg": max_weight_kg,
        "running_load_limit_kg_per_m": running_load_limit_kg_per_m,
        "length_m": length_m,
        "seat_capacity": seat_capacity,
    }
    payload.update(overrides)
    return payload


#: The canonical cabin/hold layout of the reference airframe.  Codes ``OA``,
#: ``OB`` and ``OC`` are seated zones running fore to aft; ``H1``, ``H4`` and
#: ``H5`` are holds.
CANONICAL_COMPARTMENTS = [
    {
        "code": "OA",
        "kind": "CABIN_ZONE",
        "arm_m": 12.5,
        "max_weight_kg": 5000,
        "running_load_limit_kg_per_m": 2000,
        "length_m": 6.0,
        "seat_capacity": 42,
    },
    {
        "code": "OB",
        "kind": "CABIN_ZONE",
        "arm_m": 17.8,
        "max_weight_kg": 8000,
        "running_load_limit_kg_per_m": 2000,
        "length_m": 8.0,
        "seat_capacity": 60,
    },
    {
        "code": "OC",
        "kind": "CABIN_ZONE",
        "arm_m": 22.9,
        "max_weight_kg": 8000,
        "running_load_limit_kg_per_m": 2000,
        "length_m": 8.0,
        "seat_capacity": 60,
    },
    {
        "code": "H1",
        "kind": "HOLD",
        "arm_m": 9.2,
        "max_weight_kg": 4500,
        "running_load_limit_kg_per_m": 900,
        "length_m": 5.0,
        "seat_capacity": 0,
    },
    {
        "code": "H4",
        "kind": "HOLD",
        "arm_m": 24.6,
        "max_weight_kg": 5000,
        "running_load_limit_kg_per_m": 900,
        "length_m": 6.0,
        "seat_capacity": 0,
    },
    {
        "code": "H5",
        "kind": "HOLD",
        "arm_m": 28.4,
        "max_weight_kg": 1200,
        "running_load_limit_kg_per_m": 500,
        "length_m": 2.4,
        "seat_capacity": 0,
    },
]

#: A short hold whose running-load ceiling bites long before its structural
#: ceiling does: 5000 kg over only 2.0 m at 900 kg/m.
SHORT_HOLD_COMPARTMENT = {
    "code": "H6",
    "kind": "HOLD",
    "arm_m": 24.6,
    "max_weight_kg": 5000,
    "running_load_limit_kg_per_m": 900,
    "length_m": 2.0,
    "seat_capacity": 0,
}


def runway_payload(
    airport_code: str = "LSGG",
    designator: str = "04",
    elevation_ft: float = 1411,
    length_m: float = 3900,
    slot_capacity_per_window: Optional[int] = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "airport_code": airport_code,
        "designator": designator,
        "elevation_ft": elevation_ft,
        "length_m": length_m,
    }
    if slot_capacity_per_window is not None:
        payload["slot_capacity_per_window"] = slot_capacity_per_window
    payload.update(overrides)
    return payload


def performance_band_payload(
    runway_id: str,
    temp_lo_c: float,
    temp_hi_c: float,
    base_limit_weight_kg: float,
    aircraft_type_code: str = "B738",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "runway_id": runway_id,
        "aircraft_type_code": aircraft_type_code,
        "temp_lo_c": temp_lo_c,
        "temp_hi_c": temp_hi_c,
        "base_limit_weight_kg": base_limit_weight_kg,
    }
    payload.update(overrides)
    return payload


#: The three published temperature rows for the reference airframe on the
#: reference runway.  Bands are lower-inclusive and upper-exclusive.
CANONICAL_BANDS = [
    {"temp_lo_c": -10, "temp_hi_c": 15, "base_limit_weight_kg": 79000},
    {"temp_lo_c": 15, "temp_hi_c": 30, "base_limit_weight_kg": 74500},
    {"temp_lo_c": 30, "temp_hi_c": 45, "base_limit_weight_kg": 69800},
]


def weight_program_payload(
    code: str = "STD-2026",
    program_kind: str = "STANDARD",
    documentation_ref: str = "OM-A 8.1.3 rev 12",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "program_kind": program_kind,
        "male_kg": 88.0,
        "female_kg": 70.0,
        "child_kg": 35.0,
        "infant_kg": 10.0,
        "checked_bag_kg": 13.0,
        "documentation_ref": documentation_ref,
    }
    payload.update(overrides)
    return payload


def actual_weight_program_payload(code: str = "ACT-2026", **overrides: Any) -> Dict[str, Any]:
    return weight_program_payload(
        code=code,
        program_kind="ACTUAL",
        documentation_ref="OM-A 8.1.4 rev 3",
        **overrides,
    )


def superseded_weight_program_payload(code: str = "OLD-2019", **overrides: Any) -> Dict[str, Any]:
    """An older standard programme with lighter published passenger masses."""
    return weight_program_payload(
        code=code,
        program_kind="STANDARD",
        documentation_ref="OM-A 8.1.3 rev 4",
        male_kg=84.0,
        female_kg=66.0,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------


def flight_payload(
    aircraft_id: str,
    departure_runway_id: str,
    weight_program_id: str,
    flight_number: str = "LX1602",
    scheduled_off_block_utc: str = "2026-08-15T10:00:00Z",
    scheduled_on_block_utc: str = "2026-08-15T12:30:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flight_number": flight_number,
        "aircraft_id": aircraft_id,
        "departure_runway_id": departure_runway_id,
        "weight_program_id": weight_program_id,
        "scheduled_off_block_utc": scheduled_off_block_utc,
        "scheduled_on_block_utc": scheduled_on_block_utc,
        "crew_weight_kg": 1150,
        "crew_arm_m": 13.5,
        "ramp_fuel_kg": 9800,
        "taxi_fuel_kg": 250,
        "trip_fuel_kg": 6900,
        "outside_air_temp_c": 22,
        "headwind_component_kt": 6,
        "runway_condition": "DRY",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Load plans and their contents
# ---------------------------------------------------------------------------


def load_plan_payload(flight_id: str, expected_flight_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flight_id": flight_id,
        "expected_flight_version": expected_flight_version,
    }
    payload.update(overrides)
    return payload


def pax_line_payload(
    load_plan_id: str,
    compartment_id: str,
    male_count: int = 0,
    female_count: int = 0,
    child_count: int = 0,
    infant_count: int = 0,
    actual_weight_kg: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "load_plan_id": load_plan_id,
        "compartment_id": compartment_id,
        "male_count": male_count,
        "female_count": female_count,
        "child_count": child_count,
        "infant_count": infant_count,
    }
    if actual_weight_kg is not None:
        payload["actual_weight_kg"] = actual_weight_kg
    payload.update(overrides)
    return payload


def bag_allocation_payload(
    load_plan_id: str,
    compartment_id: str,
    bag_count: int,
    bag_weight_kg: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "load_plan_id": load_plan_id,
        "compartment_id": compartment_id,
        "bag_count": bag_count,
    }
    if bag_weight_kg is not None:
        payload["bag_weight_kg"] = bag_weight_kg
    payload.update(overrides)
    return payload


def cargo_item_payload(
    flight_id: str,
    awb_number: str,
    item_kind: str = "GENERAL",
    weight_kg: float = 900,
    length_m: float = 1.2,
    is_dangerous_goods: bool = False,
    assigned_compartment_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flight_id": flight_id,
        "awb_number": awb_number,
        "item_kind": item_kind,
        "weight_kg": weight_kg,
        "length_m": length_m,
        "is_dangerous_goods": is_dangerous_goods,
    }
    if assigned_compartment_id is not None:
        payload["assigned_compartment_id"] = assigned_compartment_id
    payload.update(overrides)
    return payload


def gate_bag_payload(
    awb_number: str,
    weight_kg: float,
    compartment_id: str,
    length_m: float = 0.6,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "awb_number": awb_number,
        "weight_kg": weight_kg,
        "length_m": length_m,
        "compartment_id": compartment_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dangerous goods
# ---------------------------------------------------------------------------


def hazmat_declaration_payload(
    cargo_item_id: str,
    quantity_kg: float,
    un_number: str = "UN1263",
    imo_class: str = "CLASS_3",
    packing_group: str = "II",
    segregation_group: str = "FLAMMABLE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cargo_item_id": cargo_item_id,
        "un_number": un_number,
        "imo_class": imo_class,
        "packing_group": packing_group,
        "segregation_group": segregation_group,
        "quantity_kg": quantity_kg,
    }
    payload.update(overrides)
    return payload


def flammable_declaration_payload(cargo_item_id: str, quantity_kg: float, **overrides: Any):
    """Paint, UN1263, packing group II, segregation group FLAMMABLE."""
    return hazmat_declaration_payload(
        cargo_item_id,
        quantity_kg,
        un_number="UN1263",
        imo_class="CLASS_3",
        packing_group="II",
        segregation_group="FLAMMABLE",
        **overrides,
    )


def oxidiser_declaration_payload(cargo_item_id: str, quantity_kg: float, **overrides: Any):
    """Calcium hypochlorite, UN1748, segregation group OXIDISER."""
    return hazmat_declaration_payload(
        cargo_item_id,
        quantity_kg,
        un_number="UN1748",
        imo_class="CLASS_5",
        packing_group="II",
        segregation_group="OXIDISER",
        **overrides,
    )


def corrosive_declaration_payload(cargo_item_id: str, quantity_kg: float, **overrides: Any):
    """Sodium hydroxide solution, UN1789, segregation group CORROSIVE."""
    return hazmat_declaration_payload(
        cargo_item_id,
        quantity_kg,
        un_number="UN1789",
        imo_class="CLASS_8",
        packing_group="II",
        segregation_group="CORROSIVE",
        **overrides,
    )


# ---------------------------------------------------------------------------
# Load sheets, last-minute changes, audits
# ---------------------------------------------------------------------------


def load_sheet_payload(
    load_plan_id: str, expected_load_plan_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "load_plan_id": load_plan_id,
        "expected_load_plan_version": expected_load_plan_version,
    }
    payload.update(overrides)
    return payload


def last_minute_change_payload(
    load_sheet_id: str,
    change_kind: str,
    compartment_id: str,
    male_count: int = 0,
    female_count: int = 0,
    mass_kg: float = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "load_sheet_id": load_sheet_id,
        "change_kind": change_kind,
        "compartment_id": compartment_id,
        "male_count": male_count,
        "female_count": female_count,
        "mass_kg": mass_kg,
    }
    payload.update(overrides)
    return payload


def load_audit_payload(
    flight_id: str,
    basis: str,
    actual_pax_weight_kg: float,
    actual_bag_weight_kg: float,
    actual_cargo_weight_kg: float,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flight_id": flight_id,
        "basis": basis,
        "actual_pax_weight_kg": actual_pax_weight_kg,
        "actual_bag_weight_kg": actual_bag_weight_kg,
        "actual_cargo_weight_kg": actual_cargo_weight_kg,
    }
    payload.update(overrides)
    return payload


def close_audit_payload(finding_note: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"finding_note": finding_note}
    payload.update(overrides)
    return payload
