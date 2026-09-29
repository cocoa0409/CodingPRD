"""Payload builders for every write endpoint.

Each builder returns a valid payload made of the canonical Harbor Lights
literals; keyword overrides replace individual fields, and passing a field
explicitly as ``None`` removes it so absent-field behaviour can be exercised.
"""

from typing import Any, Dict

from .constants import (
    ARTIST_AGENCY,
    ARTIST_DRAW_SCORE,
    ARTIST_GENRE,
    ARTIST_LEGAL_NAME,
    ARTIST_PERFORMING_NAME,
    ARTIST_RADIUS_MILES,
    CANONICAL_GUARANTEE_CENTS,
    CANONICAL_OFFER_EXPIRES_UTC,
    CANONICAL_SET_LENGTH_MINUTES,
    CANONICAL_SLOT_START_UTC,
    CANONICAL_WINDOW_END_DATE,
    CANONICAL_WINDOW_START_DATE,
    DEFAULT_CONTINGENCY_RESERVE_PCT,
    EVENT_END_DATE,
    EVENT_START_DATE,
    FEST_EDITION_YEAR,
    FEST_NAME,
    MARKET_LATITUDE,
    MARKET_LONGITUDE,
    PORTLAND_LATITUDE,
    PORTLAND_LONGITUDE,
    STAGE_BUFFER_MINUTES,
    STAGE_CAPACITY,
    STAGE_CURFEW_MINUTE,
    STAGE_DAY_CAP_MINUTES,
    STAGE_NAME,
    TALENT_BUDGET_CENTS,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a key given as None is dropped from the payload."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def festival_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": FEST_NAME,
            "edition_year": FEST_EDITION_YEAR,
            "market_latitude": MARKET_LATITUDE,
            "market_longitude": MARKET_LONGITUDE,
            "event_start_date": EVENT_START_DATE,
            "event_end_date": EVENT_END_DATE,
            "talent_budget_cents": TALENT_BUDGET_CENTS,
            "contingency_reserve_pct": DEFAULT_CONTINGENCY_RESERVE_PCT,
        },
        overrides,
    )


def budget_tier_payload(festival_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "festival_id": festival_id,
            "tier_code": "HEADLINER",
            "tier_rank": 1,
            "allocation_pct": 1.00,
            "max_slots": 2,
            "genre_focus": "ELECTRONIC",
        },
        overrides,
    )


def stage_payload(festival_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "festival_id": festival_id,
            "name": STAGE_NAME,
            "capacity": STAGE_CAPACITY,
            "daily_curfew_minute": STAGE_CURFEW_MINUTE,
            "daily_program_minutes_cap": STAGE_DAY_CAP_MINUTES,
            "changeover_buffer_minutes": STAGE_BUFFER_MINUTES,
            "is_flagship": True,
        },
        overrides,
    )


def artist_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": ARTIST_LEGAL_NAME,
            "performing_name": ARTIST_PERFORMING_NAME,
            "primary_genre": ARTIST_GENRE,
            "agency": ARTIST_AGENCY,
            "draw_score": ARTIST_DRAW_SCORE,
            "default_radius_miles": ARTIST_RADIUS_MILES,
        },
        overrides,
    )


def offer_payload(
    festival_id: str,
    artist_id: str,
    budget_tier_id: str,
    stage_id: str,
    **overrides,
) -> Dict[str, Any]:
    return _merge(
        {
            "festival_id": festival_id,
            "artist_id": artist_id,
            "budget_tier_id": budget_tier_id,
            "stage_id": stage_id,
            "guarantee_cents": CANONICAL_GUARANTEE_CENTS,
            "production_fee_cents": 0,
            "billing_position": 1,
            "set_length_minutes": CANONICAL_SET_LENGTH_MINUTES,
            "slot_start_utc": CANONICAL_SLOT_START_UTC,
            "offer_expires_utc": CANONICAL_OFFER_EXPIRES_UTC,
            "radius_miles": ARTIST_RADIUS_MILES,
            "window_start_date": CANONICAL_WINDOW_START_DATE,
            "window_end_date": CANONICAL_WINDOW_END_DATE,
            "exclusivity_scope": "FULL",
        },
        overrides,
    )


def counter_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {"counter_guarantee_cents": CANONICAL_GUARANTEE_CENTS, "counter_note": "Agency ask"},
        overrides,
    )


def revise_payload(**overrides) -> Dict[str, Any]:
    return _merge({"guarantee_cents": CANONICAL_GUARANTEE_CENTS}, overrides)


def competing_performance_payload(artist_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "artist_id": artist_id,
            "venue_city": "Portland",
            "venue_latitude": PORTLAND_LATITUDE,
            "venue_longitude": PORTLAND_LONGITUDE,
            "performance_date": "2026-11-20",
            "is_ticketed": True,
            "is_festival": False,
            "announced_capacity": 3000,
        },
        overrides,
    )


def rider_item_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "category": "TECHNICAL",
            "description": "Spare amp rack",
            "quantity": 1,
            "unit_cost_cents": 100000,
            "is_promoter_provided": False,
        },
        overrides,
    )


def advance_packet_payload(booking_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "booking_id": booking_id,
            "stage_plot_ref": "PLOT-NK-01",
            "input_channel_count": 48,
            "monitor_mix_count": 8,
            "travel_party_size": 12,
            "load_in_offset_minutes": 240,
        },
        overrides,
    )


def announcement_wave_payload(festival_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "festival_id": festival_id,
            "wave_number": 1,
            "phase": "PRESALE",
            "scheduled_reveal_utc": "2026-09-01T17:00:00Z",
        },
        overrides,
    )


def cancel_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "cancelling_party": "PROMOTER",
            "cancellation_reason": "Stage redesign dropped the slot",
        },
        overrides,
    )
