"""Request-payload builders. Every builder accepts `**overrides`.

These produce *payloads only* -- no HTTP traffic. Anything that must talk to
the API to be useful lives in `fixtures.py`.
"""

from __future__ import annotations

from typing import Any

from .constants import (
    HOLY_LAND_TIERS,
    MARIAN_SHRINES_GRID,
    MARIAN_SHRINES_TIERS,
    ROME_JUBILEE_GRID,
    ROME_JUBILEE_TIERS,
    STANDARD_CANCELLATION_GRID,
    TWO_TIER_PRICE_TIERS,
)

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


# ---------------------------------------------------------------------------
# Programs (PRD §3.1)
# ---------------------------------------------------------------------------


def program_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Holy Land Small Group {_next()}",
        "destination_country": "IL",
        "faith_tradition": "CATHOLIC",
        "duration_days": 10,
        "price_tiers": [dict(tier) for tier in HOLY_LAND_TIERS],
        "cancellation_grid": [dict(bucket) for bucket in STANDARD_CANCELLATION_GRID],
    }
    payload.update(overrides)
    return payload


def two_tier_program_payload(**overrides: Any) -> dict[str, Any]:
    """A programme whose P1 tier covers exactly one traveler and P2 covers 2..3."""
    payload = program_payload(
        name=f"Holy Land Small Group {_next()}",
        price_tiers=[dict(tier) for tier in TWO_TIER_PRICE_TIERS],
    )
    payload.update(overrides)
    return payload


def rome_jubilee_program_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Rome Jubilee Deluxe {_next()}",
        "destination_country": "IT",
        "faith_tradition": "CATHOLIC",
        "duration_days": 8,
        "price_tiers": [dict(tier) for tier in ROME_JUBILEE_TIERS],
        "cancellation_grid": [dict(bucket) for bucket in ROME_JUBILEE_GRID],
    }
    payload.update(overrides)
    return payload


def marian_shrines_program_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Marian Shrines of Europe {_next()}",
        "destination_country": "PT",
        "faith_tradition": "CATHOLIC",
        "duration_days": 7,
        "price_tiers": [dict(tier) for tier in MARIAN_SHRINES_TIERS],
        "cancellation_grid": [dict(bucket) for bucket in MARIAN_SHRINES_GRID],
    }
    payload.update(overrides)
    return payload


def price_tier(
    tier_code: str,
    min_pax: int,
    max_pax: int,
    per_pax_price_cents: int,
    single_supplement_cents: int = 98_000,
    deposit_cents: int = 50_000,
) -> dict[str, Any]:
    return {
        "tier_code": tier_code,
        "min_pax": min_pax,
        "max_pax": max_pax,
        "per_pax_price_cents": per_pax_price_cents,
        "single_supplement_cents": single_supplement_cents,
        "deposit_cents": deposit_cents,
    }


def cancellation_bucket(min_days_before: int, penalty_bp: int) -> dict[str, Any]:
    return {"min_days_before": min_days_before, "penalty_bp": penalty_bp}


# ---------------------------------------------------------------------------
# Departures (PRD §3.1)
# ---------------------------------------------------------------------------


