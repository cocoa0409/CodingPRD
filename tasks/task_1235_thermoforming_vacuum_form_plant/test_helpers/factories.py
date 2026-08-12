"""Payload factories — one per creatable resource, input fields only (PRD §3).

Codes are auto-uniqued per process so composite fixtures can create several
resources of the same kind without collisions.
"""
import itertools

from .constants import CERT_BODY, CERT_EXPIRES_AT, CERT_ISSUED_AT

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_material_lot_payload(**overrides) -> dict:
    """PRD §3.1 inputs: lot_code, resin_type, gauge_mm,
    cleanliness_grade_required, quantity_kg, unit_cost_per_kg."""
    defaults = {
        "lot_code": _unique("L"),
        "resin_type": "PETG",
        "gauge_mm": 1.500,
        "cleanliness_grade_required": "INDUSTRIAL",
        "quantity_kg": 10.000,
        "unit_cost_per_kg": 10.00,
    }
    defaults.update(overrides)
    return defaults


def create_regrind_batch_payload(**overrides) -> dict:
    """PRD §3.2 inputs: batch_code, resin_type, source_grade, target_kg."""
    defaults = {
        "batch_code": _unique("RB"),
        "resin_type": "PETG",
        "source_grade": "INDUSTRIAL",
        "target_kg": 2.000,
    }
    defaults.update(overrides)
    return defaults


def create_tool_payload(**overrides) -> dict:
    """PRD §3.3 inputs: tool_code, part_number, tool_type, min_gauge_mm,
    max_gauge_mm, cleanliness_grade, prototype_cost."""
    defaults = {
        "tool_code": _unique("T"),
        "part_number": _unique("P"),
        "tool_type": "FORM_MOLD",
        "min_gauge_mm": 1.000,
        "max_gauge_mm": 3.000,
        "cleanliness_grade": "INDUSTRIAL",
        "prototype_cost": 1000.00,
    }
    defaults.update(overrides)
    return defaults


def create_approve_production_payload(**overrides) -> dict:
    """PRD §3.3 approve-production inputs: production_cost, rated_lifetime_shots."""
    defaults = {"production_cost": 8000.00, "rated_lifetime_shots": 80000}
    defaults.update(overrides)
    return defaults


def create_packaging_spec_payload(**overrides) -> dict:
    """PRD §3.4 inputs: spec_code, spec_type, cleanliness_grade, per_pack_cost."""
    defaults = {
        "spec_code": _unique("S"),
        "spec_type": "STOCK",
        "cleanliness_grade": "INDUSTRIAL",
        "per_pack_cost": 0.30,
    }
    defaults.update(overrides)
    return defaults


def create_spec_decide_payload(decision="APPROVED") -> dict:
    return {"decision": decision}


def create_production_order_payload(tool_id, packaging_spec_id, **overrides) -> dict:
    """PRD §3.5 inputs for opening a production order."""
    defaults = {
        "order_code": _unique("O"),
        "part_number": "P-1",
        "resin_type": "PETG",
        "ordered_qty": 100,
        "required_gauge_mm": 1.500,
        "cleanliness_grade": "INDUSTRIAL",
        "is_prototype_order": False,
        "spec_nominal_wall_mm": 1.300,
        "spec_min_wall_mm": 1.230,
        "nominal_part_weight_kg": 0.050,
        "std_cycle_time_s": 30,
        "std_machine_rate_per_hour": 55.00,
        "tool_id": tool_id,
        "packaging_spec_id": packaging_spec_id,
    }
    defaults.update(overrides)
    return defaults


def create_stage_payload(expected_production_order_version) -> dict:
    """PRD §2.7: staging carries the last-observed order version."""
    return {"expected_production_order_version": expected_production_order_version}


def create_material_allocation_payload(
    production_order_id, source_type="VIRGIN_LOT", qty_kg=1.000,
    lot_id=None, regrind_batch_id=None, **overrides,
) -> dict:
    """PRD §3.5 inputs; conditional fields follow the source_type rule."""
    payload = {
        "production_order_id": production_order_id,
        "source_type": source_type,
        "qty_kg": qty_kg,
    }
    if lot_id is not None:
        payload["lot_id"] = lot_id
    if regrind_batch_id is not None:
        payload["regrind_batch_id"] = regrind_batch_id
    payload.update(overrides)
    return payload


