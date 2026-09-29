"""Payload factories.

Each builder returns a payload that satisfies every schema rule of the
requirements document by default, and accepts keyword overrides so a test can
push exactly one field off its happy value.
"""

from typing import Any, Dict, Optional

from . import constants as C


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of `None` removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --- Plant -----------------------------------------------------------------
def plant_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": C.PLANT_NAME,
            "site_code": C.PLANT_SITE_CODE,
            "licensed_chemistries": [C.CHEMISTRY_LEAD_ACID, C.CHEMISTRY_LITHIUM_LFP],
            "permit_status": "ACTIVE",
            "monthly_lead_emission_permit_g": C.PLANT_PERMIT_G,
            "peak_tariff_cents_per_kwh": C.PLANT_PEAK_TARIFF,
            "offpeak_tariff_cents_per_kwh": C.PLANT_OFFPEAK_TARIFF,
            "lead_initial_inventory_kg": C.PLANT_LEAD_INVENTORY_KG,
        },
        overrides,
    )


# --- Worker ----------------------------------------------------------------
def worker_payload(plant_id: str, full_name: str, job_class: str, **overrides: Any):
    return _merge(
        {
            "plant_id": plant_id,
            "full_name": full_name,
            "job_class": job_class,
            "hire_date": C.WORKER_HIRE_DATE,
        },
        overrides,
    )


def air_sample_payload(
    sampled_at: str, concentration: float, minutes: int, **overrides: Any
):
    return _merge(
        {
            "sample_type": C.SAMPLE_TYPE_AIR,
            "sampled_at": sampled_at,
            "air_lead_ug_per_m3": concentration,
            "sample_duration_minutes": minutes,
        },
        overrides,
    )


def blood_sample_payload(sampled_at: str, level: float, **overrides: Any):
    return _merge(
        {
            "sample_type": C.SAMPLE_TYPE_BLOOD,
            "sampled_at": sampled_at,
            "blood_lead_ug_per_dl": level,
        },
        overrides,
    )


def clearance_payload(note: str = "fit for duty", **overrides: Any):
    return _merge({"clearance_note": note}, overrides)


# --- Cell design -----------------------------------------------------------
def lead_design_payload(code: str = C.LEAD_DESIGN_CODE, **overrides: Any):
    """A tubular lead-acid design: 12 cells at 2.0 V, 465.0 Ah, 300.000 kg lead."""
    return _merge(
        {
            "code": code,
            "chemistry": C.CHEMISTRY_LEAD_ACID,
            "plate_type": C.PLATE_TUBULAR,
            "cells_per_battery": C.LEAD_DESIGN_CELLS,
            "cell_nominal_voltage_v": C.LEAD_DESIGN_CELL_VOLTAGE,
            "nominal_capacity_ah": C.LEAD_DESIGN_CAPACITY_AH,
            "rated_cycles": C.LEAD_DESIGN_RATED_CYCLES,
            "warranty_months": C.LEAD_DESIGN_WARRANTY_MONTHS,
            "pack_weight_kg": C.LEAD_DESIGN_WEIGHT_KG,
            "lead_content_kg": C.LEAD_DESIGN_LEAD_KG,
            "formation_charge_factor": C.LEAD_DESIGN_CHARGE_FACTOR,
            "list_price_cents": C.LEAD_DESIGN_LIST_PRICE_CENTS,
        },
        overrides,
    )


def lithium_design_payload(code: str = "CD-LFP-900", **overrides: Any):
    """A prismatic lithium design; lithium designs carry no lead at all."""
    return _merge(
        {
            "code": code,
            "chemistry": C.CHEMISTRY_LITHIUM_LFP,
            "plate_type": C.PLATE_PRISMATIC_CELL,
            "cells_per_battery": 8,
            "cell_nominal_voltage_v": 3.0,
            "nominal_capacity_ah": 900.0,
            "rated_cycles": 3000,
            "warranty_months": 60,
            "pack_weight_kg": 700.000,
            "lead_content_kg": 0.000,
            "formation_charge_factor": 1.15,
            "list_price_cents": 900000,
        },
        overrides,
    )


def review_action_payload(action: str, **overrides: Any):
    return _merge({"action": action}, overrides)


# --- Resources -------------------------------------------------------------
def formation_bay_payload(plant_id: str, bay_code: str = C.BAY_CODE, **overrides: Any):
    return _merge(
        {
            "plant_id": plant_id,
            "bay_code": bay_code,
            "rated_power_kw": C.BAY_RATED_POWER_KW,
            "cooldown_minutes": C.BAY_COOLDOWN_MINUTES,
        },
        overrides,
    )


