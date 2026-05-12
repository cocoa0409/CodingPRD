"""Payload factories — one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input (source: input)
for the relevant endpoint. Tests override via kwargs.

Field names mirror PRD prose exactly — no abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-name helpers
# ---------------------------------------------------------------------------
def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


def unique_license() -> str:
    return f"LIC-{unique_suffix().upper()}"


def unique_email(prefix: str = "tenant") -> str:
    return f"{prefix}-{unique_suffix()}@example.com"


def unique_building_name() -> str:
    return f"Test Building {unique_suffix()}"


def unique_unit_code(prefix: str = "U") -> str:
    return f"{prefix}-{unique_suffix().upper()}"


def unique_legal_name(prefix: str = "Tenant Co") -> str:
    return f"{prefix} {unique_suffix()}"


# ---------------------------------------------------------------------------
# Building  POST /buildings  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_building_payload(
    *,
    name: Optional[str] = None,
    address: Optional[str] = None,
    floors_count: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'Creating a Building requires a human-readable name, a
    postal address, and a floors_count integer ... at least 1.'"""
    payload: Dict[str, Any] = {
        "name": name or unique_building_name(),
        "address": address or f"{unique_suffix()} Main Street",
        "floors_count": floors_count,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Unit  POST /buildings/:building_id/units  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_unit_payload(
    *,
    floor: int = 1,
    code: Optional[str] = None,
    area_sqm: float = 100.0,
    orientation: str = "N",
    usage_type: str = "OFFICE",
    rent_reference_per_sqm: float = 100.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: a unit declares floor (1..floors_count), code (unique per
    building), area_sqm (> 0, 2 decimal places), orientation, usage_type,
    and rent_reference_per_sqm (> 0, 2 decimal places)."""
    payload: Dict[str, Any] = {
        "floor": floor,
        "code": code or unique_unit_code(),
        "area_sqm": area_sqm,
        "orientation": orientation,
        "usage_type": usage_type,
        "rent_reference_per_sqm": rent_reference_per_sqm,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Unit reservation
# ---------------------------------------------------------------------------
def reserve_unit_payload(*, tenant_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'a LeasingAgent may attach a soft reservation by supplying
    the tenant_id to the reserve action on a unit.'"""
    payload: Dict[str, Any] = {"tenant_id": tenant_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Renovation start  POST /buildings/:building_id/units/:unit_id/start-renovation
# ---------------------------------------------------------------------------
def start_renovation_payload(
    *,
    renovation_start_date: str,
    renovation_end_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A property manager opens a renovation interval by
    supplying a renovation_end_date; the server stamps the unit's
    renovation_start_date and renovation_end_date from the request.'"""
    payload: Dict[str, Any] = {
        "renovation_start_date": renovation_start_date,
        "renovation_end_date": renovation_end_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Unit split  POST /buildings/:building_id/units/:unit_id/split
# ---------------------------------------------------------------------------
def split_unit_payload(*, child_units: List[Dict[str, Any]],
                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Splitting a VACANT unit retires it and creates one new
    Unit per child specification.'"""
    payload: Dict[str, Any] = {"child_units": child_units}
    payload.update(overrides)
    return payload


def make_child_unit_spec(
    *,
    floor: int = 1,
    code: Optional[str] = None,
    area_sqm: float = 50.0,
    orientation: str = "N",
    usage_type: str = "OFFICE",
    rent_reference_per_sqm: float = 100.0,
    **overrides: Any,
) -> Dict[str, Any]:
    spec: Dict[str, Any] = {
        "floor": floor,
        "code": code or unique_unit_code("C"),
        "area_sqm": area_sqm,
        "orientation": orientation,
        "usage_type": usage_type,
        "rent_reference_per_sqm": rent_reference_per_sqm,
    }
    spec.update(overrides)
    return spec


# ---------------------------------------------------------------------------
# Unit merge  POST /buildings/:building_id/units/merge
# ---------------------------------------------------------------------------
def merge_units_payload(*, source_unit_ids: List[str],
                        merged_code: Optional[str] = None,
                        **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'The request carries a source_unit_ids array listing the
    units to merge and a merged_code string for the resulting unit.'"""
    payload: Dict[str, Any] = {
        "source_unit_ids": source_unit_ids,
        "merged_code": merged_code or unique_unit_code("M"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tenant  POST /tenants  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_tenant_payload(
    *,
    legal_name: Optional[str] = None,
    business_license_no: Optional[str] = None,
    license_expires_on: str = "2099-12-01T00:00:00.000Z",
    contact_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A LeasingAgent records prospective tenants by supplying
    their legal_name, their business_license_no ... their
    license_expires_on date, and a contact_email.'"""
    payload: Dict[str, Any] = {
        "legal_name": legal_name or unique_legal_name(),
        "business_license_no": business_license_no or unique_license(),
        "license_expires_on": license_expires_on,
        "contact_email": contact_email or unique_email(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lease  POST /leases  (PRD §3.3)
# ---------------------------------------------------------------------------
def create_lease_payload(
    *,
    unit_id: str,
    tenant_id: str,
    start_date: str,
    end_date: str,
    base_monthly_rent_cents: int = 100000,
    escalation_mode: str = "NONE",
    escalation_pct_bps: Any = "__OMIT__",
    stepped_schedule: Any = "__OMIT__",
    rent_free_days: Any = "__OMIT__",
    deposit_months: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: lease draft inputs — unit_id, tenant_id, start_date,
    end_date (half-open [start_date, end_date)), base_monthly_rent_cents,
    escalation_mode, escalation_pct_bps, optional stepped_schedule,
    optional rent_free_days (defaulting to zero), deposit_months."""
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "tenant_id": tenant_id,
        "start_date": start_date,
        "end_date": end_date,
        "base_monthly_rent_cents": base_monthly_rent_cents,
        "escalation_mode": escalation_mode,
        "deposit_months": deposit_months,
    }
    if escalation_pct_bps != "__OMIT__":
        payload["escalation_pct_bps"] = escalation_pct_bps
    if stepped_schedule != "__OMIT__":
        payload["stepped_schedule"] = stepped_schedule
    if rent_free_days != "__OMIT__":
        payload["rent_free_days"] = rent_free_days
    payload.update(overrides)
    return payload


def make_stepped_entry(*, effective_from: str,
                       monthly_rent_cents: int) -> Dict[str, Any]:
    """PRD §3.3: '[an] optional stepped_schedule array of objects each
    carrying an effective_from date and a monthly_rent_cents integer'."""
    return {
        "effective_from": effective_from,
        "monthly_rent_cents": monthly_rent_cents,
    }


# ---------------------------------------------------------------------------
# Lease amendment  POST /leases/:lease_id/amend
# ---------------------------------------------------------------------------
def amend_lease_payload(
    *,
    effective_from: str,
    new_base_monthly_rent_cents: Any = "__OMIT__",
    new_end_date: Any = "__OMIT__",
    new_rent_free_days: Any = "__OMIT__",
    new_deposit_months: Any = "__OMIT__",
    new_stepped_schedule: Any = "__OMIT__",
    new_escalation_mode: Any = "__OMIT__",
    new_escalation_pct_bps: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'Amendment payloads carry an effective_from date ...
    together with any combination of optional changes:
    new_base_monthly_rent_cents, new_end_date, new_rent_free_days,
    new_deposit_months, new_stepped_schedule, new_escalation_mode, and
    new_escalation_pct_bps.'"""
    payload: Dict[str, Any] = {"effective_from": effective_from}
    if new_base_monthly_rent_cents != "__OMIT__":
        payload["new_base_monthly_rent_cents"] = new_base_monthly_rent_cents
    if new_end_date != "__OMIT__":
        payload["new_end_date"] = new_end_date
    if new_rent_free_days != "__OMIT__":
        payload["new_rent_free_days"] = new_rent_free_days
    if new_deposit_months != "__OMIT__":
        payload["new_deposit_months"] = new_deposit_months
    if new_stepped_schedule != "__OMIT__":
        payload["new_stepped_schedule"] = new_stepped_schedule
    if new_escalation_mode != "__OMIT__":
        payload["new_escalation_mode"] = new_escalation_mode
    if new_escalation_pct_bps != "__OMIT__":
        payload["new_escalation_pct_bps"] = new_escalation_pct_bps
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lease renew  POST /leases/:lease_id/renew
# ---------------------------------------------------------------------------
def renew_lease_payload(
    *,
    new_end_date: str,
    new_base_monthly_rent_cents: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'The renewal payload carries a new_end_date and an
    optional new_base_monthly_rent_cents.'"""
    payload: Dict[str, Any] = {"new_end_date": new_end_date}
    if new_base_monthly_rent_cents != "__OMIT__":
        payload["new_base_monthly_rent_cents"] = new_base_monthly_rent_cents
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Move-out request  POST /leases/:lease_id/move-out-request
# ---------------------------------------------------------------------------
def move_out_request_payload(*, target_move_out_date: str,
                             **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'A tenant initiates a move-out from an ACTIVE lease by
    supplying a target_move_out_date.'"""
    payload: Dict[str, Any] = {"target_move_out_date": target_move_out_date}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inspection / restoration
# ---------------------------------------------------------------------------
def record_inspection_payload(
    *,
    inspection_findings: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'A property manager records the unit inspection on the
    request, supplying inspection_findings — an array of objects each
    carrying an item description, a severity of MINOR or MAJOR, and an
    estimated_cost_cents integer.'"""
    payload: Dict[str, Any] = {
        "inspection_findings": (
            inspection_findings if inspection_findings is not None else []
        ),
    }
    payload.update(overrides)
    return payload


def make_inspection_finding(*, item: str = "Wall scuff",
                            severity: str = "MINOR",
                            estimated_cost_cents: int = 500,
                            **overrides: Any) -> Dict[str, Any]:
    finding: Dict[str, Any] = {
        "item": item,
        "severity": severity,
        "estimated_cost_cents": estimated_cost_cents,
    }
    finding.update(overrides)
    return finding


def confirm_restoration_payload(*, restoration_done: bool = True,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'The property manager then confirms restoration by
    submitting a restoration_done boolean.'"""
    payload: Dict[str, Any] = {"restoration_done": restoration_done}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deposit top-up  POST /deposits/:deposit_id/top-up
# ---------------------------------------------------------------------------
def top_up_payload(*, amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'A tenant tops up their deposit by supplying an
    amount_cents integer.'"""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Propose deductions  POST /deposits/:deposit_id/propose-deductions
# ---------------------------------------------------------------------------
def propose_deductions_payload(
    *,
    deduction_items: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.8: 'a PropertyManager proposes deductions against the
    deposit by submitting a deduction_items array, where each element
    carries a kind (OVERDUE_RENT, DAMAGE, or CLEANING), an amount_cents
    integer, and an optional note string.'"""
    payload: Dict[str, Any] = {
        "deduction_items": (
            deduction_items if deduction_items is not None else []
        ),
    }
    payload.update(overrides)
    return payload


def make_deduction_item(*, kind: str = "CLEANING",
                        amount_cents: int = 1000,
                        note: Optional[str] = None,
                        **overrides: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {"kind": kind, "amount_cents": amount_cents}
    if note is not None:
        item["note"] = note
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# Fee bills  POST /fee-bills
# ---------------------------------------------------------------------------
def create_property_fee_bill_payload(
    *,
    lease_id: str,
    period_start: str,
    period_end: str,
    property_fee_mode: str,
    rate_per_sqm_per_month_cents: Any = "__OMIT__",
    fixed_rate_cents_per_month: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: PROPERTY_FEE bill payload — lease_id, bill_kind,
    period_start, period_end, property_fee_mode (BY_AREA | FIXED_RATE),
    and the matching rate field."""
    payload: Dict[str, Any] = {
        "lease_id": lease_id,
        "bill_kind": "PROPERTY_FEE",
        "period_start": period_start,
        "period_end": period_end,
        "property_fee_mode": property_fee_mode,
    }
    if rate_per_sqm_per_month_cents != "__OMIT__":
        payload["rate_per_sqm_per_month_cents"] = rate_per_sqm_per_month_cents
    if fixed_rate_cents_per_month != "__OMIT__":
        payload["fixed_rate_cents_per_month"] = fixed_rate_cents_per_month
    payload.update(overrides)
    return payload


def create_energy_fee_bill_payload(
    *,
    lease_id: str,
    period_start: str,
    period_end: str,
    energy_mode: str,
    tariff_per_kwh_cents: int,
    sub_meter_kwh: Any = "__OMIT__",
    shared_total_kwh: Any = "__OMIT__",
    shared_meter_group_unit_ids: Any = "__OMIT__",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: ENERGY_FEE bill payload — energy_mode (SUB_METER |
    ALLOCATED), tariff_per_kwh_cents (> 0), and the matching inputs."""
    payload: Dict[str, Any] = {
        "lease_id": lease_id,
        "bill_kind": "ENERGY_FEE",
        "period_start": period_start,
        "period_end": period_end,
        "energy_mode": energy_mode,
        "tariff_per_kwh_cents": tariff_per_kwh_cents,
    }
    if sub_meter_kwh != "__OMIT__":
        payload["sub_meter_kwh"] = sub_meter_kwh
    if shared_total_kwh != "__OMIT__":
        payload["shared_total_kwh"] = shared_total_kwh
    if shared_meter_group_unit_ids != "__OMIT__":
        payload["shared_meter_group_unit_ids"] = shared_meter_group_unit_ids
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Dispute / resolve dispute
# ---------------------------------------------------------------------------
def dispute_fee_bill_payload(*, dispute_reason: str = "Disputed charge",
                             **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'A tenant disputing a bill moves its status from ISSUED
    to DISPUTED and stores the supplied dispute_reason on the bill.'"""
    payload: Dict[str, Any] = {"dispute_reason": dispute_reason}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(*, resolution_keeps_bill: bool,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'A finance officer resolves a dispute by submitting a
    resolution_keeps_bill boolean.'"""
    payload: Dict[str, Any] = {"resolution_keeps_bill": resolution_keeps_bill}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance  POST /_clock/advance
# ---------------------------------------------------------------------------
def clock_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'advances the logical server clock to a supplied to
    instant.'"""
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix", "unique_license", "unique_email",
    "unique_building_name", "unique_unit_code", "unique_legal_name",
    "create_building_payload",
    "create_unit_payload", "reserve_unit_payload",
    "start_renovation_payload",
    "split_unit_payload", "make_child_unit_spec",
    "merge_units_payload",
    "create_tenant_payload",
    "create_lease_payload", "make_stepped_entry",
    "amend_lease_payload", "renew_lease_payload",
    "move_out_request_payload",
    "record_inspection_payload", "make_inspection_finding",
    "confirm_restoration_payload",
    "top_up_payload",
    "propose_deductions_payload", "make_deduction_item",
    "create_property_fee_bill_payload",
    "create_energy_fee_bill_payload",
    "dispute_fee_bill_payload", "resolve_dispute_payload",
    "clock_payload",
]
