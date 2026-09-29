"""Request-payload factories.

Each factory returns a valid request body for one create or action endpoint and
accepts keyword overrides so a test can perturb exactly the one field it cares
about.  Codes that carry a uniqueness constraint (PRD 3.1, 3.2, 3.3, 3.7) are
suffixed with a per-process counter unless the caller pins them.
"""

import itertools
from typing import Any, Dict, List, Optional

from . import constants as K

_seq = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for the codes that must be unique."""
    return f"{next(_seq):04d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ── Master data ──────────────────────────────────────────────────────────────
def foundry_payload(**overrides) -> Dict[str, Any]:
    base = dict(K.FOUNDRY_NORTH)
    base["foundry_code"] = f"FDY-{unique_suffix()}"
    return _merge(base, overrides)


def suspend_foundry_payload(**overrides) -> Dict[str, Any]:
    return _merge({"suspension_reason": "Failed annual furnace audit"}, overrides)


def pump_model_payload(**overrides) -> Dict[str, Any]:
    base = dict(K.MODEL_HSC_14)
    base["model_code"] = f"HSC-{unique_suffix()}"
    return _merge(base, overrides)


def supersede_model_payload(successor_model_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"superseded_by_model_id": successor_model_id}, overrides)


def pattern_asset_payload(
    pump_model_id: str, foundry_id: str, **overrides
) -> Dict[str, Any]:
    base = dict(K.PATTERN_HSC14_A)
    base["pattern_code"] = f"PAT-{unique_suffix()}"
    base["pump_model_id"] = pump_model_id
    base["foundry_id"] = foundry_id
    return _merge(base, overrides)


def material_seal_config_payload(pump_model_id: str, **overrides) -> Dict[str, Any]:
    base = dict(K.CONFIG_CI_P11)
    base["config_code"] = f"MSC-{unique_suffix()}"
    base["pump_model_id"] = pump_model_id
    return _merge(base, overrides)


def duty_application_payload(**overrides) -> Dict[str, Any]:
    base = dict(K.DUTY_APP_1001)
    base["application_code"] = f"APP-{unique_suffix()}"
    return _merge(base, overrides)


def repair_kit_payload(pump_model_id: str, **overrides) -> Dict[str, Any]:
    base = dict(K.KIT_HSC14_G2)
    base["kit_code"] = f"RK-{unique_suffix()}"
    base["pump_model_id"] = pump_model_id
    return _merge(base, overrides)


def kit_receipt_payload(qty: int = 5, **overrides) -> Dict[str, Any]:
    return _merge({"qty": qty}, overrides)


# ── Selection ────────────────────────────────────────────────────────────────
def selection_payload(
    duty_application_id: str,
    pump_model_id: str,
    material_seal_config_id: str,
    expected_duty_application_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "duty_application_id": duty_application_id,
            "pump_model_id": pump_model_id,
            "material_seal_config_id": material_seal_config_id,
            "expected_duty_application_version": expected_duty_application_version,
        },
        overrides,
    )


# ── Casting ──────────────────────────────────────────────────────────────────
def casting_lot_payload(
    pattern_asset_id: str, foundry_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "pattern_asset_id": pattern_asset_id,
        "foundry_id": foundry_id,
        "heat_number": f"H-{unique_suffix()}",
        "alloy_code": "CI_GG25",
        "qty_poured": 4,
        "pour_window_start": K.DEFAULT_POUR_WINDOW_START,
        "pour_window_end": K.DEFAULT_POUR_WINDOW_END,
    }
    return _merge(base, overrides)


def casting_defect_payload(**overrides) -> Dict[str, Any]:
    base = {
        "defect_code": f"DF-{unique_suffix()}",
        "defect_type": "POROSITY",
        "severity": "MINOR",
        "affected_qty": 1,
    }
    return _merge(base, overrides)


def disposition_payload(disposition: str, **overrides) -> Dict[str, Any]:
    return _merge({"disposition": disposition}, overrides)


# ── Build and test ───────────────────────────────────────────────────────────
def build_order_payload(
    selection_id: str, casting_lot_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "selection_id": selection_id,
        "casting_lot_id": casting_lot_id,
        "serial_number": f"SN-{unique_suffix()}",
    }
    return _merge(base, overrides)


def assembly_payload(**overrides) -> Dict[str, Any]:
    base = {
        "running_clearance_mm": 0.35,
        "residual_unbalance_g_mm": 900.00,
        "seal_flush_plan_installed": "API_PLAN_11",
    }
    return _merge(base, overrides)


def reassign_lot_payload(casting_lot_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"casting_lot_id": casting_lot_id}, overrides)


def auto_allocation_payload(requested_qty: int = 1, **overrides) -> Dict[str, Any]:
    return _merge({"requested_qty": requested_qty}, overrides)


def test_run_payload(build_order_id: str, **overrides) -> Dict[str, Any]:
    base = {
        "build_order_id": build_order_id,
        "test_speed_rpm": 2950,
        "correction_basis": "RATED_SPEED_CORRECTED",
        "test_grade": "GRADE_1B",
        "witness_required": True,
    }
    return _merge(base, overrides)


def test_point_payload(
    measured_flow_m3h: float,
    measured_head_m: float,
    measured_power_kw: float,
    measured_npsh3_m: Optional[float] = None,
    is_npsh_point: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "measured_flow_m3h": measured_flow_m3h,
        "measured_head_m": measured_head_m,
        "measured_power_kw": measured_power_kw,
    }
    if measured_npsh3_m is not None:
        base["measured_npsh3_m"] = measured_npsh3_m
    if is_npsh_point is not None:
        base["is_npsh_point"] = is_npsh_point
    return _merge(base, overrides)


def curve_points(
    points: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """A copy of a five-point measured set, safe to mutate."""
    source = points if points is not None else K.GOLDEN_CURVE_POINTS
    return [dict(p) for p in source]


# ── Package ──────────────────────────────────────────────────────────────────
def pump_package_payload(
    build_order_id: str, test_run_id: str, **overrides
) -> Dict[str, Any]:
    base = dict(K.PACKAGE_BP_14A)
    base["build_order_id"] = build_order_id
    base["test_run_id"] = test_run_id
    return _merge(base, overrides)


def ship_payload(
    actual_ship_date: str = K.DEFAULT_ACTUAL_SHIP_DATE, **overrides
) -> Dict[str, Any]:
    return _merge({"actual_ship_date": actual_ship_date}, overrides)


# ── Kit allocation ───────────────────────────────────────────────────────────
def kit_allocation_payload(
    repair_kit_id: str,
    build_order_id: str,
    requested_qty: int,
    expected_repair_kit_version: int,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "repair_kit_id": repair_kit_id,
            "build_order_id": build_order_id,
            "requested_qty": requested_qty,
            "expected_repair_kit_version": expected_repair_kit_version,
        },
        overrides,
    )


# ── Warranty ─────────────────────────────────────────────────────────────────
def claim_line(
    line_code: str, category: str, gross_amount: float
) -> Dict[str, Any]:
    """One commercial line of a warranty claim (PRD 3.9)."""
    return {
        "line_code": line_code,
        "category": category,
        "gross_amount": gross_amount,
    }


def warranty_claim_payload(
    pump_package_id: str,
    claim_lines: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "pump_package_id": pump_package_id,
        "as_found_flow_m3h": 300.0,
        "as_found_head_m": 67.0,
        "as_found_npsha_m": 5.10,
        "as_found_solids_pct": 0.0,
        "as_found_viscosity_cst": 1.2,
        "as_found_speed_rpm": 2950,
        "claim_lines": claim_lines
        if claim_lines is not None
        else [claim_line("L1", "PARTS", 1205.00)],
    }
    return _merge(base, overrides)


def request_info_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"info_request_note": "Send the field vibration trace and suction gauge log."},
        overrides,
    )


# ── Logical clock ────────────────────────────────────────────────────────────
def clock_payload(to_iso8601: str, **overrides) -> Dict[str, Any]:
    return _merge({"to_iso8601": to_iso8601}, overrides)
