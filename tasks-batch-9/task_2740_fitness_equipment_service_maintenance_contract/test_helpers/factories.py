"""
Payload factories for every FleetCare write endpoint.

Each factory produces a valid, minimal-but-complete body using PRD-exact field
names, and lets a test override any field with a keyword argument. Optional fields
are only emitted when the caller asks for them, so a factory call never accidentally
supplies a value where the test means to exercise the declared default.

Money is always an integer number of cents — never a float and never a string.
"""

from typing import Any, Dict, List, Optional

# ─── Clubs ────────────────────────────────────────────────────────────────────


def club_payload(
    name: str = "Northside Fitness",
    region_code: str = "NW",
    operating_open_minute: Optional[int] = None,
    operating_close_minute: Optional[int] = None,
    max_concurrent_visits: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "region_code": region_code}
    if operating_open_minute is not None:
        payload["operating_open_minute"] = operating_open_minute
    if operating_close_minute is not None:
        payload["operating_close_minute"] = operating_close_minute
    if max_concurrent_visits is not None:
        payload["max_concurrent_visits"] = max_concurrent_visits
    payload.update(overrides)
    return payload


# ─── Equipment models ─────────────────────────────────────────────────────────


def checklist_item(
    code: str, is_safety_critical: bool = False, consumable: bool = False
) -> Dict[str, Any]:
    return {
        "code": code,
        "is_safety_critical": is_safety_critical,
        "consumable": consumable,
    }


def equipment_model_payload(
    manufacturer: str = "Pacemaster",
    model_code: str = "TM-900",
    category: str = "TREADMILL",
    model_year: int = 2019,
    pm_interval_hours: int = 250,
    expected_service_life_hours: int = 20000,
    base_annual_service_cents: int = 120000,
    checklist_template: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "manufacturer": manufacturer,
        "model_code": model_code,
        "category": category,
        "model_year": model_year,
        "pm_interval_hours": pm_interval_hours,
        "expected_service_life_hours": expected_service_life_hours,
        "base_annual_service_cents": base_annual_service_cents,
    }
    if checklist_template is not None:
        payload["checklist_template"] = checklist_template
    payload.update(overrides)
    return payload


# ─── Equipment ────────────────────────────────────────────────────────────────


def equipment_payload(
    club_id: str,
    model_id: str,
    serial_number: str = "SN-0001",
    install_date: str = "2024-03-01",
    initial_usage_hours: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "model_id": model_id,
        "serial_number": serial_number,
        "install_date": install_date,
    }
    if initial_usage_hours is not None:
        payload["initial_usage_hours"] = initial_usage_hours
    payload.update(overrides)
    return payload


def usage_reading_payload(usage_hours: float, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"usage_hours": usage_hours}
    payload.update(overrides)
    return payload


