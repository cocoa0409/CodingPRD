"""
Request-payload builders for the Valve Manufacturing & Product Certification API.

Each builder spells out the fields the PRD declares as required for that write and
leaves declared-optional fields out unless the caller supplies them, so that a
builder call reads as the business intent rather than as a wire format. Conditional
fields are filled where the PRD makes them conditional-required: ``leak_drops`` is
required when ``test_type`` is ``SEAT`` and ``leak_rate_ppm`` is required when
``test_type`` is ``FUGITIVE_EMISSION``.
"""

from typing import List, Optional

from .constants import FRESH_CLOCK_UTC
from .types import Payload


def _with_optional(payload: Payload, **optional) -> Payload:
    for key, value in optional.items():
        if value is not None:
            payload[key] = value
    return payload


# ─── Product-line designs ─────────────────────────────


def valve_model_payload(
    model_code: str,
    valve_type: str,
    pressure_class: int,
    body_material_grade: str,
    bore_size_mm: float,
    seat_type: str,
    base_break_torque_nm: float,
    required_special_services: Optional[List[str]] = None,
    repair_kit_stock_qty: Optional[int] = None,
    supersedes_model_id: Optional[str] = None,
) -> Payload:
    payload: Payload = {
        "model_code": model_code,
        "valve_type": valve_type,
        "pressure_class": pressure_class,
        "body_material_grade": body_material_grade,
        "bore_size_mm": bore_size_mm,
        "seat_type": seat_type,
        "base_break_torque_nm": base_break_torque_nm,
    }
    return _with_optional(
        payload,
        required_special_services=required_special_services,
        repair_kit_stock_qty=repair_kit_stock_qty,
        supersedes_model_id=supersedes_model_id,
    )


def model_action_payload(action: str) -> Payload:
    """``SUBMIT_REVIEW`` | ``RELEASE`` | ``REJECT`` | ``WITHDRAW``."""
    return {"action": action}


# ─── Foundries and qualifications ─────────────────────


def foundry_payload(foundry_code: str, name: str, country_code: str) -> Payload:
    return {"foundry_code": foundry_code, "name": name, "country_code": country_code}


def foundry_qualification_payload(
    foundry_id: str,
    process: str,
    material_grade: str,
    max_pressure_class: int,
    valid_from: str,
    valid_until: str,
) -> Payload:
    return {
        "foundry_id": foundry_id,
        "process": process,
        "material_grade": material_grade,
        "max_pressure_class": max_pressure_class,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }


def qualification_action_payload(
    action: str, valid_from: Optional[str] = None, valid_until: Optional[str] = None
) -> Payload:
    """``QUALIFY`` | ``REVOKE`` | ``REQUALIFY``; requalification carries a fresh window."""
    return _with_optional({"action": action}, valid_from=valid_from, valid_until=valid_until)


# ─── Heat lots and components ─────────────────────────


def heat_lot_payload(
    foundry_id: str,
    heat_number: str,
    material_grade: str,
    process: str,
    qty_received_kg: float,
    mtr_document_ref: str,
    carbon_equivalent_pct: float,
    impact_energy_j: float,
) -> Payload:
    return {
        "foundry_id": foundry_id,
        "heat_number": heat_number,
        "material_grade": material_grade,
        "process": process,
        "qty_received_kg": qty_received_kg,
        "mtr_document_ref": mtr_document_ref,
        "carbon_equivalent_pct": carbon_equivalent_pct,
        "impact_energy_j": impact_energy_j,
    }


def lot_disposition_payload(action: str, quarantine_reason: Optional[str] = None) -> Payload:
    """``VERIFY`` | ``RELEASE`` | ``QUARANTINE`` | ``REJECT``."""
    return _with_optional({"action": action}, quarantine_reason=quarantine_reason)


def component_payload(
    heat_lot_id: str, target_model_id: str, component_type: str, net_weight_kg: float
) -> Payload:
    return {
        "heat_lot_id": heat_lot_id,
        "target_model_id": target_model_id,
        "component_type": component_type,
        "net_weight_kg": net_weight_kg,
    }


def component_disposition_payload(action: str) -> Payload:
    """``ISSUE_TO_MACHINING`` | ``SCRAP`` | ``VOID``."""
    return {"action": action}


# ─── Valve units ──────────────────────────────────────


def valve_unit_payload(
    model_id: str,
    body_component_id: str,
    monogram_license_id: str,
    serial_number: str,
    special_services: Optional[List[str]] = None,
    engineered_order_id: Optional[str] = None,
) -> Payload:
    payload: Payload = {
        "model_id": model_id,
        "body_component_id": body_component_id,
        "monogram_license_id": monogram_license_id,
        "serial_number": serial_number,
    }
    return _with_optional(
        payload,
        special_services=special_services,
        engineered_order_id=engineered_order_id,
    )


def build_action_payload(action: str, to_build_status: Optional[str] = None) -> Payload:
    """``ADVANCE`` with a target build status, or ``REWORK_COMPLETE``."""
    return _with_optional({"action": action}, to_build_status=to_build_status)


def advance_build_payload(to_build_status: str) -> Payload:
    return {"action": "ADVANCE", "to_build_status": to_build_status}


def cert_action_payload(action: str, decertification_reason: Optional[str] = None) -> Payload:
    """``CERTIFY`` | ``DECERTIFY``."""
    return _with_optional({"action": action}, decertification_reason=decertification_reason)


def service_action_payload(
    action: str, engineer_user_id: Optional[str] = None, kit_qty: Optional[int] = None
) -> Payload:
    """``OPEN`` | ``RESERVE_KIT`` | ``START`` | ``COMPLETE`` | ``ABORT``."""
    return _with_optional(
        {"action": action}, engineer_user_id=engineer_user_id, kit_qty=kit_qty
    )


