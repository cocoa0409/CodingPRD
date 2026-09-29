"""Payload factories — one per write endpoint, input fields only.

Defaults reproduce the commercial and physical baseline every scenario in this
suite is written against: a 100 kW AC / 130 kW DC plant on a 10,000,000-cent
contract. Each factory takes ``**overrides`` so a test can vary exactly the one
figure it is about.
"""
from __future__ import annotations

from typing import Any, Dict

from .constants import BASE_PROJECT

Json = Dict[str, Any]


def _merge(defaults: Json, overrides: Json) -> Json:
    payload = dict(defaults)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_payload(now: str) -> Json:
    return {"now": now}


# ---------------------------------------------------------------------------
# PRD 3.1 — project, change orders, milestones, compliance runs
# ---------------------------------------------------------------------------
def project_payload(**overrides: Any) -> Json:
    defaults = {
        "name": "Basin Mesa I",
        "utility_name": "Basin Power",
        **BASE_PROJECT,
    }
    return _merge(defaults, overrides)


def change_order_payload(amount_cents: int, **overrides: Any) -> Json:
    defaults = {"amount_cents": amount_cents, "reason": "owner-directed scope addition"}
    return _merge(defaults, overrides)


def labor_compliance_run_payload(**overrides: Any) -> Json:
    return dict(overrides)


def milestone_claim_payload(milestone_kind: str, **overrides: Any) -> Json:
    return _merge({"milestone_kind": milestone_kind}, overrides)


def milestone_decision_payload(
    milestone_kind: str, decision: str, **overrides: Any
) -> Json:
    return _merge({"milestone_kind": milestone_kind, "decision": decision}, overrides)


# ---------------------------------------------------------------------------
# PRD 3.2 — grading areas, earthwork logs, site events, acceptance
# ---------------------------------------------------------------------------
def grading_area_payload(**overrides: Any) -> Json:
    defaults = {
        "area_code": "A1",
        "permit_number": "CGP-2026-118",
        "disturbed_acreage_limit": 40.00,
        "bmp_inspection_interval_days": 14,
    }
    return _merge(defaults, overrides)


def earthwork_log_payload(
    activity_type: str,
    work_start_at: str,
    work_end_at: str,
    acreage_disturbed_delta: float,
    **overrides: Any,
) -> Json:
    defaults = {
        "activity_type": activity_type,
        "work_start_at": work_start_at,
        "work_end_at": work_end_at,
        "acreage_disturbed_delta": acreage_disturbed_delta,
    }
    return _merge(defaults, overrides)


def rain_event_payload(occurred_at: str, rainfall_inches: float, **overrides: Any) -> Json:
    defaults = {
        "event_type": "RAIN_EVENT",
        "occurred_at": occurred_at,
        "rainfall_inches": rainfall_inches,
    }
    return _merge(defaults, overrides)


def bmp_inspection_payload(
    occurred_at: str, deficiencies_found: bool = False, **overrides: Any
) -> Json:
    defaults = {
        "event_type": "BMP_INSPECTION",
        "occurred_at": occurred_at,
        "deficiencies_found": deficiencies_found,
    }
    return _merge(defaults, overrides)


def permit_suspension_payload(occurred_at: str, **overrides: Any) -> Json:
    defaults = {"event_type": "PERMIT_SUSPENSION", "occurred_at": occurred_at}
    return _merge(defaults, overrides)


def permit_reinstatement_payload(occurred_at: str, **overrides: Any) -> Json:
    defaults = {"event_type": "PERMIT_REINSTATEMENT", "occurred_at": occurred_at}
    return _merge(defaults, overrides)


def acceptance_payload(
    compaction_test_pct: float = 96.5,
    drainage_inspection_passed: bool = True,
    **overrides: Any,
) -> Json:
    defaults = {
        "compaction_test_pct": compaction_test_pct,
        "drainage_inspection_passed": drainage_inspection_passed,
    }
    return _merge(defaults, overrides)


# ---------------------------------------------------------------------------
# PRD 3.3 — yard zones and deliveries
# ---------------------------------------------------------------------------
def yard_zone_payload(**overrides: Any) -> Json:
    defaults = {"zone_code": "Y1", "pallet_capacity": 100}
    return _merge(defaults, overrides)


