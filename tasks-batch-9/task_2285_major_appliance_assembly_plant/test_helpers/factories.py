"""Payload factories: one per creating/mutating endpoint.

Each factory returns a fully valid payload built from sensible plant defaults;
``**overrides`` replaces or adds any key, and passing ``None`` for a key that
the PRD marks optional removes it from the payload entirely (so callers can
test the documented defaulting behaviour).
"""

from typing import Optional

_SENTINEL = object()


def _apply(payload: dict, overrides: dict) -> dict:
    """Merge overrides into payload, dropping keys explicitly set to None."""
    for key, value in overrides.items():
        if value is _SENTINEL:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


#: Pass ``field=OMIT`` to a factory to leave the field out of the payload.
OMIT = _SENTINEL


# =============================================================================
# Logical clock
# =============================================================================
def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


# =============================================================================
# Line
# =============================================================================
def line_payload(line_code: str = "L1", **overrides) -> dict:
    payload = {
        "line_code": line_code,
        "takt_seconds": 120,
        "option_load_limit_pct": 63.00,
        "baseline_headcount": 20,
        "current_family_code": "FAM_A",
    }
    return _apply(payload, overrides)


def stop_line_payload(reason: str = "SAFETY_DRILL", **overrides) -> dict:
    payload = {"reason": reason}
    return _apply(payload, overrides)


def start_line_payload(to_family_code: Optional[str] = None, **overrides) -> dict:
    payload: dict = {}
    if to_family_code is not None:
        payload["to_family_code"] = to_family_code
    return _apply(payload, overrides)


# =============================================================================
# Station
# =============================================================================
def station_payload(line_id: str, station_code: str = "ST10",
                    position_index: int = 10, **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "station_code": station_code,
        "position_index": position_index,
        "presentation_slot_capacity": 40,
        "station_cycle_seconds": 110,
    }
    return _apply(payload, overrides)


# =============================================================================
# Model variant
# =============================================================================
def model_variant_payload(model_code: str = "WM-X", family_code: str = "FAM_A",
                          **overrides) -> dict:
    payload = {
        "model_code": model_code,
        "family_code": family_code,
        "option_codes": ["OPT-STEAM", "OPT-WIFI"],
        "option_content_points": 4,
        "labor_minutes": 150,
        "functional_cycle_count_required": 3,
        "requires_leak_test": True,
        "hipot_leakage_ma_limit": 0.50,
        "leak_limit_ml_per_min": 2.00,
        "energy_kwh_limit": 400.00,
        "water_liters_limit": 200.00,
    }
    return _apply(payload, overrides)


# =============================================================================
# Supplier
# =============================================================================
def supplier_payload(supplier_code: str = "SUP1",
                     name: str = "Hinge and Module Co", **overrides) -> dict:
    payload = {
        "supplier_code": supplier_code,
        "name": name,
        "sync_window_minutes": 30,
    }
    return _apply(payload, overrides)


# =============================================================================
# Part
# =============================================================================
def part_payload(supplier_id: str, part_number: str = "P-DOOR-A",
                 **overrides) -> dict:
    payload = {
        "part_number": part_number,
        "supplier_id": supplier_id,
        "is_sequenced_module": False,
        "line_side_max_units": 24,
    }
    return _apply(payload, overrides)


# =============================================================================
# Bill-of-materials line
# =============================================================================
def bom_line_payload(model_variant_id: str, part_id: str, station_id: str,
                     expected_model_variant_version: int,
                     bom_position_code: str = "POS-DOOR", **overrides) -> dict:
    payload = {
        "model_variant_id": model_variant_id,
        "part_id": part_id,
        "station_id": station_id,
        "bom_position_code": bom_position_code,
        "qty_per_unit": 2,
        "effective_from_sequence": 1,
        "expected_model_variant_version": expected_model_variant_version,
    }
    return _apply(payload, overrides)


# =============================================================================
# Delivery call
# =============================================================================
def delivery_call_payload(supplier_id: str, part_id: str, station_id: str,
                          window_start: str = "2026-08-03T09:00:00Z",
                          window_end: str = "2026-08-03T10:00:00Z",
                          **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "part_id": part_id,
        "station_id": station_id,
        "window_start": window_start,
        "window_end": window_end,
        "sequenced_qty": 4,
    }
    return _apply(payload, overrides)


def record_arrival_payload(arrived_at: str, **overrides) -> dict:
    payload = {"arrived_at": arrived_at}
    return _apply(payload, overrides)


# =============================================================================
# Shift plan
# =============================================================================
def shift_plan_payload(line_id: str, expected_line_version: int,
                       shift_date: str = "2026-08-03", shift_code: str = "A",
                       shift_start: str = "2026-08-03T06:00:00Z",
                       shift_end: str = "2026-08-03T14:00:00Z",
                       planned_headcount: int = 20, **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "shift_date": shift_date,
        "shift_code": shift_code,
        "planned_headcount": planned_headcount,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "expected_line_version": expected_line_version,
    }
    return _apply(payload, overrides)


# =============================================================================
# Build slot
# =============================================================================
def build_slot_payload(line_id: str, model_variant_id: str,
                       sequence_index: int = 1,
                       planned_start: str = "2026-08-03T07:00:00Z",
                       **overrides) -> dict:
    payload = {
        "line_id": line_id,
        "model_variant_id": model_variant_id,
        "sequence_index": sequence_index,
        "planned_start": planned_start,
    }
    return _apply(payload, overrides)


# =============================================================================
# Quality test
# =============================================================================
def quality_test_payload(test_type: str, measured_value: float,
                         **overrides) -> dict:
    payload = {"test_type": test_type, "measured_value": measured_value}
    return _apply(payload, overrides)


def clear_quarantine_payload(note: Optional[str] = None, **overrides) -> dict:
    payload: dict = {}
    if note is not None:
        payload["note"] = note
    return _apply(payload, overrides)


# =============================================================================
# Engineering change
# =============================================================================
def engineering_change_payload(model_variant_id: str, affected_part_id: str,
                               target_line_id: str,
                               bom_position_code: str = "POS-DOOR",
                               cut_in_sequence_index: int = 5,
                               **overrides) -> dict:
    payload = {
        "model_variant_id": model_variant_id,
        "bom_position_code": bom_position_code,
        "affected_part_id": affected_part_id,
        "target_line_id": target_line_id,
        "cut_in_sequence_index": cut_in_sequence_index,
    }
    return _apply(payload, overrides)


def decide_payload(decision: str, note: Optional[str] = None, **overrides) -> dict:
    payload: dict = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return _apply(payload, overrides)


# =============================================================================
# Warranty return
# =============================================================================
def warranty_return_payload(production_unit_id: str,
                            failure_code: str = "F-DOOR-SEAL",
                            field_hours: float = 500, **overrides) -> dict:
    payload = {
        "production_unit_id": production_unit_id,
        "failure_code": failure_code,
        "field_hours": field_hours,
    }
    return _apply(payload, overrides)


def analyze_payload(disposition: str, root_cause_part_id: Optional[str] = None,
                    **overrides) -> dict:
    payload: dict = {"disposition": disposition}
    if root_cause_part_id is not None:
        payload["root_cause_part_id"] = root_cause_part_id
    return _apply(payload, overrides)


def close_return_payload(design_feedback_note: Optional[str] = None,
                         **overrides) -> dict:
    payload: dict = {}
    if design_feedback_note is not None:
        payload["design_feedback_note"] = design_feedback_note
    return _apply(payload, overrides)