def departure_payload(program_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "program_id": program_id,
        "departure_date": "2026-11-01",
        "return_date": "2026-11-11",
        "min_pax": 1,
        "max_pax": 40,
        "deposit_due_date": "2026-08-15",
        "final_payment_due_date": "2026-09-15",
        "mobility_accessible_coach": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Group leader agreements (PRD §3.4)
# ---------------------------------------------------------------------------


def agreement_payload(
    departure_id: str, expected_departure_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "departure_id": departure_id,
        "leader_name": "Fr. Alonso Reyes",
        "leader_user_id": f"u-leader-{_next()}",
        "free_travel_threshold": 2,
        "commission_mode": "PER_PAX_CASH",
        "commission_rate_cents_per_pax": 6000,
        "accrual_basis": "RECRUITED",
        "expected_departure_version": expected_departure_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pilgrims (PRD §3.5)
# ---------------------------------------------------------------------------


def pilgrim_payload(departure_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "departure_id": departure_id,
        "full_name": f"Anna Kessler {_next()}",
        "date_of_birth": "1980-05-05",
        "room_type_requested": "DOUBLE",
    }
    payload.update(overrides)
    return payload


def rooming_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "room_type_assigned": "DOUBLE",
        "room_label": f"R-{100 + _next()}",
        "ground_floor": False,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Cash and plans (PRD §3.7)
# ---------------------------------------------------------------------------


def payment_payload(amount_cents: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"amount_cents": amount_cents, "method": "ACH"}
    payload.update(overrides)
    return payload


def payment_plan_payload(
    plan_type: str, first_due_date: str, expected_pilgrim_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "plan_type": plan_type,
        "first_due_date": first_due_date,
        "expected_pilgrim_version": expected_pilgrim_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Air blocks (PRD §3.6)
# ---------------------------------------------------------------------------


def air_block_payload(departure_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "departure_id": departure_id,
        "carrier_code": "LY",
        "seats_held": 20,
        "name_change_deadline_utc": "2026-09-20T00:00:00Z",
        "deposit_deadline_utc": "2026-08-25T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def negotiation_round_payload(party: str, fare_cents: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"party": party, "fare_cents": fare_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sacred sites and service bookings (PRD §3.2)
# ---------------------------------------------------------------------------


def sacred_site_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Basilica of the Holy Sepulchre {_next()}",
        "country": "IL",
        "access_regime": "PERMIT_REQUIRED",
        "daily_capacity_pax": 200,
        "turnaround_buffer_minutes": 30,
        "requires_local_clergy": True,
    }
    payload.update(overrides)
    return payload


def open_access_site_payload(**overrides: Any) -> dict[str, Any]:
    """A friction-free site: open access, no buffer, no clergy requirement."""
    payload: dict[str, Any] = {
        "name": f"Mount of Beatitudes Chapel {_next()}",
        "country": "IL",
        "access_regime": "OPEN_ACCESS",
        "daily_capacity_pax": 5000,
        "turnaround_buffer_minutes": 0,
        "requires_local_clergy": False,
    }
    payload.update(overrides)
    return payload


def service_booking_payload(
    departure_id: str, sacred_site_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "departure_id": departure_id,
        "sacred_site_id": sacred_site_id,
        "service_type": "MASS",
        "scheduled_start_utc": "2026-11-02T06:00:00Z",
        "duration_minutes": 60,
        "pax_count": 2,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Land resources and assignments (PRD §3.3)
# ---------------------------------------------------------------------------


def land_resource_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operator_name": f"Terra Santa DMC {_next()}",
        "country": "IL",
        "resource_type": "HOTEL_ROOM_BLOCK",
        "units_total": 30,
        "unit_rate_local_cents": 45_000,
        "fx_rate_bp": 10_833,
        "force_majeure_notice_days": 45,
    }
    payload.update(overrides)
    return payload


def land_assignment_payload(
    land_resource_id: str, departure_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "land_resource_id": land_resource_id,
        "departure_id": departure_id,
        "date_from": "2026-11-01",
        "date_to": "2026-11-05",
        "units_requested": 6,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Travel protection (PRD §3.8)
# ---------------------------------------------------------------------------


def protection_payload(pilgrim_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "pilgrim_id": pilgrim_id,
        "plan_code": "STANDARD",
        "medical_limit_cents": 3_000_000,
        "pre_existing_waiver_requested": False,
    }
    payload.update(overrides)
    return payload


def medical_review_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"questionnaire_complete": True, "stable_period_days": 90}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Risk advisories (PRD §3.9)
# ---------------------------------------------------------------------------


def advisory_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "country": "IL",
        "level": "DO_NOT_TRAVEL",
        "effective_from": "2026-08-01T00:00:00Z",
        "source": "US Department of State Travel Advisory",
    }
    payload.update(overrides)
    return payload


__all__ = [
    "advisory_payload",
    "agreement_payload",
    "air_block_payload",
    "cancellation_bucket",
    "departure_payload",
    "land_assignment_payload",
    "land_resource_payload",
    "marian_shrines_program_payload",
    "medical_review_payload",
    "negotiation_round_payload",
    "open_access_site_payload",
    "payment_payload",
    "payment_plan_payload",
    "pilgrim_payload",
    "price_tier",
    "program_payload",
    "protection_payload",
    "rome_jubilee_program_payload",
    "rooming_payload",
    "sacred_site_payload",
    "service_booking_payload",
    "two_tier_program_payload",
]