# ─── Test records ─────────────────────────────────────


def test_record_payload(
    test_type: str,
    test_bench_code: str,
    started_at: str,
    ended_at: str,
    test_pressure_bar: float,
    hold_seconds: int,
    result: str,
    leak_rate_ppm: Optional[float] = None,
    leak_drops: Optional[int] = None,
    standard_ref: Optional[str] = None,
) -> Payload:
    payload: Payload = {
        "test_type": test_type,
        "test_bench_code": test_bench_code,
        "started_at": started_at,
        "ended_at": ended_at,
        "test_pressure_bar": test_pressure_bar,
        "hold_seconds": hold_seconds,
        "result": result,
    }
    # leak_drops is required when test_type is SEAT; leak_rate_ppm is required
    # when test_type is FUGITIVE_EMISSION.
    if test_type == "SEAT" and leak_drops is None:
        leak_drops = 0
    if test_type == "FUGITIVE_EMISSION" and leak_rate_ppm is None:
        leak_rate_ppm = 0.0
    return _with_optional(
        payload,
        leak_rate_ppm=leak_rate_ppm,
        leak_drops=leak_drops,
        standard_ref=standard_ref,
    )


# ─── Actuator packages ────────────────────────────────


def actuator_package_payload(
    valve_unit_id: str,
    actuator_type: str,
    output_torque_nm: float,
    sizing_basis: str,
    expected_valve_unit_version: int,
    supply_pressure_bar: Optional[float] = None,
) -> Payload:
    payload: Payload = {
        "valve_unit_id": valve_unit_id,
        "actuator_type": actuator_type,
        "output_torque_nm": output_torque_nm,
        "sizing_basis": sizing_basis,
        "expected_valve_unit_version": expected_valve_unit_version,
    }
    return _with_optional(payload, supply_pressure_bar=supply_pressure_bar)


def actuator_decision_payload(decision: str) -> Payload:
    """``APPROVE`` | ``REJECT``."""
    return {"decision": decision}


# ─── Monogram licenses ────────────────────────────────


def monogram_license_payload(
    license_code: str,
    facility_code: str,
    scope_valve_types: List[str],
    lead_auditor_user_id: str,
    audit_window_start: str,
    audit_window_end: str,
) -> Payload:
    return {
        "license_code": license_code,
        "facility_code": facility_code,
        "scope_valve_types": scope_valve_types,
        "lead_auditor_user_id": lead_auditor_user_id,
        "audit_window_start": audit_window_start,
        "audit_window_end": audit_window_end,
    }


def license_action_payload(
    action: str,
    audit_window_start: Optional[str] = None,
    audit_window_end: Optional[str] = None,
) -> Payload:
    """``SCHEDULE_AUDIT`` | ``START_AUDIT`` | ``CLOSE_AUDIT`` | ``GRANT`` |
    ``GRANT_CONDITIONAL`` | ``DENY`` | ``SUSPEND`` | ``REINSTATE``."""
    return _with_optional(
        {"action": action},
        audit_window_start=audit_window_start,
        audit_window_end=audit_window_end,
    )


def finding_entry_payload(entry_action: str, severity: str) -> Payload:
    """``RAISE`` | ``CLOSE`` | ``WAIVE`` with ``MAJOR`` or ``MINOR`` severity."""
    return {"entry_action": entry_action, "severity": severity}


# ─── Engineered orders ────────────────────────────────


def engineered_order_payload(
    order_code: str,
    model_id: str,
    ordered_qty: int,
    unit_price_cents: int,
    customer_credit_limit_cents: int,
    datasheet_break_torque_nm: float,
    datasheet_torque_source: str,
    requested_special_services: Optional[List[str]] = None,
    expedite_requested: Optional[bool] = None,
) -> Payload:
    payload: Payload = {
        "order_code": order_code,
        "model_id": model_id,
        "ordered_qty": ordered_qty,
        "unit_price_cents": unit_price_cents,
        "customer_credit_limit_cents": customer_credit_limit_cents,
        "datasheet_break_torque_nm": datasheet_break_torque_nm,
        "datasheet_torque_source": datasheet_torque_source,
    }
    return _with_optional(
        payload,
        requested_special_services=requested_special_services,
        expedite_requested=expedite_requested,
    )


def review_action_payload(action: str) -> Payload:
    """``SUBMIT_REVIEW`` | ``REQUEST_CLARIFICATION`` | ``APPROVE`` | ``REJECT``."""
    return {"action": action}


def lifecycle_action_payload(action: str) -> Payload:
    """``RELEASE_TO_PRODUCTION`` | ``RESUME`` | ``CLOSE`` | ``CANCEL`` |
    ``ISSUE_DOC_PACKAGE`` | ``VOID_DOC_PACKAGE``."""
    return {"action": action}


def datasheet_revision_payload(
    datasheet_break_torque_nm: float,
    datasheet_torque_source: str,
    expected_engineered_order_version: int,
) -> Payload:
    return {
        "datasheet_break_torque_nm": datasheet_break_torque_nm,
        "datasheet_torque_source": datasheet_torque_source,
        "expected_engineered_order_version": expected_engineered_order_version,
    }


def order_document_payload(doc_type: str, doc_ref: str) -> Payload:
    return {"doc_type": doc_type, "doc_ref": doc_ref}


# ─── Convenient interval defaults ─────────────────────

DEFAULT_QUALIFICATION_WINDOW = ("2026-01-01T00:00:00Z", "2026-12-31T00:00:00Z")
DEFAULT_AUDIT_WINDOW = ("2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z")
DEFAULT_BENCH_INTERVAL = ("2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z")
FRESH_CLOCK = FRESH_CLOCK_UTC