def delivery_payload(
    project_id: str,
    yard_zone_id: str,
    expected_yard_zone_version: int,
    **overrides: Any,
) -> Json:
    defaults = {
        "project_id": project_id,
        "yard_zone_id": yard_zone_id,
        "component_type": "MODULE",
        "unit_qty": 60,
        "pallets": 60,
        "planned_arrival_at": "2026-08-03T09:00:00Z",
        "laydown_window_start": "2026-08-03T00:00:00Z",
        "laydown_window_end": "2026-08-07T00:00:00Z",
        "expected_yard_zone_version": expected_yard_zone_version,
    }
    return _merge(defaults, overrides)


def receipt_payload(
    received_unit_qty: int, damaged_unit_qty: int, **overrides: Any
) -> Json:
    defaults = {
        "received_unit_qty": received_unit_qty,
        "damaged_unit_qty": damaged_unit_qty,
    }
    return _merge(defaults, overrides)


def cancellation_payload(
    cancel_reason: str = "supplier slipped the ship date", **overrides: Any
) -> Json:
    return _merge({"cancel_reason": cancel_reason}, overrides)


# ---------------------------------------------------------------------------
# PRD 3.4 — blocks, piles, remediation, mechanical completion
# ---------------------------------------------------------------------------
def block_payload(grading_area_id: str, **overrides: Any) -> Json:
    defaults = {
        "grading_area_id": grading_area_id,
        "block_code": "B1",
        "dc_capacity_kw": 130,
        "planned_pile_count": 1,
        "planned_string_count": 1,
    }
    return _merge(defaults, overrides)


def pile_payload(**overrides: Any) -> Json:
    defaults = {"row_index": 1, "position_index": 1, "design_embedment_mm": 3000}
    return _merge(defaults, overrides)


def drive_result_payload(
    actual_embedment_mm: int = 3000,
    plumb_deviation_mm: float = 5.0,
    blow_count: int = 42,
    refusal: bool = False,
    **overrides: Any,
) -> Json:
    defaults = {
        "actual_embedment_mm": actual_embedment_mm,
        "plumb_deviation_mm": plumb_deviation_mm,
        "blow_count": blow_count,
        "refusal": refusal,
    }
    return _merge(defaults, overrides)


def remediation_payload(
    remediation_method: str,
    actual_embedment_mm: int,
    plumb_deviation_mm: float,
    **overrides: Any,
) -> Json:
    defaults = {
        "remediation_method": remediation_method,
        "actual_embedment_mm": actual_embedment_mm,
        "plumb_deviation_mm": plumb_deviation_mm,
    }
    return _merge(defaults, overrides)


def mechanical_completion_payload(
    modules_installed_qty: int = 50,
    max_torque_tube_deviation_mm: float = 18.0,
    **overrides: Any,
) -> Json:
    defaults = {
        "modules_installed_qty": modules_installed_qty,
        "max_torque_tube_deviation_mm": max_torque_tube_deviation_mm,
    }
    return _merge(defaults, overrides)


# ---------------------------------------------------------------------------
# PRD 3.5 — string circuits
# ---------------------------------------------------------------------------
def string_circuit_payload(**overrides: Any) -> Json:
    defaults = {"circuit_code": "C1", "modules_in_series": 15}
    return _merge(defaults, overrides)


def wiring_payload(combiner_position: str = "CB1-01", **overrides: Any) -> Json:
    return _merge({"combiner_position": combiner_position}, overrides)


def string_test_payload(
    insulation_resistance_mohm: float = 55.0,
    measured_voc_v: float = 705.00,
    ambient_c: float = 40,
    polarity_ok: bool = True,
    **overrides: Any,
) -> Json:
    defaults = {
        "insulation_resistance_mohm": insulation_resistance_mohm,
        "measured_voc_v": measured_voc_v,
        "ambient_c": ambient_c,
        "polarity_ok": polarity_ok,
    }
    return _merge(defaults, overrides)


# ---------------------------------------------------------------------------
# PRD 3.6 — substation and outage windows
# ---------------------------------------------------------------------------
def substation_payload(**overrides: Any) -> Json:
    defaults = {
        "substation_code": "S1",
        "interconnection_voltage_kv": 138.0,
        "mv_collection_km": 12.5,
    }
    return _merge(defaults, overrides)


