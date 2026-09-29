"""Request-payload builders.

Each factory returns a valid body for one endpoint with the domain's standard
values pre-filled, and accepts keyword overrides so a test can vary exactly the
one field it is about. Passing ``None`` explicitly for an optional field removes
it from the body, which is how tests probe "field absent" behaviour.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_UNSET = object()

# A justification comfortably past the 40-character floor.
VALID_JUSTIFICATION = (
    "Casegoods vendor confirms a twelve week backorder on the guest room package, "
    "so the corridor refresh cannot finish on schedule."
)

# A justification that is too short once trimmed.
SHORT_JUSTIFICATION = "   Vendor is late.   "


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not _UNSET}


def franchisee_payload(
    legal_name: str = "Harborline Lodging LLC",
    contact_email: str = "ops@harborline.example",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"legal_name": legal_name, "contact_email": contact_email}
    payload.update(overrides)
    return payload


def property_payload(
    franchisee_id: str,
    name: str = "Harborline Midtown",
    room_count: int = 200,
    adr_baseline_cents: int = 18000,
    occupancy_baseline_pct: float = 0.70,
    reserve_balance_cents: int = 50000000,
    minimum_retention_cents: int = 5000000,
    brand_code: str = "HRB",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "franchisee_id": franchisee_id,
        "brand_code": brand_code,
        "name": name,
        "room_count": room_count,
        "adr_baseline_cents": adr_baseline_cents,
        "occupancy_baseline_pct": occupancy_baseline_pct,
        "reserve_balance_cents": reserve_balance_cents,
        "minimum_retention_cents": minimum_retention_cents,
    }
    payload.update(overrides)
    return payload


def plan_payload(
    property_id: str,
    trigger_type: str = "POST_INSPECTION",
    standards_edition: str = "2026.1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "property_id": property_id,
        "trigger_type": trigger_type,
        "standards_edition": standards_edition,
    }
    payload.update(overrides)
    return payload


def item_payload(
    plan_id: str,
    category: str = "GUEST_FACING",
    standards_reference: str = "GF-4.2.1",
    brand_estimated_cost_cents: int = 1000000,
    room_impacting: bool = False,
    rooms_affected_count: int = 0,
    predecessor_item_id: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "plan_id": plan_id,
            "category": category,
            "standards_reference": standards_reference,
            "brand_estimated_cost_cents": brand_estimated_cost_cents,
            "room_impacting": room_impacting,
            "rooms_affected_count": rooms_affected_count,
            "predecessor_item_id": predecessor_item_id,
        }
    )
    payload.update(overrides)
    return payload


def item_revision_payload(expected_plan_version: int, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_plan_version": expected_plan_version}
    payload.update(fields)
    return payload


def capital_budget_payload(
    plan_id: str,
    total_authorized_cents: int,
    expected_plan_version: int,
    contingency_pct: float = 0.10,
    financing_source: str = "OWNER_EQUITY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "plan_id": plan_id,
        "total_authorized_cents": total_authorized_cents,
        "contingency_pct": contingency_pct,
        "financing_source": financing_source,
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


def reserve_draw_payload(
    property_id: str,
    capital_budget_id: str,
    purpose_item_id: str,
    amount_cents: int,
    expected_property_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "property_id": property_id,
        "capital_budget_id": capital_budget_id,
        "purpose_item_id": purpose_item_id,
        "amount_cents": amount_cents,
        "expected_property_version": expected_property_version,
    }
    payload.update(overrides)
    return payload


def reserve_contribution_payload(amount_cents: int = 1000000, **overrides: Any) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def renovation_phase_payload(
    plan_id: str,
    phase_number: int = 1,
    start_date: str = "2026-09-01",
    end_date: str = "2026-09-10",
    rooms_out_of_service: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "plan_id": plan_id,
        "phase_number": phase_number,
        "start_date": start_date,
        "end_date": end_date,
        "rooms_out_of_service": rooms_out_of_service,
    }
    payload.update(overrides)
    return payload


def contractor_payload(
    name: str = "Grantham General Contracting",
    trade: str = "GENERAL",
    brand_approved: bool = False,
    max_concurrent_bookings: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "trade": trade,
        "brand_approved": brand_approved,
        "max_concurrent_bookings": max_concurrent_bookings,
    }
    payload.update(overrides)
    return payload


def contractor_booking_payload(
    contractor_id: str,
    phase_id: str,
    start_datetime: str = "2026-09-02T08:00:00Z",
    end_datetime: str = "2026-09-02T16:00:00Z",
    crew_size: int = 4,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "contractor_id": contractor_id,
        "phase_id": phase_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "crew_size": crew_size,
    }
    payload.update(overrides)
    return payload


def extension_request_payload(
    item_id: str,
    requested_days: int = 45,
    business_justification: str = VALID_JUSTIFICATION,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "item_id": item_id,
        "requested_days": requested_days,
        "business_justification": business_justification,
    }
    payload.update(overrides)
    return payload


def extension_decision_payload(
    decision: str,
    decision_note: str = "Recorded by the brand compliance desk.",
    granted_days: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "decision": decision,
            "decision_note": decision_note,
            "granted_days": granted_days,
        }
    )
    payload.update(overrides)
    return payload


def extension_resubmit_payload(
    requested_days: int = 45,
    business_justification: str = VALID_JUSTIFICATION,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "requested_days": requested_days,
        "business_justification": business_justification,
    }
    payload.update(overrides)
    return payload


def inspection_payload(
    plan_id: str,
    inspector_user_id: str,
    scheduled_date: str = "2026-08-05",
    inspection_type: str = "COMPLETION",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "plan_id": plan_id,
        "inspection_type": inspection_type,
        "inspector_user_id": inspector_user_id,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def punch_list_item_payload(
    inspection_id: str,
    pip_item_id: str,
    severity: str = "MAJOR",
    defect_note: str = "Corridor sprinkler escutcheon plates missing on the renovated floor.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "inspection_id": inspection_id,
        "pip_item_id": pip_item_id,
        "defect_note": defect_note,
        "severity": severity,
    }
    payload.update(overrides)
    return payload


def punch_verify_payload(
    outcome: str,
    verification_note: Any = "Verified on the follow-up walk.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact({"outcome": outcome, "verification_note": verification_note})
    payload.update(overrides)
    return payload


def dispute_payload(
    plan_id: str,
    item_id: str,
    claimed_cost_cents: int,
    dispute_basis: str = "COST_ESTIMATE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "plan_id": plan_id,
        "item_id": item_id,
        "dispute_basis": dispute_basis,
        "claimed_cost_cents": claimed_cost_cents,
    }
    payload.update(overrides)
    return payload


def dispute_resolution_payload(
    resolution: str,
    revised_cost_cents: Any = _UNSET,
    panel_decision_note: Optional[str] = "Determined by the standards panel.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _compact(
        {
            "resolution": resolution,
            "revised_cost_cents": revised_cost_cents,
            "panel_decision_note": panel_decision_note,
        }
    )
    payload.update(overrides)
    return payload


def default_notice_payload(
    plan_id: str, cure_period_days: int = 30, **overrides: Any
) -> Dict[str, Any]:
    payload = {"plan_id": plan_id, "cure_period_days": cure_period_days}
    payload.update(overrides)
    return payload


def draw_decision_payload(decision: str = "CONSENT", **overrides: Any) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def property_patch_payload(**fields: Any) -> Dict[str, Any]:
    """Only the supplied baselines are corrected; omitted ones are left untouched."""
    return dict(fields)


__all__ = [
    "VALID_JUSTIFICATION",
    "SHORT_JUSTIFICATION",
    "franchisee_payload",
    "property_payload",
    "plan_payload",
    "item_payload",
    "item_revision_payload",
    "capital_budget_payload",
    "reserve_draw_payload",
    "reserve_contribution_payload",
    "renovation_phase_payload",
    "contractor_payload",
    "contractor_booking_payload",
    "extension_request_payload",
    "extension_decision_payload",
    "extension_resubmit_payload",
    "inspection_payload",
    "punch_list_item_payload",
    "punch_verify_payload",
    "dispute_payload",
    "dispute_resolution_payload",
    "default_notice_payload",
    "draw_decision_payload",
    "property_patch_payload",
]
