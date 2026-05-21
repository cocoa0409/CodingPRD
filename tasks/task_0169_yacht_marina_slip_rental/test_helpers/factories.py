"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.8: all monetary values are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def date_iso(year: int, month: int, day: int,
             hour: int = 0, minute: int = 0,
             second: int = 0, millis: int = 0) -> str:
    """Build an ISO 8601 UTC string for the given date/time."""
    return iso_utc(
        datetime(year, month, day, hour, minute, second,
                 millis * 1000, tzinfo=timezone.utc)
    )


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_code(prefix: str = "S") -> str:
    """Slip code unique within a marina (PRD §3.3: "human label `code`
    that is unique within its marina")."""
    return f"{prefix}-{random_suffix(6).upper()}"


# ---------------------------------------------------------------------------
# Marina — POST /marinas
# ---------------------------------------------------------------------------
def create_marina_payload(
    *,
    name: Optional[str] = None,
    timezone: Optional[str] = None,
    base_daily_rate_cents: int = TEST_DEFAULTS["BASE_DAILY_RATE_CENTS"],
    liveaboard_quota: int = TEST_DEFAULTS["LIVEABOARD_QUOTA"],
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or TEST_DEFAULTS["MARINA_NAME"],
        "base_daily_rate_cents": base_daily_rate_cents,
        "liveaboard_quota": liveaboard_quota,
    }
    if timezone is not None:
        payload["timezone"] = timezone
    payload.update(extra)
    return payload


def clock_advance_payload(*, to: str, **extra: Any) -> Dict[str, Any]:
    """PRD §3.1 / §2.7: "a `DockMaster` advances it explicitly: an
    operator-only test-driving capability accepts a `to` instant..."."""
    payload: Dict[str, Any] = {"to": to}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Boater — POST /marinas/:m/boaters