def status_advance_payload(to_status: str, utility_witness_ref: str, **overrides: Any) -> Json:
    defaults = {"to_status": to_status, "utility_witness_ref": utility_witness_ref}
    return _merge(defaults, overrides)


def outage_window_payload(
    start_at: str = "2026-08-10T00:00:00Z",
    end_at: str = "2026-08-10T04:00:00Z",
    purpose: str = "BACKFEED",
    **overrides: Any,
) -> Json:
    defaults = {"start_at": start_at, "end_at": end_at, "purpose": purpose}
    return _merge(defaults, overrides)


def utility_response_payload(
    decision: str, utility_reference: str = "SO-4471", **overrides: Any
) -> Json:
    defaults = {"decision": decision, "utility_reference": utility_reference}
    return _merge(defaults, overrides)


# ---------------------------------------------------------------------------
# PRD 3.7 — commissioning
# ---------------------------------------------------------------------------
def commissioning_test_payload(
    project_id: str,
    expected_project_version: int,
    test_type: str = "CAPACITY",
    scheduled_at: str = "2026-08-10T02:30:00Z",
    **overrides: Any,
) -> Json:
    defaults = {
        "project_id": project_id,
        "test_type": test_type,
        "scheduled_at": scheduled_at,
        "expected_project_version": expected_project_version,
    }
    return _merge(defaults, overrides)


def interval_payload(
    sampled_at: str,
    irradiance_w_m2: float,
    measured_kw_ac: float,
    ambient_c: float = 30,
    wind_m_s: float = 3.0,
    **overrides: Any,
) -> Json:
    defaults = {
        "sampled_at": sampled_at,
        "irradiance_w_m2": irradiance_w_m2,
        "measured_kw_ac": measured_kw_ac,
        "ambient_c": ambient_c,
        "wind_m_s": wind_m_s,
    }
    return _merge(defaults, overrides)


def finalization_payload(**overrides: Any) -> Json:
    return dict(overrides)


# ---------------------------------------------------------------------------
# PRD 3.9 — punch list
# ---------------------------------------------------------------------------
def punch_list_item_payload(
    title: str = "Combiner box label missing",
    category: str = "ELECTRICAL",
    severity: str = "MINOR",
    estimated_cost_cents: int = 20000,
    **overrides: Any,
) -> Json:
    defaults = {
        "title": title,
        "category": category,
        "severity": severity,
        "estimated_cost_cents": estimated_cost_cents,
    }
    return _merge(defaults, overrides)


def closure_submission_payload(
    closure_evidence_ref: str = "PHOTO-1001", **overrides: Any
) -> Json:
    return _merge({"closure_evidence_ref": closure_evidence_ref}, overrides)


def closure_decision_payload(decision: str, **overrides: Any) -> Json:
    return _merge({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# PRD 3.8 — certified payroll
# ---------------------------------------------------------------------------
def payroll_week_payload(week_start_date: str = "2026-08-03", **overrides: Any) -> Json:
    return _merge({"week_start_date": week_start_date}, overrides)


def labor_entry_payload(
    worker_ref: str = "W-501",
    classification: str = "ELECTRICIAN",
    is_apprentice: bool = False,
    hours: float = 8.00,
    paid_rate_cents: int = 4500,
    fringe_rate_cents: int = 500,
    prevailing_rate_cents: int = 5000,
    work_date: str = "2026-08-03",
    **overrides: Any,
) -> Json:
    defaults = {
        "worker_ref": worker_ref,
        "classification": classification,
        "is_apprentice": is_apprentice,
        "hours": hours,
        "paid_rate_cents": paid_rate_cents,
        "fringe_rate_cents": fringe_rate_cents,
        "prevailing_rate_cents": prevailing_rate_cents,
        "work_date": work_date,
    }
    return _merge(defaults, overrides)


def void_payload(void_reason: str = "hours booked to the wrong project", **overrides: Any) -> Json:
    return _merge({"void_reason": void_reason}, overrides)


def certification_payload(**overrides: Any) -> Json:
    return dict(overrides)
