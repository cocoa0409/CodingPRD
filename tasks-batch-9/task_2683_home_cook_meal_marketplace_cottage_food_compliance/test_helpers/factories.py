"""Payload factories, one per creating or mutating endpoint.

Every monetary field is emitted as a JSON number of integer cents, never as a
string: "All money in this system is expressed in integer cents" (PRD 2.8).
Every factory takes `**overrides` last so a test can bend exactly one field.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import STANDARD_LABEL_FIELDS

_seq = itertools.count(1)


def next_suffix() -> int:
    """Monotonic counter for unique emails, zone codes and certificate numbers."""
    return next(_seq)


# --------------------------------------------------------------- state policy
def state_policy_payload(
    state_code: str = "CA",
    cottage_food_annual_cap_cents: int = 5_000_000,
    allowed_kitchen_types: Optional[List[str]] = None,
    tcs_requires_commercial_kitchen: bool = True,
    max_shelf_life_days_non_refrigerated: int = 14,
    label_required_fields: Optional[List[str]] = None,
    cert_validity_max_days: int = 1825,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "cottage_food_annual_cap_cents": int(cottage_food_annual_cap_cents),
        "allowed_kitchen_types": list(
            allowed_kitchen_types
            if allowed_kitchen_types is not None
            else ["HOME_COTTAGE", "HOME_INSPECTED", "COMMERCIAL_SHARED"]
        ),
        "tcs_requires_commercial_kitchen": tcs_requires_commercial_kitchen,
        "max_shelf_life_days_non_refrigerated": max_shelf_life_days_non_refrigerated,
        "label_required_fields": list(
            label_required_fields if label_required_fields is not None else STANDARD_LABEL_FIELDS
        ),
        "cert_validity_max_days": cert_validity_max_days,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------- cook
def cook_payload(
    legal_name: str = "Ana Ruiz",
    email: Optional[str] = None,
    state_code: str = "CA",
    claimed_kitchen_type: str = "HOME_INSPECTED",
    weekly_capacity_meals: Optional[int] = 40,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "email": email if email is not None else f"cook{next_suffix()}@example.com",
        "state_code": state_code,
        "claimed_kitchen_type": claimed_kitchen_type,
    }
    if weekly_capacity_meals is not None:
        payload["weekly_capacity_meals"] = weekly_capacity_meals
    payload.update(overrides)
    return payload


# ---------------------------------------------------- onboarding documents
def food_handler_cert_payload(
    cook_id: str,
    expected_cook_version: int,
    certificate_number: Optional[str] = None,
    issuing_authority: str = "CA DPH",
    issued_on: str = "2026-04-01",
    expires_on: str = "2028-04-01",
    **overrides: Any,
) -> Dict[str, Any]:
    """FOOD_HANDLER_CERT requires certificate_number, issuing_authority,
    issued_on and expires_on, and forbids kitchen_type_claimed and
    inspection_date (PRD 3.1)."""
    payload: Dict[str, Any] = {
        "cook_id": cook_id,
        "doc_type": "FOOD_HANDLER_CERT",
        "expected_cook_version": expected_cook_version,
        "certificate_number": (
            certificate_number if certificate_number is not None else f"FH-{next_suffix():04d}"
        ),
        "issuing_authority": issuing_authority,
        "issued_on": issued_on,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def kitchen_inspection_payload(
    cook_id: str,
    expected_cook_version: int,
    kitchen_type_claimed: str = "HOME_INSPECTED",
    inspection_date: str = "2026-07-01",
    **overrides: Any,
) -> Dict[str, Any]:
    """KITCHEN_INSPECTION requires kitchen_type_claimed and inspection_date and
    forbids the four certificate fields (PRD 3.1)."""
    payload: Dict[str, Any] = {
        "cook_id": cook_id,
        "doc_type": "KITCHEN_INSPECTION",
        "expected_cook_version": expected_cook_version,
        "kitchen_type_claimed": kitchen_type_claimed,
        "inspection_date": inspection_date,
    }
    payload.update(overrides)
    return payload


def document_review_payload(decision: str, note: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def onboarding_decision_payload(
    decision: str, note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def standing_action_payload(action: str, reason: str, **overrides: Any) -> Dict[str, Any]:
    """Every standing action carries an `action` and a mandatory `reason` (PRD 3.7)."""
    payload: Dict[str, Any] = {"action": action, "reason": reason}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------- menu item
def menu_item_payload(
    cook_id: str,
    name: str = "Tamale Dozen",
    food_category: str = "NON_TCS",
    allergens: Optional[List[str]] = None,
    allergen_free_attested: bool = False,
    shelf_life_days: int = 6,
    requires_refrigeration: bool = False,
    handoff_mode: str = "BATCH_COOK_AND_CHILL",
    unit_price_cents: int = 1200,
    label_fields: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cook_id": cook_id,
        "name": name,
        "food_category": food_category,
        "allergens": list(allergens if allergens is not None else ["MILK"]),
        "allergen_free_attested": allergen_free_attested,
        "shelf_life_days": shelf_life_days,
        "requires_refrigeration": requires_refrigeration,
        "handoff_mode": handoff_mode,
        "unit_price_cents": int(unit_price_cents),
        "label_fields": list(label_fields if label_fields is not None else STANDARD_LABEL_FIELDS),
    }
    payload.update(overrides)
    return payload


def menu_item_review_payload(
    decision: str,
    allergen_review_notes: Optional[str] = None,
    revision_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """APPROVE requires a non-empty `allergen_review_notes` (PRD 3.2)."""
    payload: Dict[str, Any] = {"decision": decision}
    if allergen_review_notes is not None:
        payload["allergen_review_notes"] = allergen_review_notes
    if revision_note is not None:
        payload["revision_note"] = revision_note
    payload.update(overrides)
    return payload


def approve_menu_item_payload(
    allergen_review_notes: str = "allergens reviewed and declared", **overrides: Any
) -> Dict[str, Any]:
    return menu_item_review_payload("APPROVE", allergen_review_notes=allergen_review_notes, **overrides)


# ---------------------------------------------------------- production window
def production_window_payload(
    cook_id: str,
    week_start_date: str = "2026-08-03",
    order_cutoff_at: str = "2026-08-05T00:00:00Z",
    handoff_start_at: str = "2026-08-08T16:00:00Z",
    handoff_end_at: str = "2026-08-08T18:00:00Z",
    capacity_meals: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cook_id": cook_id,
        "week_start_date": week_start_date,
        "order_cutoff_at": order_cutoff_at,
        "handoff_start_at": handoff_start_at,
        "handoff_end_at": handoff_end_at,
        "capacity_meals": capacity_meals,
    }
    payload.update(overrides)
    return payload


def window_advance_payload(
    to_status: str, cancelled_reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    if cancelled_reason is not None:
        payload["cancelled_reason"] = cancelled_reason
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ delivery zone
def delivery_zone_payload(
    state_policy_id: str,
    zone_code: Optional[str] = None,
    state_code: str = "CA",
    service_mode: str = "DOOR_DELIVERY",
    postal_codes: Optional[List[str]] = None,
    max_cold_chain_minutes: int = 180,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_policy_id": state_policy_id,
        "zone_code": zone_code if zone_code is not None else f"ZONE-{next_suffix():04d}",
        "state_code": state_code,
        "service_mode": service_mode,
        "postal_codes": list(postal_codes if postal_codes is not None else ["94110"]),
        "max_cold_chain_minutes": max_cold_chain_minutes,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------- pickup hub
def pickup_hub_payload(
    delivery_zone_id: str,
    name: str = "Central Hub",
    address: str = "1 Market St",
    slot_capacity_orders: int = 5,
    hub_window_start_at: str = "2026-08-08T15:00:00Z",
    hub_window_end_at: str = "2026-08-08T21:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delivery_zone_id": delivery_zone_id,
        "name": name,
        "address": address,
        "slot_capacity_orders": slot_capacity_orders,
        "hub_window_start_at": hub_window_start_at,
        "hub_window_end_at": hub_window_end_at,
    }
    payload.update(overrides)
    return payload


def consolidate_payload(production_window_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"production_window_id": production_window_id}
    payload.update(overrides)
    return payload


# -------------------------------------------------------------------- order
def order_payload(
    menu_item_id: str,
    production_window_id: str,
    delivery_zone_id: str,
    quantity: int = 1,
    diner_contact_email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "menu_item_id": menu_item_id,
        "production_window_id": production_window_id,
        "delivery_zone_id": delivery_zone_id,
        "quantity": quantity,
        "diner_contact_email": (
            diner_contact_email
            if diner_contact_email is not None
            else f"diner{next_suffix()}@example.com"
        ),
    }
    payload.update(overrides)
    return payload


def order_advance_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


def order_cancel_payload(reason: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------- safety incident
def safety_incident_payload(
    cook_id: str,
    subject_type: str = "COOK",
    category: str = "LABEL_MISSING",
    severity: str = "MODERATE",
    description: str = "package shipped without the cottage-food disclaimer",
    occurred_at: str = "2026-07-30T12:00:00Z",
    order_id: Optional[str] = None,
    menu_item_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`COOK` requires neither order_id nor menu_item_id; `MENU_ITEM` requires a
    menu_item_id and forbids order_id; `ORDER` requires an order_id and forbids
    menu_item_id (PRD 3.7)."""
    payload: Dict[str, Any] = {
        "cook_id": cook_id,
        "subject_type": subject_type,
        "category": category,
        "severity": severity,
        "description": description,
        "occurred_at": occurred_at,
    }
    if order_id is not None:
        payload["order_id"] = order_id
    if menu_item_id is not None:
        payload["menu_item_id"] = menu_item_id
    payload.update(overrides)
    return payload


def triage_payload(
    decision: str, severity_override: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if severity_override is not None:
        payload["severity_override"] = severity_override
    payload.update(overrides)
    return payload


def adjudicate_payload(
    decision: str, resolution_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    payload.update(overrides)
    return payload


# --------------------------------------------------------- payout statement
def payout_statement_payload(
    cook_id: str,
    production_window_id: str,
    expected_production_window_version: int,
    basis: str = "ACCRUAL_WINDOW",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cook_id": cook_id,
        "production_window_id": production_window_id,
        "basis": basis,
        "expected_production_window_version": expected_production_window_version,
    }
    payload.update(overrides)
    return payload


def statement_advance_payload(
    to_status: str, note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- refund event
def refund_event_payload(
    order_id: str,
    reason: str = "QUALITY",
    fault_party: str = "COOK",
    refund_amount_cents: int = 100,
    settle_immediately: Optional[bool] = None,
    safety_incident_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "reason": reason,
        "fault_party": fault_party,
        "refund_amount_cents": int(refund_amount_cents),
    }
    if settle_immediately is not None:
        payload["settle_immediately"] = settle_immediately
    if safety_incident_id is not None:
        payload["safety_incident_id"] = safety_incident_id
    payload.update(overrides)
    return payload