def tag_out_payload(reason: str = "INSPECTOR_TAG_OUT", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Service contracts ────────────────────────────────────────────────────────


def contract_payload(
    club_id: str,
    coverage_tier: str = "GOLD",
    parts_inclusion: str = "FULL",
    pm_visits_per_year: int = 4,
    annual_base_cents: int = 250000,
    initial_parts_allowance_cents: int = 500000,
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-12-31",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "club_id": club_id,
        "coverage_tier": coverage_tier,
        "parts_inclusion": parts_inclusion,
        "pm_visits_per_year": pm_visits_per_year,
        "annual_base_cents": annual_base_cents,
        "initial_parts_allowance_cents": initial_parts_allowance_cents,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
    }
    payload.update(overrides)
    return payload


def suspend_payload(reason: str = "NON_PAYMENT", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def allowance_adjustment_payload(
    amount_cents: int, memo: str = "Goodwill top-up", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents, "memo": memo}
    payload.update(overrides)
    return payload


def credit_reconciliation_payload(
    period_key: str, expected_contract_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_key": period_key,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def renewal_quote_payload(
    expected_contract_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_contract_version": expected_contract_version
    }
    payload.update(overrides)
    return payload


def quote_decline_payload(reason: str = "BUDGET", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Technicians ──────────────────────────────────────────────────────────────


def technician_payload(
    full_name: str = "Dana Reyes",
    region_code: str = "NW",
    skill_categories: Optional[List[str]] = None,
    is_safety_inspector: Optional[bool] = None,
    max_committed_minutes: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "region_code": region_code,
        "skill_categories": list(skill_categories or ["TREADMILL"]),
    }
    if is_safety_inspector is not None:
        payload["is_safety_inspector"] = is_safety_inspector
    if max_committed_minutes is not None:
        payload["max_committed_minutes"] = max_committed_minutes
    payload.update(overrides)
    return payload


def duty_status_payload(duty_status: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"duty_status": duty_status}
    payload.update(overrides)
    return payload


def release_payload(reason: str = "ROUTE_REBALANCE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Preventive visits ────────────────────────────────────────────────────────


def preventive_visit_payload(
    contract_id: str,
    equipment_id: str,
    window_start: str,
    window_end: str,
    technician_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "equipment_id": equipment_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    if technician_id is not None:
        payload["technician_id"] = technician_id
    payload.update(overrides)
    return payload


def checklist_result_payload(
    item_code: str,
    result: str = "PASS",
    consumable_replaced: Optional[bool] = None,
    note: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"item_code": item_code, "result": result}
    if consumable_replaced is not None:
        payload["consumable_replaced"] = consumable_replaced
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def visit_cancel_payload(
    reason: str = "CLUB_REQUEST", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def safety_doc_submit_payload(
    inspection_summary: str = "Belt tension and emergency stop verified.",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"inspection_summary": inspection_summary}
    payload.update(overrides)
    return payload


def safety_doc_reject_payload(
    rejection_reason: str = "PHOTOS_MISSING", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ─── Service calls ────────────────────────────────────────────────────────────


def service_call_payload(
    contract_id: str,
    equipment_id: str,
    severity: str = "MAJOR",
    symptom_code: str = "BELT_NOISE",
    injury_reported: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "equipment_id": equipment_id,
        "severity": severity,
        "symptom_code": symptom_code,
    }
    if injury_reported is not None:
        payload["injury_reported"] = injury_reported
    payload.update(overrides)
    return payload


def dispatch_payload(
    start_at: str, technician_id: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"start_at": start_at}
    if technician_id is not None:
        payload["technician_id"] = technician_id
    payload.update(overrides)
    return payload


def parts_hold_payload(
    part_id: str, qty: int = 1, source: str = "NEW", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"part_id": part_id, "qty": qty, "source": source}
    payload.update(overrides)
    return payload


def resolve_payload(
    resolution_code: str = "BELT_TENSIONED",
    safety_clearance_technician_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution_code": resolution_code}
    if safety_clearance_technician_id is not None:
        payload["safety_clearance_technician_id"] = safety_clearance_technician_id
    payload.update(overrides)
    return payload


def call_cancel_payload(reason: str = "CLUB_WITHDREW", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Spare parts ──────────────────────────────────────────────────────────────


def part_payload(
    model_id: str,
    part_number: str = "BELT-STD",
    category: str = "WEAR",
    unit_price_cents: int = 8000,
    is_critical_spare: Optional[bool] = None,
    initial_on_hand_qty: Optional[int] = None,
    initial_refurb_qty: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model_id": model_id,
        "part_number": part_number,
        "category": category,
        "unit_price_cents": unit_price_cents,
    }
    if is_critical_spare is not None:
        payload["is_critical_spare"] = is_critical_spare
    if initial_on_hand_qty is not None:
        payload["initial_on_hand_qty"] = initial_on_hand_qty
    if initial_refurb_qty is not None:
        payload["initial_refurb_qty"] = initial_refurb_qty
    payload.update(overrides)
    return payload


def inventory_adjustment_payload(
    new_qty_delta: int = 0, refurb_qty_delta: int = 0, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_qty_delta": new_qty_delta,
        "refurb_qty_delta": refurb_qty_delta,
    }
    payload.update(overrides)
    return payload


def part_order_cancel_payload(
    reason: str = "WRONG_PART", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ─── Downtime events ──────────────────────────────────────────────────────────


def waive_payload(waive_reason: str = "GOODWILL", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"waive_reason": waive_reason}
    payload.update(overrides)
    return payload
