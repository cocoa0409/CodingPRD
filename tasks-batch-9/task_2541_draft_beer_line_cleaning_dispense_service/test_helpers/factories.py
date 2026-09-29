"""Payload factories for every write endpoint the PRD declares.

Each factory produces a valid, PRD-shaped body with sensible defaults and lets a
caller override any field with a keyword argument.  Optional inputs are omitted
unless supplied so a test can exercise the declared fallback behaviour.
"""

from typing import Any, Dict, Optional

from .types import (
    BeerStyleGroup,
    CertificationLevel,
    ChemicalType,
    ComponentType,
    ConditionGrade,
    ActionTaken,
    DiagnosticOutcome,
    Disposition,
    FindingCode,
    FundedScope,
    Symptom,
    TechnicianStatus,
    VerificationDecision,
    VisitKind,
)


def _with(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    base.update({k: v for k, v in overrides.items() if v is not None})
    return base


# --- Venue onboarding -------------------------------------------------------
def account_payload(
    venue_name: str = "Harbor Taproom",
    access_window_start_minute: int = 480,
    access_window_end_minute: int = 1080,
    glycol_system_present: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "venue_name": venue_name,
        "access_window_start_minute": access_window_start_minute,
        "access_window_end_minute": access_window_end_minute,
    }
    if glycol_system_present is not None:
        payload["glycol_system_present"] = glycol_system_present
    payload.update(overrides)
    return payload


def contract_payload(
    account_id: str,
    expected_account_version: int,
    cleaning_frequency_days: int = 21,
    contracted_line_count: int = 4,
    per_line_rate_cents: int = 4175,
    visit_base_fee_cents: int = 7500,
    effective_from: str = "2026-08-01T00:00:00Z",
    brewer_program_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "cleaning_frequency_days": cleaning_frequency_days,
        "contracted_line_count": contracted_line_count,
        "per_line_rate_cents": per_line_rate_cents,
        "visit_base_fee_cents": visit_base_fee_cents,
        "effective_from": effective_from,
        "expected_account_version": expected_account_version,
    }
    if brewer_program_id is not None:
        payload["brewer_program_id"] = brewer_program_id
    payload.update(overrides)
    return payload


def beer_line_payload(
    account_id: str,
    line_number: int = 1,
    run_length_feet: float = 32,
    vertical_rise_feet: float = 4,
    inner_diameter_inches: float = 0.375,
    beer_style_group: str = BeerStyleGroup.ALE,
    average_daily_throughput_liters: float = 12.0,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "line_number": line_number,
        "run_length_feet": run_length_feet,
        "vertical_rise_feet": vertical_rise_feet,
        "inner_diameter_inches": inner_diameter_inches,
        "beer_style_group": beer_style_group,
        "average_daily_throughput_liters": average_daily_throughput_liters,
    }
    payload.update(overrides)
    return payload


# --- Crew, chemistry and catalogue ------------------------------------------
def technician_payload(
    full_name: str = "Dana Ruiz",
    certification_level: str = CertificationLevel.MASTER,
    caustic_certified: Optional[bool] = True,
    status: Optional[str] = TechnicianStatus.ACTIVE,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "certification_level": certification_level,
    }
    if caustic_certified is not None:
        payload["caustic_certified"] = caustic_certified
    if status is not None:
        payload["status"] = status
    payload.update(overrides)
    return payload


def chemical_lot_payload(
    chemical_type: str = ChemicalType.CAUSTIC,
    lot_code: str = "C-1001",
    concentration_pct_stock: float = 45.0,
    liters_initial: float = 20.0,
    expires_on: str = "2026-12-31",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "chemical_type": chemical_type,
        "lot_code": lot_code,
        "concentration_pct_stock": concentration_pct_stock,
        "liters_initial": liters_initial,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def part_payload(
    sku: str = "FAUCET-88",
    component_type: str = ComponentType.FAUCET,
    unit_price_cents: int = 3195,
    stock_on_hand: int = 5,
    brewer_funded_eligible: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sku": sku,
        "component_type": component_type,
        "unit_price_cents": unit_price_cents,
        "stock_on_hand": stock_on_hand,
    }
    if brewer_funded_eligible is not None:
        payload["brewer_funded_eligible"] = brewer_funded_eligible
    payload.update(overrides)
    return payload


def brewer_program_payload(
    brewer_name: str = "Southside Brewing",
    funded_scope: str = FundedScope.CLEANING_ONLY,
    co_pay_bps: int = 1500,
    funding_cap_cents: int = 50000,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "brewer_name": brewer_name,
        "funded_scope": funded_scope,
        "co_pay_bps": co_pay_bps,
        "funding_cap_cents": funding_cap_cents,
    }
    payload.update(overrides)
    return payload


# --- Route board ------------------------------------------------------------
def service_visit_payload(
    account_id: str,
    technician_id: str,
    visit_kind: str = VisitKind.ROUTINE_CLEANING,
    scheduled_date: str = "2026-08-05",
    scheduled_start_minute: int = 540,
    scheduled_end_minute: int = 660,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "technician_id": technician_id,
        "visit_kind": visit_kind,
        "scheduled_date": scheduled_date,
        "scheduled_start_minute": scheduled_start_minute,
        "scheduled_end_minute": scheduled_end_minute,
    }
    payload.update(overrides)
    return payload


def reschedule_payload(
    scheduled_date: str = "2026-08-06",
    scheduled_start_minute: int = 540,
    scheduled_end_minute: int = 660,
    technician_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scheduled_date": scheduled_date,
        "scheduled_start_minute": scheduled_start_minute,
        "scheduled_end_minute": scheduled_end_minute,
    }
    if technician_id is not None:
        payload["technician_id"] = technician_id
    payload.update(overrides)
    return payload


# --- Field records ----------------------------------------------------------
def cleaning_cycle_payload(
    visit_id: str,
    line_id: str,
    chemical_lot_id: str,
    chemical_type: str = ChemicalType.CAUSTIC,
    contact_minutes: int = 20,
    recirculation_temp_f: float = 96.0,
    concentrate_liters_used: float = 0.31,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "visit_id": visit_id,
        "line_id": line_id,
        "chemical_lot_id": chemical_lot_id,
        "chemical_type": chemical_type,
        "contact_minutes": contact_minutes,
        "recirculation_temp_f": recirculation_temp_f,
        "concentrate_liters_used": concentrate_liters_used,
    }
    payload.update(overrides)
    return payload


def balance_record_payload(
    visit_id: str,
    line_id: str,
    expected_line_version: int,
    measured_temp_f: float = 38.0,
    proposed_applied_psi: float = 13.60,
    proposed_co2_pct: float = 59.2,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "visit_id": visit_id,
        "line_id": line_id,
        "measured_temp_f": measured_temp_f,
        "proposed_applied_psi": proposed_applied_psi,
        "proposed_co2_pct": proposed_co2_pct,
        "expected_line_version": expected_line_version,
    }
    payload.update(overrides)
    return payload


def balance_decision_payload(
    decision: str,
    decision_note: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    payload.update(overrides)
    return payload


def component_inspection_payload(
    visit_id: str,
    line_id: str,
    component_type: str = ComponentType.FAUCET,
    condition_grade: str = ConditionGrade.WORN,
    action_taken: str = ActionTaken.REPLACED,
    part_sku_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "visit_id": visit_id,
        "line_id": line_id,
        "component_type": component_type,
        "condition_grade": condition_grade,
        "action_taken": action_taken,
    }
    if part_sku_id is not None:
        payload["part_sku_id"] = part_sku_id
    payload.update(overrides)
    return payload


def glycol_maintenance_payload(
    visit_id: str,
    glycol_pct: float = 35.0,
    pump_psi: float = 12.0,
    bath_temp_f: float = 28.0,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "visit_id": visit_id,
        "glycol_pct": glycol_pct,
        "pump_psi": pump_psi,
        "bath_temp_f": bath_temp_f,
    }
    payload.update(overrides)
    return payload


def cooler_reading_payload(
    glycol_loop_id: str,
    cooler_temp_f: float = 38.0,
    glycol_supply_temp_f: float = 26.0,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "glycol_loop_id": glycol_loop_id,
        "cooler_temp_f": cooler_temp_f,
        "glycol_supply_temp_f": glycol_supply_temp_f,
    }
    payload.update(overrides)
    return payload


# --- Close-out --------------------------------------------------------------
def verification_payload(
    decision: str = VerificationDecision.SIGN,
    signer_name: Optional[str] = None,
    dispute_reason: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if signer_name is not None:
        payload["signer_name"] = signer_name
    if dispute_reason is not None:
        payload["dispute_reason"] = dispute_reason
    payload.update(overrides)
    return payload


# --- Complaints -------------------------------------------------------------
def quality_complaint_payload(
    account_id: str,
    line_id: str,
    symptom: str = Symptom.FOAMY_POUR,
    **overrides,
) -> Dict[str, Any]:
    payload = {"account_id": account_id, "line_id": line_id, "symptom": symptom}
    payload.update(overrides)
    return payload


def diagnostic_round_payload(
    outcome: str = DiagnosticOutcome.ROOT_CAUSE_FOUND,
    finding_code: str = FindingCode.LINE_SOIL,
    **overrides,
) -> Dict[str, Any]:
    payload = {"outcome": outcome, "finding_code": finding_code}
    payload.update(overrides)
    return payload


def closure_payload(
    disposition: str = Disposition.RESOLVED,
    measured_waste_liters: float = 4.0,
    **overrides,
) -> Dict[str, Any]:
    payload = {"disposition": disposition, "measured_waste_liters": measured_waste_liters}
    payload.update(overrides)
    return payload