# ---------------------------------------------------------------------------
def create_boater_payload(
    *,
    name: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or TEST_DEFAULTS["BOATER_NAME"],
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Vessel — POST /marinas/:m/boaters/:b/vessels
# ---------------------------------------------------------------------------
def create_vessel_payload(
    *,
    name: Optional[str] = None,
    loa_feet: float = TEST_DEFAULTS["VESSEL_LOA_FEET"],
    beam_feet: float = TEST_DEFAULTS["VESSEL_BEAM_FEET"],
    draft_feet: float = TEST_DEFAULTS["VESSEL_DRAFT_FEET"],
    holding_tank_gallons: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or TEST_DEFAULTS["VESSEL_NAME"],
        "loa_feet": loa_feet,
        "beam_feet": beam_feet,
        "draft_feet": draft_feet,
    }
    if holding_tank_gallons is not None:
        payload["holding_tank_gallons"] = holding_tank_gallons
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Slip — POST /marinas/:m/slips
# ---------------------------------------------------------------------------
def create_slip_payload(
    *,
    code: Optional[str] = None,
    length_feet: float = TEST_DEFAULTS["SLIP_LENGTH_FEET"],
    beam_feet: float = TEST_DEFAULTS["SLIP_BEAM_FEET"],
    depth_feet: float = TEST_DEFAULTS["SLIP_DEPTH_FEET"],
    flat_daily_charge_cents: int = TEST_DEFAULTS[
        "SLIP_FLAT_DAILY_CHARGE_CENTS"
    ],
    liveaboard_allowed: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or unique_code(),
        "length_feet": length_feet,
        "beam_feet": beam_feet,
        "depth_feet": depth_feet,
        "flat_daily_charge_cents": flat_daily_charge_cents,
    }
    if liveaboard_allowed is not None:
        payload["liveaboard_allowed"] = liveaboard_allowed
    payload.update(extra)
    return payload


def patch_slip_status_payload(*, status: str,
                              **extra: Any) -> Dict[str, Any]:
    """PRD §3.3: PATCH slip status accepts a `status` field. The
    If-Match HTTP header carries the version; it is not part of the
    body."""
    payload: Dict[str, Any] = {"status": status}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Reservation — POST /marinas/:m/reservations
# ---------------------------------------------------------------------------
def create_reservation_payload(
    *,
    boater_id: str,
    vessel_id: str,
    slip_id: str,
    check_in_date: str,
    check_out_date: str,
    insurance_policy_id: str,
    liveaboard: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "boater_id": boater_id,
        "vessel_id": vessel_id,
        "slip_id": slip_id,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "insurance_policy_id": insurance_policy_id,
    }
    if liveaboard is not None:
        payload["liveaboard"] = liveaboard
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# WaitlistEntry — POST /marinas/:m/waitlist
# ---------------------------------------------------------------------------
def create_waitlist_payload(
    *,
    boater_id: str,
    vessel_id: str,
    requested_check_in: str,
    requested_check_out: str,
    liveaboard: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "boater_id": boater_id,
        "vessel_id": vessel_id,
        "requested_check_in": requested_check_in,
        "requested_check_out": requested_check_out,
    }
    if liveaboard is not None:
        payload["liveaboard"] = liveaboard
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# SlipTransferRequest — POST /marinas/:m/transfer-requests
# ---------------------------------------------------------------------------
def create_transfer_request_payload(
    *,
    reservation_id: str,
    desired_slip_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reservation_id": reservation_id,
        "desired_slip_id": desired_slip_id,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# PumpOutJob — POST /marinas/:m/pump-out-jobs
# ---------------------------------------------------------------------------
def create_pump_out_payload(
    *,
    reservation_id: str,
    scheduled_start: str,
    scheduled_end: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reservation_id": reservation_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(extra)
    return payload


def complete_pump_out_payload(
    *,
    tank_gallons_drained: int,
    **extra: Any,
) -> Dict[str, Any]:
    """PRD §3.8: complete a pump-out by "supplying
    `tank_gallons_drained` (which must be strictly greater than zero)"."""
    payload: Dict[str, Any] = {
        "tank_gallons_drained": tank_gallons_drained,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# UtilityReading — POST .../utility-readings
# ---------------------------------------------------------------------------
def create_utility_reading_payload(
    *,
    read_at: str,
    kwh_delta: int,
    water_gallons_delta: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "read_at": read_at,
        "kwh_delta": kwh_delta,
        "water_gallons_delta": water_gallons_delta,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# InsurancePolicy — POST /marinas/:m/boaters/:b/policies
# ---------------------------------------------------------------------------
def create_policy_payload(
    *,
    carrier: Optional[str] = None,
    liability_limit_cents: int = TEST_DEFAULTS[
        "INSURANCE_LIABILITY_LIMIT_CENTS"
    ],
    effective_date: Optional[str] = None,
    expiration_date: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "carrier": carrier or TEST_DEFAULTS["INSURANCE_CARRIER"],
        "liability_limit_cents": liability_limit_cents,
        "effective_date": (
            effective_date or TEST_DEFAULTS["INSURANCE_EFFECTIVE_DATE"]
        ),
        "expiration_date": (
            expiration_date or TEST_DEFAULTS["INSURANCE_EXPIRATION_DATE"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# TowAssistContract — POST /marinas/:m/boaters/:b/tow-contracts
# ---------------------------------------------------------------------------
def create_tow_contract_payload(
    *,
    tier: str = "BASIC",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"tier": tier}
    payload.update(extra)
    return payload


def create_tow_event_payload(
    *,
    occurred_at: str,
    from_position: str,
    to_slip_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "occurred_at": occurred_at,
        "from_position": from_position,
        "to_slip_id": to_slip_id,
    }
    payload.update(extra)
    return payload


__all__ = [
    # Time helpers
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_hours", "add_days",
    "date_iso",
    # Uniqueness
    "random_suffix", "unique_code",
    # Marina / clock
    "create_marina_payload", "clock_advance_payload",
    # Boater
    "create_boater_payload",
    # Vessel
    "create_vessel_payload",
    # Slip
    "create_slip_payload", "patch_slip_status_payload",
    # Reservation
    "create_reservation_payload",
    # Waitlist
    "create_waitlist_payload",
    # Transfer
    "create_transfer_request_payload",
    # Pump-out
    "create_pump_out_payload", "complete_pump_out_payload",
    # Utility readings
    "create_utility_reading_payload",
    # Insurance
    "create_policy_payload",
    # Tow
    "create_tow_contract_payload", "create_tow_event_payload",
]
