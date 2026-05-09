"""Payload factories — input fields only, exact PRD field names.

Factories cover only `source: input` fields. Computed fields (status, posture,
alert_state, signed_actor_id, etc.) are emitted by the server.
"""
from typing import Any, Dict, List, Optional
import uuid


# --- Production (PRD §3.1) ---

def create_production_payload(
    *,
    title: Optional[str] = None,
    production_type: str = "FILM",
    shoot_window_start: str = "2026-01-01T00:00:00.000Z",
    shoot_window_end: str = "2026-12-31T23:59:59.000Z",
    total_budget_cents: int = 200_000_000,
    reserve_fund_cents: int = 20_000_000,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "title": title or f"Test Production {uuid.uuid4().hex[:8]}",
        "production_type": production_type,
        "shoot_window_start": shoot_window_start,
        "shoot_window_end": shoot_window_end,
        "total_budget_cents": total_budget_cents,
        "reserve_fund_cents": reserve_fund_cents,
    }
    p.update(overrides)
    return p


# --- Scene (PRD §3.4) ---

def create_scene_payload(
    *,
    scene_number: Optional[str] = None,
    int_ext: str = "INT",
    planned_duration_minutes: int = 240,
    required_actor_role_ids: Optional[List[str]] = None,
    required_equipment_categories: Optional[List[str]] = None,
    weather_dependent: bool = False,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "scene_number": scene_number or f"S-{uuid.uuid4().hex[:6]}",
        "int_ext": int_ext,
        "planned_duration_minutes": planned_duration_minutes,
        "required_actor_role_ids": list(required_actor_role_ids or []),
        "required_equipment_categories": list(required_equipment_categories or []),
        "weather_dependent": weather_dependent,
    }
    p.update(overrides)
    return p


# --- Role / Casting (PRD §3.2) ---

def create_role_payload(
    *,
    role_name: Optional[str] = None,
    description: str = "Test role description",
    union_tier: str = "SUPPORTING",
    day_rate_cents: int = 200_000,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "role_name": role_name or f"Role-{uuid.uuid4().hex[:6]}",
        "description": description,
        "union_tier": union_tier,
        "day_rate_cents": day_rate_cents,
    }
    p.update(overrides)
    return p


def create_audition_payload(
    *,
    actor_id: str,
    audition_at: str = "2026-01-15T10:00:00.000Z",
    outcome: str = "PASS",
    notes: str = "Test audition notes",
    **overrides,
) -> Dict[str, Any]:
    p = {
        "actor_id": actor_id,
        "audition_at": audition_at,
        "outcome": outcome,
        "notes": notes,
    }
    p.update(overrides)
    return p


def offer_role_payload(*, actor_id: str, **overrides) -> Dict[str, Any]:
    p = {"actor_id": actor_id}
    p.update(overrides)
    return p


def substitute_role_payload(
    *,
    replacement_actor_id: str,
    replacement_role_name: Optional[str] = None,
    replacement_day_rate_cents: int = 200_000,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "replacement_actor_id": replacement_actor_id,
        "replacement_role_name": replacement_role_name or f"Sub-{uuid.uuid4().hex[:6]}",
        "replacement_day_rate_cents": replacement_day_rate_cents,
    }
    p.update(overrides)
    return p


# --- Actor (PRD §3.2) ---

def create_actor_payload(
    *,
    legal_name: Optional[str] = None,
    agency_contact_email: str = "agent@example.com",
    travel_origin_zone: str = "ZONE_A",
    **overrides,
) -> Dict[str, Any]:
    p = {
        "legal_name": legal_name or f"Actor {uuid.uuid4().hex[:6]}",
        "agency_contact_email": agency_contact_email,
        "travel_origin_zone": travel_origin_zone,
    }
    p.update(overrides)
    return p


# --- Location / Reservation (PRD §3.3) ---

def create_location_payload(
    *,
    name: Optional[str] = None,
    zone: str = "ZONE_A",
    requires_permit: bool = False,
    max_parallel_units: int = 1,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "name": name or f"Location-{uuid.uuid4().hex[:6]}",
        "zone": zone,
        "requires_permit": requires_permit,
        "max_parallel_units": max_parallel_units,
    }
    p.update(overrides)
    return p