def test_chamber_payload(
    plant_id: str, chamber_code: str = C.CHAMBER_CODE, **overrides: Any
):
    return _merge(
        {
            "plant_id": plant_id,
            "chamber_code": chamber_code,
            "power_cap_kw": C.CHAMBER_POWER_CAP_KW,
        },
        overrides,
    )


# --- Lots ------------------------------------------------------------------
def production_lot_payload(
    plant_id: str, cell_design_id: str, lot_code: str, quantity: int = 9, **overrides
):
    return _merge(
        {
            "plant_id": plant_id,
            "cell_design_id": cell_design_id,
            "lot_code": lot_code,
            "quantity": quantity,
        },
        overrides,
    )


def advance_payload(to_state: str, **overrides: Any):
    return _merge({"to_state": to_state}, overrides)


def sampling_plan_payload(expected_lot_version: int, **overrides: Any):
    return _merge(
        {
            "expected_lot_version": expected_lot_version,
            "plan_reason": "initial acceptance plan",
        },
        overrides,
    )


def disposition_payload(action: str, note: str = "acceptance met", **overrides: Any):
    return _merge({"action": action, "disposition_note": note}, overrides)


def env_hold_payload(action: str, hold_reason: Optional[str] = None, **overrides: Any):
    base: Dict[str, Any] = {"action": action}
    if hold_reason is not None:
        base["hold_reason"] = hold_reason
    return _merge(base, overrides)


# --- Assemblies ------------------------------------------------------------
def assembly_payload(
    lot_id: str,
    serial_number: str,
    module_count: int = 6,
    **overrides: Any,
):
    return _merge(
        {
            "lot_id": lot_id,
            "serial_number": serial_number,
            "module_count": module_count,
            "case_type": "STEEL_TRAY",
            "torque_spec_nm": 20.00,
            "ir_min_megaohm": 1.00,
        },
        overrides,
    )


def torque_verification_payload(
    measured_torque_nm: float, connection_count: int, **overrides: Any
):
    return _merge(
        {
            "verification_type": C.VERIFICATION_TORQUE,
            "measured_torque_nm": measured_torque_nm,
            "connection_count": connection_count,
        },
        overrides,
    )


def insulation_verification_payload(
    measured_ir_megaohm: float, test_voltage_v: int = 500, **overrides: Any
):
    return _merge(
        {
            "verification_type": C.VERIFICATION_INSULATION,
            "measured_ir_megaohm": measured_ir_megaohm,
            "test_voltage_v": test_voltage_v,
        },
        overrides,
    )


def rework_payload(note: str = "reworked on the line", **overrides: Any):
    return _merge({"rework_note": note}, overrides)


# --- Formation runs --------------------------------------------------------
def formation_run_payload(
    lot_id: str,
    bay_id: str,
    scheduled_start_at: str = "2026-09-02T06:00:00Z",
    scheduled_end_at: str = "2026-09-02T12:00:00Z",
    **overrides: Any,
):
    return _merge(
        {
            "lot_id": lot_id,
            "bay_id": bay_id,
            "scheduled_start_at": scheduled_start_at,
            "scheduled_end_at": scheduled_end_at,
        },
        overrides,
    )


def complete_run_payload(
    metered_energy_kwh: float,
    formation_capacity_pct: float,
    actual_end_at: Optional[str] = None,
    **overrides: Any,
):
    base: Dict[str, Any] = {
        "metered_energy_kwh": metered_energy_kwh,
        "formation_capacity_pct": formation_capacity_pct,
    }
    if actual_end_at is not None:
        base["actual_end_at"] = actual_end_at
    return _merge(base, overrides)


def abort_payload(abort_reason: str = C.ABORT_OPERATOR, **overrides: Any):
    return _merge({"abort_reason": abort_reason}, overrides)


# --- Capacity tests --------------------------------------------------------
def capacity_test_payload(
    assembly_id: str,
    chamber_id: str,
    scheduled_start_at: str = "2026-09-03T08:00:00Z",
    scheduled_end_at: str = "2026-09-03T10:00:00Z",
    test_type: str = C.TEST_TYPE_CAPACITY,
    draw_kw: float = 3.00,
    **overrides: Any,
):
    return _merge(
        {
            "assembly_id": assembly_id,
            "chamber_id": chamber_id,
            "test_type": test_type,
            "scheduled_start_at": scheduled_start_at,
            "scheduled_end_at": scheduled_end_at,
            "draw_kw": draw_kw,
        },
        overrides,
    )


