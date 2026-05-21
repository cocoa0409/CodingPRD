"""Payload factories — one per entity, input fields only.

PRD §2.4 forbids embedding system-managed fields in client requests; the
factories below emit ONLY the source: input fields the PRD declares on
each entity. Helpers append timestamp strings in ISO 8601 UTC with three
fractional digits per PRD §2.4.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_email() -> str:
    return f"member-{random_suffix(8)}@example.com"


def random_flight_number() -> str:
    return f"AA{random.randint(100, 9999)}"


def random_airport_code() -> str:
    # IATA codes are 3 uppercase letters.
    return "".join(random.choices(string.ascii_uppercase, k=3))


def random_idempotency_key() -> str:
    return f"idem-{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 demands ISO 8601 UTC with 3 fractional digits.
# ---------------------------------------------------------------------------
def iso_now_utc() -> str:
    return iso_from_dt(datetime.now(timezone.utc))


def iso_from_dt(dt: datetime) -> str:
    """Render dt as ISO 8601 UTC with three fractional digits and a Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return f"{base}.{millis:03d}Z"


def add_seconds_iso(iso: str, seconds: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(seconds=seconds))


def add_hours_iso(iso: str, hours: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(hours=hours))


def add_days_iso(iso: str, days: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(days=days))


def _parse_iso(iso: str) -> datetime:
    """Parse ISO-8601 strings as emitted by iso_from_dt or the server."""
    s = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# Entity payload factories
# ---------------------------------------------------------------------------
def create_member_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: creation takes email, display_name, home_region."""
    payload = {
        "email": random_email(),
        "display_name": f"Member-{random_suffix(6)}",
        "home_region": "DOMESTIC",
    }
    payload.update(overrides)
    return payload


def create_flight_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2: creation takes flight_number, origin, destination,
    distance_miles, route_region, departure_at, base_fare_cents, and the
    three optional cabin capacities.
    """
    # Default departure 90 days in the future so it stays SCHEDULED.
    default_departure = iso_from_dt(
        datetime.now(timezone.utc) + timedelta(days=90),
    )
    payload = {
        "flight_number": random_flight_number(),
        "origin": "JFK",
        "destination": "LAX",
        "distance_miles": 1_000,
        "route_region": "DOMESTIC",
        "departure_at": default_departure,
        "base_fare_cents": 50_000,
        "capacity_economy": 100,
        "capacity_business": 16,
        "capacity_first": 4,
    }
    payload.update(overrides)
    return payload


def create_segment_payload(flight_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.3: creation takes flight_id, booked_cabin."""
    payload = {
        "flight_id": flight_id,
        "booked_cabin": "ECONOMY",
    }
    payload.update(overrides)
    return payload


def create_upgrade_request_payload(target_cabin: str = "FIRST",
                                   points_offered: int = 5_000,
                                   **overrides) -> Dict[str, Any]:
    """PRD §3.4: creation takes target_cabin, points_offered."""
    payload = {
        "target_cabin": target_cabin,
        "points_offered": points_offered,
    }
    payload.update(overrides)
    return payload


def patch_upgrade_request_payload(points_offered: int,
                                  version: Optional[int] = None,
                                  **overrides) -> Dict[str, Any]:
    """PRD §3.4 + §2.5: PATCH takes points_offered (and optional version)."""
    payload: Dict[str, Any] = {"points_offered": points_offered}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def create_award_booking_payload(flight_id: str,
                                 cabin: str = "ECONOMY",
                                 pricing_mode: str = "FIXED",
                                 **overrides) -> Dict[str, Any]:
    """PRD §3.5: creation takes flight_id, cabin, pricing_mode, and
    optional cash_taxes_cents, companion_certificate_id.
    """
    payload: Dict[str, Any] = {
        "flight_id": flight_id,
        "cabin": cabin,
        "pricing_mode": pricing_mode,
    }
    payload.update(overrides)
    return payload


def create_status_match_request_payload(
    competitor_program: str = "OtherAirways",
    competitor_tier: str = "GOLD",
    evidence_url: str = "https://example.com/evidence.pdf",
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.7: creation takes competitor_program, competitor_tier,
    evidence_url.
    """
    payload = {
        "competitor_program": competitor_program,
        "competitor_tier": competitor_tier,
        "evidence_url": evidence_url,
    }
    payload.update(overrides)
    return payload


def create_gift_payload(recipient_member_id: str, amount: int,
                       idempotency_key: Optional[str] = None,
                       **overrides) -> Dict[str, Any]:
    """PRD §3.6: gift payload is recipient_member_id, amount,
    idempotency_key.
    """
    payload = {
        "recipient_member_id": recipient_member_id,
        "amount": amount,
        "idempotency_key": idempotency_key or random_idempotency_key(),
    }
    payload.update(overrides)
    return payload


def points_adjustment_payload(points_delta: int,
                              reason: str = "test adjustment",
                              **overrides) -> Dict[str, Any]:
    """PRD §3.8: admin adjustment takes points_delta, reason."""
    payload = {
        "points_delta": int(points_delta),
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def annual_rollover_payload(target_year: int,
                            **overrides) -> Dict[str, Any]:
    """PRD §3.1 + §3.8: rollover takes target_year."""
    payload = {"target_year": int(target_year)}
    payload.update(overrides)
    return payload


def clock_advance_payload(by_seconds: int,
                          **overrides) -> Dict[str, Any]:
    """PRD §3.8: clock advance takes by_seconds (integer)."""
    payload = {"by_seconds": int(by_seconds)}
    payload.update(overrides)
    return payload


def version_body(version: int) -> Dict[str, Any]:
    """PRD §2.5: optimistic-concurrency PATCH body fragment."""
    return {"version": int(version)}


__all__ = [
    "add_days_iso",
    "add_hours_iso",
    "add_seconds_iso",
    "annual_rollover_payload",
    "clock_advance_payload",
    "create_award_booking_payload",
    "create_flight_payload",
    "create_gift_payload",
    "create_member_payload",
    "create_segment_payload",
    "create_status_match_request_payload",
    "create_upgrade_request_payload",
    "iso_from_dt",
    "iso_now_utc",
    "patch_upgrade_request_payload",
    "points_adjustment_payload",
    "random_airport_code",
    "random_email",
    "random_flight_number",
    "random_idempotency_key",
    "random_suffix",
    "version_body",
]
