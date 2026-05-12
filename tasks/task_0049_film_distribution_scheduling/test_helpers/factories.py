"""Payload factories -- one factory per input-bearing endpoint.

Each factory emits ONLY the fields PRD §3 declares as input (source: input)
for the relevant endpoint. Tests override defaults via kwargs.

Field names mirror PRD prose exactly -- never abbreviated, never guessed.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import (
    ALT_REGION,
    DEFAULT_AD_MIN,
    DEFAULT_BUSINESS_DATE,
    DEFAULT_CLEANING_INTERVAL_MIN,
    DEFAULT_PEAK_END_MIN,
    DEFAULT_PEAK_START_MIN,
    DEFAULT_PRESALE_OPENS_AT,
    DEFAULT_REGION,
    DEFAULT_RELEASE_DATE,
    DEFAULT_TRAILER_MIN,
    WIDE_OPERATING_END_MIN,
    WIDE_OPERATING_START_MIN,
)


def unique_suffix() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Distributor (PRD §3.1)
# ---------------------------------------------------------------------------
def create_distributor_payload(
    *,
    name: Optional[str] = None,
    contact_email: Optional[str] = None,
    default_split_ratio_bps: int = 6000,
    min_show_count_per_week: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A new distributor is created with name, contact_email,
    the integer default_split_ratio_bps that will govern how net revenue
    is shared between distributor and cinema on every settlement, and
    min_show_count_per_week that pins the minimum number of weekly
    showings any cinema must run for any film carrying this distributor's
    label.'"""
    payload: Dict[str, Any] = {
        "name": name or f"Dist {unique_suffix()}",
        "contact_email": contact_email or f"ops-{unique_suffix()}@example.com",
        "default_split_ratio_bps": default_split_ratio_bps,
        "min_show_count_per_week": min_show_count_per_week,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Film (PRD §3.1)
# ---------------------------------------------------------------------------
def create_film_payload(
    *,
    title: Optional[str] = None,
    distributor_id: str,
    duration_minutes: int = 90,
    rating: str = "PG13",
    format: str = "2D",
    release_date: str = DEFAULT_RELEASE_DATE,
    region_strategy: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'The request supplies a title, the foreign key
    distributor_id, a positive integer duration_minutes, a rating chosen
    from G, PG, PG13, R, or NC17, a format chosen from 2D, 3D, or IMAX,
    and a release_date that is the earliest moment the title may be sold
    publicly.'"""
    payload: Dict[str, Any] = {
        "title": title or f"Film {unique_suffix()}",
        "distributor_id": distributor_id,
        "duration_minutes": duration_minutes,
        "rating": rating,
        "format": format,
        "release_date": release_date,
        "region_strategy": (
            region_strategy if region_strategy is not None
            else {
                "allowed_regions": [DEFAULT_REGION, ALT_REGION],
                "tier_caps": {"TIER_1": 5, "TIER_2": 5, "TIER_3": 5},
            }
        ),
    }
    payload.update(overrides)
    return payload


def shelve_payload(*, version: int, reason: str = "low_demand") -> Dict[str, Any]:
    """PRD §3.2: 'Shelving ... is a soft pause invoked by DistributorOps
    with a free-text reason that the server records on the film's
    shelved_reason.'"""
    return {"version": version, "reason": reason}


def version_payload(version: int) -> Dict[str, Any]:
    """For action endpoints whose request body carries only `version`.
    PRD §2.6 declares `version` as the optimistic-concurrency field."""
    return {"version": version}


# ---------------------------------------------------------------------------
# Cinema (PRD §3.3)
# ---------------------------------------------------------------------------
def create_cinema_payload(
    *,
    name: Optional[str] = None,
    region_code: str = DEFAULT_REGION,
    tier: str = "TIER_1",
    peak_window_start_minute: int = DEFAULT_PEAK_START_MIN,
    peak_window_end_minute: int = DEFAULT_PEAK_END_MIN,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'CinemaOps registers a Cinema with name, a region_code, a
    tier chosen from TIER_1, TIER_2, or TIER_3, and the cinema-wide peak
    window defined by peak_window_start_minute and peak_window_end_minute.'"""
    payload: Dict[str, Any] = {
        "name": name or f"Cinema {unique_suffix()}",
        "region_code": region_code,
        "tier": tier,
        "peak_window_start_minute": peak_window_start_minute,
        "peak_window_end_minute": peak_window_end_minute,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Screen (PRD §3.3)
# ---------------------------------------------------------------------------
def create_screen_payload(
    *,
    label: Optional[str] = None,
    supported_formats: Optional[List[str]] = None,
    operating_start_minute: int = WIDE_OPERATING_START_MIN,
    operating_end_minute: int = WIDE_OPERATING_END_MIN,
    cleaning_interval_minutes: int = DEFAULT_CLEANING_INTERVAL_MIN,
    trailer_minutes: int = DEFAULT_TRAILER_MIN,
    ad_minutes: int = DEFAULT_AD_MIN,
    seat_capacity: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'A screen carries a human-readable label, the array
    supported_formats listing which of 2D, 3D, and IMAX it can project, an
    operating_start_minute (inclusive) and operating_end_minute (exclusive)
    bounding when the screen can run, a cleaning_interval_minutes between
    consecutive shows that defaults to 15, a trailer_minutes count
    defaulting to 10, an ad_minutes count defaulting to 5, and a positive
    integer seat_capacity.'"""
    payload: Dict[str, Any] = {
        "label": label or f"Screen {unique_suffix()}",
        "supported_formats": (
            supported_formats if supported_formats is not None
            else ["2D", "3D", "IMAX"]
        ),
        "operating_start_minute": operating_start_minute,
        "operating_end_minute": operating_end_minute,
        "cleaning_interval_minutes": cleaning_interval_minutes,
        "trailer_minutes": trailer_minutes,
        "ad_minutes": ad_minutes,
        "seat_capacity": seat_capacity,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Showtime (PRD §3.4)
# ---------------------------------------------------------------------------
def create_showtime_payload(
    *,
    film_id: str,
    start_minute: int = 720,
    business_date: str = DEFAULT_BUSINESS_DATE,
    ticket_price_cents: int = 1500,
    presale_opens_at: str = DEFAULT_PRESALE_OPENS_AT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'CinemaOps schedules a showtime against a specific screen
    by supplying the film_id, an integer start_minute (the minute-of-day at
    which the ad block begins), a business_date carrying the calendar date
    the screening belongs to as a midnight ISO 8601 timestamp, the per-seat
    ticket_price_cents, and the presale_opens_at instant.'"""
    payload: Dict[str, Any] = {
        "film_id": film_id,
        "start_minute": start_minute,
        "business_date": business_date,
        "ticket_price_cents": ticket_price_cents,
        "presale_opens_at": presale_opens_at,
    }
    payload.update(overrides)
    return payload


def cancel_showtime_payload(
    *,
    version: int,
    cancel_reason: str = "INCIDENT",
    exchange_to_showtime_id: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.7: 'CinemaOps cancels a SCHEDULED showtime by supplying a
    cancel_reason chosen from LOW_ATTENDANCE, NEW_FILM_INSERTION, and
    INCIDENT, an optional exchange_to_showtime_id ..., and the standard
    version field.'"""
    payload: Dict[str, Any] = {
        "version": version,
        "cancel_reason": cancel_reason,
    }
    if exchange_to_showtime_id is not None:
        payload["exchange_to_showtime_id"] = exchange_to_showtime_id
    return payload


# ---------------------------------------------------------------------------
# Ticket (PRD §3.5, §3.8)
# ---------------------------------------------------------------------------
def create_ticket_payload(
    *,
    buyer_external_id: str = "buyer-001",
    paid_amount_cents: int = 1500,
    promo_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'TicketingPlatform purchases a ticket against a specific
    showtime by supplying the buyer_external_id, a non-negative integer
    paid_amount_cents, and optionally a promo_code.'"""
    payload: Dict[str, Any] = {
        "buyer_external_id": buyer_external_id,
        "paid_amount_cents": paid_amount_cents,
    }
    if promo_code is not None:
        payload["promo_code"] = promo_code
    payload.update(overrides)
    return payload


def exchange_ticket_payload(
    *,
    version: int,
    exchanged_to_showtime_id: str,
) -> Dict[str, Any]:
    """PRD §3.8: 'An exchange takes version plus the request-body field
    exchanged_to_showtime_id naming the destination showtime.'"""
    return {
        "version": version,
        "exchanged_to_showtime_id": exchanged_to_showtime_id,
    }


# ---------------------------------------------------------------------------
# Settlement (PRD §3.9)
# ---------------------------------------------------------------------------
def create_settlement_payload(
    *,
    showtime_id: str,
    cycle_label: str = "2026-W19",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.9: 'FinanceOps creates a draft posting against a showtime by
    supplying the showtime_id and the cycle_label (an ISO-week identifier
    such as 2026-W19).'"""
    payload: Dict[str, Any] = {
        "showtime_id": showtime_id,
        "cycle_label": cycle_label,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock / sweep / external events (PRD §2.10, §3.10)
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    """PRD §2.10: 'the clock can be advanced ... by submitting an ISO 8601
    instant as to_timestamp.'"""
    return {"to_timestamp": to_timestamp}


def external_event_payload(
    *,
    kind: str = "TICKETING_PLATFORM",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """PRD §3.10: 'Each inbound event carries a kind of TICKETING_PLATFORM,
    PAYMENT, or CINEMA_MGMT, plus a free-form payload object'."""
    return {
        "kind": kind,
        "payload": payload if payload is not None else {"note": "synthetic"},
    }


__all__ = [
    "unique_suffix",
    "create_distributor_payload",
    "create_film_payload",
    "shelve_payload",
    "version_payload",
    "create_cinema_payload",
    "create_screen_payload",
    "create_showtime_payload",
    "cancel_showtime_payload",
    "create_ticket_payload",
    "exchange_ticket_payload",
    "create_settlement_payload",
    "clock_advance_payload",
    "external_event_payload",
]