def capacity_result_payload(measured_capacity_ah: float, **overrides: Any):
    return _merge({"measured_capacity_ah": measured_capacity_ah}, overrides)


def cycle_life_result_payload(
    measured_capacity_ah: float, cycles_completed: int, **overrides: Any
):
    return _merge(
        {
            "measured_capacity_ah": measured_capacity_ah,
            "cycles_completed": cycles_completed,
        },
        overrides,
    )


# --- Chargers and sizing ---------------------------------------------------
def charger_payload(
    model_code: str,
    chemistry_compatibility: str = C.CHEMISTRY_LEAD_ACID,
    output_voltage_v: float = 24.0,
    output_amps: float = 100.0,
    price_cents: int = 300000,
    charge_profile: str = "FERRO",
    **overrides: Any,
):
    return _merge(
        {
            "model_code": model_code,
            "chemistry_compatibility": chemistry_compatibility,
            "output_voltage_v": output_voltage_v,
            "output_amps": output_amps,
            "charge_profile": charge_profile,
            "price_cents": price_cents,
        },
        overrides,
    )


def sizing_request_payload(
    plant_id: str,
    application_name: str = "Harbor Forklift Co fleet",
    forklift_count: int = 6,
    shifts_per_day: int = 2,
    shift_energy_kwh_per_shift: float = 6.00,
    required_voltage_v: float = 24.0,
    ambient_temp_c: float = 5.0,
    compartment_max_kg: float = 1000.0,
    charge_window_hours: float = 8.00,
    chemistry_preference: str = C.CHEMISTRY_PREFERENCE_ANY,
    forklift_class: str = "CLASS_I",
    **overrides: Any,
):
    return _merge(
        {
            "plant_id": plant_id,
            "application_name": application_name,
            "forklift_class": forklift_class,
            "forklift_count": forklift_count,
            "shift_energy_kwh_per_shift": shift_energy_kwh_per_shift,
            "shifts_per_day": shifts_per_day,
            "ambient_temp_c": ambient_temp_c,
            "required_voltage_v": required_voltage_v,
            "compartment_max_kg": compartment_max_kg,
            "charge_window_hours": charge_window_hours,
            "chemistry_preference": chemistry_preference,
        },
        overrides,
    )


def sizing_decision_payload(action: str, **overrides: Any):
    return _merge({"action": action}, overrides)


# --- Units, service, warranty, core ---------------------------------------
def battery_unit_payload(
    lot_id: str,
    serial_number: str,
    customer_name: str = "Harbor Forklift Co",
    **overrides: Any,
):
    return _merge(
        {
            "lot_id": lot_id,
            "serial_number": serial_number,
            "customer_name": customer_name,
            "list_price_cents": C.LEAD_DESIGN_LIST_PRICE_CENTS,
        },
        overrides,
    )


def watering_log_payload(
    performed_at: str, electrolyte_level_ok: bool = True, **overrides: Any
):
    return _merge(
        {
            "event_type": C.MAINT_WATERING,
            "performed_at": performed_at,
            "electrolyte_level_ok": electrolyte_level_ok,
        },
        overrides,
    )


def cycle_report_payload(performed_at: str, cycles_delta: int, **overrides: Any):
    return _merge(
        {
            "event_type": C.MAINT_CYCLE_REPORT,
            "performed_at": performed_at,
            "cycles_delta": cycles_delta,
        },
        overrides,
    )


def inspection_log_payload(
    performed_at: str, event_type: str = C.MAINT_INSPECTION, **overrides: Any
):
    return _merge({"event_type": event_type, "performed_at": performed_at}, overrides)


def warranty_claim_payload(
    expected_battery_unit_version: int,
    complaint_code: str = "CAPACITY_LOSS",
    **overrides: Any,
):
    return _merge(
        {
            "expected_battery_unit_version": expected_battery_unit_version,
            "complaint_code": complaint_code,
        },
        overrides,
    )


def adjudication_payload(inspection_finding: str, **overrides: Any):
    return _merge(
        {
            "inspection_finding": inspection_finding,
            "adjudication_note": "adjudicated",
        },
        overrides,
    )


def core_return_payload(core_manifest_number: str, **overrides: Any):
    return _merge({"core_manifest_number": core_manifest_number}, overrides)


def core_transition_payload(
    action: str, received_lead_kg: Optional[float] = None, **overrides: Any
):
    base: Dict[str, Any] = {"action": action, "transition_note": "core transition"}
    if received_lead_kg is not None:
        base["received_lead_kg"] = received_lead_kg
    return _merge(base, overrides)
