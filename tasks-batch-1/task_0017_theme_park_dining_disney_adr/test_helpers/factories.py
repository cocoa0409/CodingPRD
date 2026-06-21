"""Payload factories — one per entity, input fields only.

Driven by PRD §3 (entity-by-entity field lists). Every defaulted value matches
the PRD; all overrides flow through `**overrides`.
"""
from typing import Optional, List


# ─── Guest ────────────────────────────────────────────────────────────────

def create_guest_payload(
    email: str = "guest@example.com",
    full_name: str = "Test Guest",
    home_timezone: str = "America/New_York",
    **overrides,
) -> dict:
    payload = {
        "email": email,
        "full_name": full_name,
        "home_timezone": home_timezone,
    }
    payload.update(overrides)
    return payload


# ─── Restaurant ───────────────────────────────────────────────────────────

def create_restaurant_payload(
    name: str = "Test Restaurant",
    park_code: str = "EPCOT",
    capacity_per_slot: int = 20,
    dining_plan_credit_cost: int = 1,
    no_show_base_fee_cents: int = 1000,
    opening_local_time: str = "11:00",
    closing_local_time: str = "22:00",
    slot_minutes: Optional[int] = 30,
    is_character_dining: Optional[bool] = False,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "park_code": park_code,
        "capacity_per_slot": capacity_per_slot,
        "dining_plan_credit_cost": dining_plan_credit_cost,
        "no_show_base_fee_cents": no_show_base_fee_cents,
        "opening_local_time": opening_local_time,
        "closing_local_time": closing_local_time,
    }
    if slot_minutes is not None:
        payload["slot_minutes"] = slot_minutes
    if is_character_dining is not None:
        payload["is_character_dining"] = is_character_dining
    payload.update(overrides)
    return payload


# ─── ParkSession ──────────────────────────────────────────────────────────

def create_park_session_payload(
    guest_id: str,
    park_code: str = "EPCOT",
    visit_date: str = "2026-02-15",
    **overrides,
) -> dict:
    payload = {
        "guest_id": guest_id,
        "park_code": park_code,
        "visit_date": visit_date,
    }
    payload.update(overrides)
    return payload


# ─── DiningPlan ───────────────────────────────────────────────────────────

def create_dining_plan_payload(
    guest_id: str,
    tier: str = "STANDARD",
    table_service_credits_initial: int = 10,
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_until: str = "2026-12-31T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "guest_id": guest_id,
        "tier": tier,
        "table_service_credits_initial": table_service_credits_initial,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


# ─── Reservation ──────────────────────────────────────────────────────────

def create_reservation_payload(
    guest_id: str,
    restaurant_id: str,
    park_session_id: str,
    dining_plan_id: str,
    slot_start_utc: str = "2026-02-15T18:00:00Z",
    party_size: int = 2,
    **overrides,
) -> dict:
    payload = {
        "guest_id": guest_id,
        "restaurant_id": restaurant_id,
        "park_session_id": park_session_id,
        "dining_plan_id": dining_plan_id,
        "slot_start_utc": slot_start_utc,
        "party_size": party_size,
    }
    payload.update(overrides)
    return payload


def cancel_reservation_payload(expected_reservation_version: int) -> dict:
    return {"expected_reservation_version": expected_reservation_version}


def patch_party_size_payload(party_size: int) -> dict:
    return {"party_size": party_size}


# ─── AllergyMeal ──────────────────────────────────────────────────────────

def create_allergy_meal_payload(
    reservation_id: str,
    allergen_codes: Optional[List[str]] = None,
    notes: Optional[str] = None,
    **overrides,
) -> dict:
    if allergen_codes is None:
        allergen_codes = ["PEANUT"]
    payload = {
        "reservation_id": reservation_id,
        "allergen_codes": list(allergen_codes),
    }
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


def decline_allergy_meal_payload(reason: str) -> dict:
    return {"reason": reason}


# ─── LightningLaneAddOn ───────────────────────────────────────────────────

def create_lightning_lane_payload(
    reservation_id: str,
    tier: str = "SINGLE_PASS",
    **overrides,
) -> dict:
    payload = {
        "reservation_id": reservation_id,
        "tier": tier,
    }
    payload.update(overrides)
    return payload


def allocate_lightning_lane_payload(expected_reservation_version: int) -> dict:
    return {"expected_reservation_version": expected_reservation_version}


# ─── Ops ──────────────────────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
