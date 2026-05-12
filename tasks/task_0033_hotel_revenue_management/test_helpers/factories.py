"""Payload factories — one factory per entity, input fields only.

Field names match PRD §3 verbatim. Every factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_room_type_code(prefix: str = "RT") -> str:
    """RoomType.code: uppercase, 2-8 chars (PRD §3.1)."""
    suffix = uuid.uuid4().hex[:5].upper()
    return (prefix + suffix)[:8]


def unique_room_number(prefix: str = "R") -> str:
    return f"{prefix}{uuid.uuid4().hex[:6].upper()}"


def unique_channel_code(prefix: str = "CH") -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{suffix}"


def unique_rate_plan_code(prefix: str = "RP") -> str:
    suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}{suffix}"


def unique_guest_name(prefix: str = "Guest") -> str:
    return f"{prefix} {uuid.uuid4().hex[:6]}"


def unique_priority_rank(base: int = 100) -> int:
    """Pick a priority_rank deterministically unlikely to collide.

    PRD §3.2 requires ranks unique among ACTIVE channels. We sample from a
    large window so concurrent test runs do not collide.
    """
    return base + (uuid.uuid4().int % 9000)


# ---------------------------------------------------------------------------
# RoomType payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_room_type_payload(
    *,
    code: Optional[str] = None,
    name: Optional[str] = None,
    base_rate_cents: int = 20000,
    max_occupancy: int = 2,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_room_type_code(),
        "name": name or "Standard Room",
        "base_rate_cents": base_rate_cents,
        "max_occupancy": max_occupancy,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Room payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_room_payload(
    *,
    room_type_id: str,
    room_number: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_number": room_number or unique_room_number(),
        "room_type_id": room_type_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MaintenanceBlock payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_maintenance_block_payload(
    *,
    room_id: str,
    start_date: str,
    end_date: str,
    reason: str = "Refurbishment",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_id": room_id,
        "start_date": start_date,
        "end_date": end_date,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Channel payload (PRD §3.2)
# ---------------------------------------------------------------------------
def create_channel_payload(
    *,
    code: Optional[str] = None,
    channel_type: str = "DIRECT",
    commission_basis_points: int = 0,
    priority_rank: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_channel_code(),
        "channel_type": channel_type,
        "commission_basis_points": commission_basis_points,
        "priority_rank": (priority_rank
                          if priority_rank is not None
                          else unique_priority_rank()),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RatePlan payload (PRD §3.2)
# ---------------------------------------------------------------------------
def create_rate_plan_payload(
    *,
    room_type_id: str,
    code: Optional[str] = None,
    refund_tier_code: str = "FLEXIBLE",
    modification_allowed: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_rate_plan_code(),
        "room_type_id": room_type_id,
        "refund_tier_code": refund_tier_code,
        "modification_allowed": modification_allowed,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ChannelRatePlanMapping payload (PRD §3.2)
# ---------------------------------------------------------------------------
def create_channel_rate_plan_mapping_payload(
    *,
    channel_id: str,
    rate_plan_id: str,
    inventory_share_basis_points: int = 10000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "channel_id": channel_id,
        "rate_plan_id": rate_plan_id,
        "inventory_share_basis_points": inventory_share_basis_points,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RateOverride payload (PRD §3.3)
# ---------------------------------------------------------------------------
def create_rate_override_payload(
    *,
    room_type_id: str,
    stay_date: str,
    proposed_rate_cents: int = 25000,
    recommendation_source: str = "MANUAL_OVERRIDE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_type_id": room_type_id,
        "stay_date": stay_date,
        "proposed_rate_cents": proposed_rate_cents,
        "recommendation_source": recommendation_source,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OverbookingPolicy payload (PRD §3.4)
# ---------------------------------------------------------------------------
def create_overbooking_policy_payload(
    *,
    room_type_id: str,
    stay_date: str,
    overbook_ratio_basis_points: int = 1500,
    estimated_no_show_probability_basis_points: int = 1000,
    walkout_compensation_cents: int = 15000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_type_id": room_type_id,
        "stay_date": stay_date,
        "overbook_ratio_basis_points": overbook_ratio_basis_points,
        "estimated_no_show_probability_basis_points":
            estimated_no_show_probability_basis_points,
        "walkout_compensation_cents": walkout_compensation_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reservation payload (PRD §3.5)
# ---------------------------------------------------------------------------
def create_reservation_payload(
    *,
    room_type_id: str,
    rate_plan_id: str,
    channel_id: str,
    check_in_date: str,
    check_out_date: str,
    guest_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "guest_name": guest_name or unique_guest_name(),
        "room_type_id": room_type_id,
        "rate_plan_id": rate_plan_id,
        "channel_id": channel_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }
    payload.update(overrides)
    return payload


def modify_reservation_payload(
    *,
    check_in_date: str,
    check_out_date: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def check_in_payload(
    *,
    room_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"room_id": room_id}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(
    *,
    resolution: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """resolution must be 'GUEST' or 'HOTEL' (PRD §3.8)."""
    payload: Dict[str, Any] = {"resolution": resolution}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_room_type_code",
    "unique_room_number",
    "unique_channel_code",
    "unique_rate_plan_code",
    "unique_guest_name",
    "unique_priority_rank",
    "create_room_type_payload",
    "create_room_payload",
    "create_maintenance_block_payload",
    "create_channel_payload",
    "create_rate_plan_payload",
    "create_channel_rate_plan_mapping_payload",
    "create_rate_override_payload",
    "create_overbooking_policy_payload",
    "create_reservation_payload",
    "modify_reservation_payload",
    "check_in_payload",
    "resolve_dispute_payload",
]