def create_machine_resource_payload(**overrides) -> dict:
    """PRD §3.6 inputs: resource_code, resource_type, cleanliness_grade,
    machine_rate_per_hour."""
    defaults = {
        "resource_code": _unique("ST"),
        "resource_type": "FORMING_STATION",
        "cleanliness_grade": "INDUSTRIAL",
        "machine_rate_per_hour": 55.00,
    }
    defaults.update(overrides)
    return defaults


def create_forming_run_payload(production_order_id, station_id, **overrides) -> dict:
    """PRD §3.6 inputs for scheduling a run."""
    defaults = {
        "production_order_id": production_order_id,
        "station_id": station_id,
        "planned_start": "2026-05-02T10:00:00Z",
        "planned_end": "2026-05-02T10:30:00Z",
        "oven_temp_c": 180.0,
        "cycle_time_s": 30,
        "shots_planned": 10,
    }
    defaults.update(overrides)
    return defaults


def create_run_complete_payload(shots_completed, scrap_weight_kg=0.000,
                                actual_end="2026-05-02T10:30:00Z") -> dict:
    """PRD §3.6 complete inputs: shots_completed, scrap_weight_kg, actual_end."""
    return {
        "shots_completed": shots_completed,
        "scrap_weight_kg": scrap_weight_kg,
        "actual_end": actual_end,
    }


def create_scrap_certify_payload(regrind_batch_id, decision="CERTIFY") -> dict:
    """PRD §3.2 certify inputs: regrind_batch_id, decision."""
    return {"regrind_batch_id": regrind_batch_id, "decision": decision}


def create_batch_decide_payload(decision="CERTIFIED", certified_grade=None) -> dict:
    """PRD §3.2 decide inputs; certified_grade required unless REJECTED."""
    payload = {"decision": decision}
    if certified_grade is not None:
        payload["certified_grade"] = certified_grade
    return payload


def create_quality_inspection_payload(production_order_id, booth_id,
                                      forming_run_id=None, **overrides) -> dict:
    """PRD §3.7 inputs; forming_run_id only for FIRST_ARTICLE inspections."""
    defaults = {
        "production_order_id": production_order_id,
        "booth_id": booth_id,
        "inspection_type": "FIRST_ARTICLE",
        "scheduled_start": "2026-05-02T12:00:00Z",
        "scheduled_end": "2026-05-02T12:30:00Z",
        "wall_measurements_mm": [1.240, 1.250],
    }
    defaults.update(overrides)
    if forming_run_id is not None:
        defaults["forming_run_id"] = forming_run_id
    return defaults


def create_disposition_payload(disposition="PASS", scrapped_qty=None) -> dict:
    """PRD §3.7 disposition inputs; scrapped_qty only for SCRAP."""
    payload = {"disposition": disposition}
    if scrapped_qty is not None:
        payload["scrapped_qty"] = scrapped_qty
    return payload


def create_assembly_task_payload(production_order_id, insert_part_code=None,
                                 **overrides) -> dict:
    """PRD §3.8 inputs; insert_part_code only when task_type is INSERT."""
    defaults = {
        "production_order_id": production_order_id,
        "task_type": "TRIM",
        "sequence_no": 1,
    }
    defaults.update(overrides)
    if insert_part_code is not None:
        defaults["insert_part_code"] = insert_part_code
    return defaults


def create_cleanliness_certificate_payload(subject_type, subject_id, **overrides) -> dict:
    """PRD §2.5 inputs: subject_type, subject_id, grade, issued_at,
    expires_at, cert_body."""
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "grade": "INDUSTRIAL",
        "issued_at": CERT_ISSUED_AT,
        "expires_at": CERT_EXPIRES_AT,
        "cert_body": CERT_BODY,
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601) -> dict:
    """PRD §2.5: the clock is set to a supplied to_iso8601 instant."""
    return {"to_iso8601": to_iso8601}


__all__ = [name for name in dir() if name.startswith("create_")]
