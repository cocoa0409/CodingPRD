"""Payload factories — one per entity, input fields only.

Field names match PRD verbatim. Each factory accepts **overrides so
individual tests can pin specific values (boundary, threshold, edge case).
"""
from __future__ import annotations
import time
import uuid
from typing import Any, Dict, List, Optional

from .test_users import PLANNER_ID, AUDITOR_ID


# ---------------------------------------------------------------------------
# Unique-id helpers
# ---------------------------------------------------------------------------
def unique_suffix(prefix: str = "x") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_couple_name() -> str:
    return f"Couple-{uuid.uuid4().hex[:8]}"


def unique_vendor_name(prefix: str = "Vendor") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_template_name(prefix: str = "Template") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Time helpers (Unix seconds; the PRD measures time in Unix-second integers)
# ---------------------------------------------------------------------------
def now_seconds() -> int:
    return int(time.time())


def far_future_seconds(offset_days: int = 365) -> int:
    return now_seconds() + offset_days * 86400


# ---------------------------------------------------------------------------
# WeddingProject (PRD §3.1)
# ---------------------------------------------------------------------------
def create_project_payload(
    *,
    couple_name: Optional[str] = None,
    ceremony_date: Optional[int] = None,
    style: str = "MODERN",
    scale: str = "MEDIUM",
    planner_user_id: str = PLANNER_ID,
    auditor_user_id: str = AUDITOR_ID,
    total_budget_cents: int = 5_000_000,
    template_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1 lists couple_name, ceremony_date, style, scale, planner_user_id,
    auditor_user_id, total_budget_cents, and optional template_id as the
    project-creation inputs.
    """
    payload: Dict[str, Any] = {
        "couple_name": couple_name or unique_couple_name(),
        "ceremony_date": (
            ceremony_date if ceremony_date is not None
            else far_future_seconds(180)
        ),
        "style": style,
        "scale": scale,
        "planner_user_id": planner_user_id,
        "auditor_user_id": auditor_user_id,
        "total_budget_cents": total_budget_cents,
    }
    if template_id is not None:
        payload["template_id"] = template_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ProjectTemplate (PRD §3.1)
# ---------------------------------------------------------------------------
def create_template_payload(
    *,
    name: Optional[str] = None,
    scale: str = "MEDIUM",
    default_milestones: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'an Auditor registers each template with a unique name, a
    target scale, and the default_milestones payload.' Each entry of
    default_milestones is a {label, offset_days_from_ceremony, percent_of_budget}
    triple."""
    if default_milestones is None:
        default_milestones = [
            {"label": "Venue Deposit",
             "offset_days_from_ceremony": -180,
             "percent_of_budget": 50.0},
            {"label": "Final Payment",
             "offset_days_from_ceremony": -7,
             "percent_of_budget": 50.0},
        ]
    payload: Dict[str, Any] = {
        "name": name or unique_template_name(),
        "scale": scale,
        "default_milestones": default_milestones,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Milestone (PRD §3.1)
# ---------------------------------------------------------------------------
def create_milestone_payload(
    *,
    label: Optional[str] = None,
    due_at: Optional[int] = None,
    percent_of_budget: float = 100.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": label or unique_suffix("Milestone"),
        "due_at": due_at if due_at is not None else far_future_seconds(90),
        "percent_of_budget": percent_of_budget,
    }
    payload.update(overrides)
    return payload


def patch_milestone_payload(
    *,
    label: Optional[str] = None,
    due_at: Optional[int] = None,
    percent_of_budget: Optional[float] = None,
    status: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if label is not None:
        payload["label"] = label
    if due_at is not None:
        payload["due_at"] = due_at
    if percent_of_budget is not None:
        payload["percent_of_budget"] = percent_of_budget
    if status is not None:
        payload["status"] = status
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vendor (PRD §3.2)
# ---------------------------------------------------------------------------
def create_vendor_payload(
    *,
    name: Optional[str] = None,
    category: str = "PHOTOGRAPHY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_vendor_name(),
        "category": category,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Quote (PRD §3.2)
# ---------------------------------------------------------------------------
def create_quote_payload(
    *,
    amount_cents: int = 100_000,
    scope_description: str = "Standard service package",
    valid_until: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "scope_description": scope_description,
        "valid_until": (
            valid_until if valid_until is not None
            else far_future_seconds(60)
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contract (PRD §3.3)
# ---------------------------------------------------------------------------
def create_contract_payload(
    *,
    vendor_id: str,
    quote_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_id": vendor_id,
        "quote_id": quote_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ChangeOrder (PRD §3.4)
# ---------------------------------------------------------------------------
def create_change_order_payload(
    *,
    delta_amount_cents: int,
    reason: str = "Scope change",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delta_amount_cents": delta_amount_cents,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Settlement (PRD §3.4)
# ---------------------------------------------------------------------------
def create_settlement_payload(
    *,
    breach_deduction_cents: Optional[int] = None,
    refund_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'optionally seeding breach_deduction_cents and refund_cents
    (both default to 0 and both must remain non-negative).'"""
    payload: Dict[str, Any] = {}
    if breach_deduction_cents is not None:
        payload["breach_deduction_cents"] = breach_deduction_cents
    if refund_cents is not None:
        payload["refund_cents"] = refund_cents
    payload.update(overrides)
    return payload


def patch_settlement_payload(
    *,
    breach_deduction_cents: Optional[int] = None,
    refund_cents: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if breach_deduction_cents is not None:
        payload["breach_deduction_cents"] = breach_deduction_cents
    if refund_cents is not None:
        payload["refund_cents"] = refund_cents
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def create_performance_rating_payload(
    *,
    score: int,
    comment: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2 / §3.4: integer score 1..5 inclusive, optional comment."""
    payload: Dict[str, Any] = {"score": score}
    if comment is not None:
        payload["comment"] = comment
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TimelineSlot (PRD §3.6)
# ---------------------------------------------------------------------------
def create_timeline_slot_payload(
    *,
    start_at: int,
    end_at: int,
    label: str = "Slot",
    vendor_id: Optional[str] = None,
    setup_buffer_seconds: Optional[int] = None,
    kind: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "start_at": start_at,
        "end_at": end_at,
        "label": label,
    }
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    if setup_buffer_seconds is not None:
        payload["setup_buffer_seconds"] = setup_buffer_seconds
    if kind is not None:
        payload["kind"] = kind
    payload.update(overrides)
    return payload


def patch_timeline_slot_payload(
    *,
    start_at: Optional[int] = None,
    end_at: Optional[int] = None,
    setup_buffer_seconds: Optional[int] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if start_at is not None:
        payload["start_at"] = start_at
    if end_at is not None:
        payload["end_at"] = end_at
    if setup_buffer_seconds is not None:
        payload["setup_buffer_seconds"] = setup_buffer_seconds
    if label is not None:
        payload["label"] = label
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Guest (PRD §3.7)
# ---------------------------------------------------------------------------
def create_guest_payload(
    *,
    full_name: Optional[str] = None,
    party_size: Optional[int] = None,
    dietary_requirements: Optional[List[str]] = None,
    accessibility_requirements: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_suffix("Guest"),
    }
    if party_size is not None:
        payload["party_size"] = party_size
    if dietary_requirements is not None:
        payload["dietary_requirements"] = dietary_requirements
    if accessibility_requirements is not None:
        payload["accessibility_requirements"] = accessibility_requirements
    payload.update(overrides)
    return payload


def patch_guest_payload(
    *,
    full_name: Optional[str] = None,
    party_size: Optional[int] = None,
    dietary_requirements: Optional[List[str]] = None,
    accessibility_requirements: Optional[List[str]] = None,
    table_number: Optional[int] = None,
    gift_amount_cents: Optional[int] = None,
    thank_you_sent_at: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if full_name is not None:
        payload["full_name"] = full_name
    if party_size is not None:
        payload["party_size"] = party_size
    if dietary_requirements is not None:
        payload["dietary_requirements"] = dietary_requirements
    if accessibility_requirements is not None:
        payload["accessibility_requirements"] = accessibility_requirements
    if table_number is not None:
        payload["table_number"] = table_number
    if gift_amount_cents is not None:
        payload["gift_amount_cents"] = gift_amount_cents
    if thank_you_sent_at is not None:
        payload["thank_you_sent_at"] = thank_you_sent_at
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def rsvp_payload(*, rsvp_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rsvp_status": rsvp_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Budget reallocation (PRD §3.5)
# ---------------------------------------------------------------------------
def reallocate_budget_payload(
    *,
    allocations: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'allocations payload — a list of {milestone_id,
    percent_of_budget} pairs covering every milestone on the project.'"""
    payload: Dict[str, Any] = {"allocations": allocations}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Event hooks (PRD §3.8)
# ---------------------------------------------------------------------------
def emit_event_payload(
    *,
    kind: str,
    envelope_id: Optional[str] = None,
    contract_id: Optional[str] = None,
    settlement_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": kind}
    if envelope_id is not None:
        payload["envelope_id"] = envelope_id
    if contract_id is not None:
        payload["contract_id"] = contract_id
    if settlement_id is not None:
        payload["settlement_id"] = settlement_id
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix",
    "unique_couple_name",
    "unique_vendor_name",
    "unique_template_name",
    "now_seconds",
    "far_future_seconds",
    "create_project_payload",
    "create_template_payload",
    "create_milestone_payload",
    "patch_milestone_payload",
    "create_vendor_payload",
    "create_quote_payload",
    "create_contract_payload",
    "create_change_order_payload",
    "create_settlement_payload",
    "patch_settlement_payload",
    "create_performance_rating_payload",
    "create_timeline_slot_payload",
    "patch_timeline_slot_payload",
    "create_guest_payload",
    "patch_guest_payload",
    "rsvp_payload",
    "reallocate_budget_payload",
    "emit_event_payload",
]