def create_location_reservation_payload(
    *,
    location_id: str,
    production_id: str,
    scene_id: str,
    unit_label: str = "MAIN",
    start_at: str = "2026-02-01T09:00:00.000Z",
    end_at: str = "2026-02-01T17:00:00.000Z",
    **overrides,
) -> Dict[str, Any]:
    p = {
        "location_id": location_id,
        "production_id": production_id,
        "scene_id": scene_id,
        "unit_label": unit_label,
        "start_at": start_at,
        "end_at": end_at,
    }
    p.update(overrides)
    return p


def patch_permit_status_payload(*, permit_status: str, **overrides) -> Dict[str, Any]:
    p = {"permit_status": permit_status}
    p.update(overrides)
    return p


def patch_weather_status_payload(*, weather_status: str, **overrides) -> Dict[str, Any]:
    p = {"weather_status": weather_status}
    p.update(overrides)
    return p


def schedule_scene_payload(*, reservation_id: str, **overrides) -> Dict[str, Any]:
    p = {"reservation_id": reservation_id}
    p.update(overrides)
    return p


def reschedule_scene_payload(*, new_reservation_id: str, **overrides) -> Dict[str, Any]:
    p = {"new_reservation_id": new_reservation_id}
    p.update(overrides)
    return p


# --- Budget / ChangeOrder (PRD §3.1, §3.7) ---

def create_budget_category_payload(
    *,
    code: str = "CAST",
    planned_cents: int = 10_000_000,
    **overrides,
) -> Dict[str, Any]:
    p = {"code": code, "planned_cents": planned_cents}
    p.update(overrides)
    return p


def create_change_order_payload(
    *,
    production_id: str,
    category_id: str,
    delta_cents: int,
    justification: str = "Test change order",
    source: str = "REALLOCATION",
    **overrides,
) -> Dict[str, Any]:
    p = {
        "production_id": production_id,
        "category_id": category_id,
        "delta_cents": delta_cents,
        "justification": justification,
        "source": source,
    }
    p.update(overrides)
    return p


# --- Equipment (PRD §3.5) ---

def create_equipment_payload(
    *,
    name: Optional[str] = None,
    category: str = "CAMERA",
    acquisition_mode: str = "RENTAL",
    vendor_id: Optional[str] = None,
    unit_cost_cents: int = 50_000,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "name": name or f"Equipment-{uuid.uuid4().hex[:6]}",
        "category": category,
        "acquisition_mode": acquisition_mode,
        "vendor_id": vendor_id or f"vendor-{uuid.uuid4().hex[:8]}",
        "unit_cost_cents": unit_cost_cents,
    }
    p.update(overrides)
    return p


def create_equipment_event_payload(
    *,
    production_id: str,
    event_type: str,
    occurred_at: str = "2026-02-01T12:00:00.000Z",
    damage_charge_cents: int = 0,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "production_id": production_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "damage_charge_cents": damage_charge_cents,
    }
    p.update(overrides)
    return p


# --- Crew / Vendor (PRD §3.8, §3.6) ---

def create_crew_assignment_payload(
    *,
    crew_user_id: Optional[str] = None,
    role_label: str = "DP",
    day_rate_cents: int = 100_000,
    scheduled_days: int = 5,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "crew_user_id": crew_user_id or f"crew-{uuid.uuid4().hex[:8]}",
        "role_label": role_label,
        "day_rate_cents": day_rate_cents,
        "scheduled_days": scheduled_days,
    }
    p.update(overrides)
    return p


def patch_actual_days_payload(*, actual_days: int, **overrides) -> Dict[str, Any]:
    p = {"actual_days": actual_days}
    p.update(overrides)
    return p


def create_vendor_invoice_payload(
    *,
    production_id: str,
    vendor_id: str,
    category_code: str,
    gross_cents: int,
    **overrides,
) -> Dict[str, Any]:
    p = {
        "production_id": production_id,
        "vendor_id": vendor_id,
        "category_code": category_code,
        "gross_cents": gross_cents,
    }
    p.update(overrides)
    return p


# --- Test-driving endpoint payloads ---

def advance_clock_payload(*, to_iso8601: str, **overrides) -> Dict[str, Any]:
    p = {"to_iso8601": to_iso8601}
    p.update(overrides)
    return p


def emit_event_payload(*, event_type: str, payload: Optional[Dict[str, Any]] = None,
                        **overrides) -> Dict[str, Any]:
    p = {"event_type": event_type, "payload": payload or {}}
    p.update(overrides)
    return p
