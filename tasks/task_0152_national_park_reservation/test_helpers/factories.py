"""Payload factories — one per endpoint that accepts a body.

Each factory emits the exact JSON-body schema the PRD declares for
the request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared
input fields are produced; computed/system fields are omitted so the
implementation cannot accidentally accept them.

PRD §2.2: API responses use ISO 8601 UTC with three fractional digits.
Input fields that take datetimes accept the same format.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_TIMED_ENTRY_WINDOW_MINUTES,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.2 ISO 8601 UTC with three fractional digits
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


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def date_to_local_str(d: date) -> str:
    """YYYY-MM-DD."""
    return d.strftime("%Y-%m-%d")


def local_hhmm(hour: int, minute: int = 0) -> str:
    """HH:MM."""
    return f"{hour:02d}:{minute:02d}"


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_email() -> str:
    return f"visitor_{random_suffix(6).lower()}@example.com"


def random_park_code() -> str:
    return f"{TEST_DEFAULTS['park_code_prefix']}{random_suffix(4)}"


def random_park_name() -> str:
    return f"{TEST_DEFAULTS['park_name_prefix']} {random_suffix(4)}"


def random_campground_name() -> str:
    return f"{TEST_DEFAULTS['campground_name_prefix']} {random_suffix(4)}"


def random_zone_name() -> str:
    return f"{TEST_DEFAULTS['zone_name_prefix']} {random_suffix(4)}"


def random_lottery_name() -> str:
    return f"{TEST_DEFAULTS['lottery_name_prefix']} {random_suffix(4)}"


def random_plate() -> str:
    # PRD §3.3: "vehicle_plate (1 through 10 characters, uppercased on
    # persist)"
    return random_suffix(6)


# ---------------------------------------------------------------------------
# Clock / sweep — PRD §2.13, §4
# ---------------------------------------------------------------------------
def clock_advance_payload(target_iso: str) -> Dict[str, Any]:
    """PRD §2.13: 'advances the logical clock to a supplied target_iso
    instant'.
    """
    return {"target_iso": target_iso}


# ---------------------------------------------------------------------------
# Visitor — PRD §3.1
# ---------------------------------------------------------------------------
def create_visitor_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'The record carries an email (RFC 5322 compliant,
    unique across the system), a full_name (1 through 120 characters)'.
    """
    defaults: Dict[str, Any] = {
        "email": random_email(),
        "full_name": f"{TEST_DEFAULTS['visitor_full_name']} {random_suffix(4)}",
    }
    defaults.update(overrides)
    return defaults


def wallet_deposit_payload(amount_cents: int) -> Dict[str, Any]:
    """PRD §3.1: 'with the deposit amount specified in the request body
    as amount_cents'.
    """
    return {"amount_cents": amount_cents}


# ---------------------------------------------------------------------------
# Pass — PRD §3.1
# ---------------------------------------------------------------------------
def issue_pass_payload(
    pass_type: str = "ANNUAL",
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'a pass_type drawn from {ANNUAL, SENIOR_ANNUAL,
    SENIOR_LIFETIME, MILITARY, ACCESS, VOLUNTEER, FOURTH_GRADE} ...
    a valid_from UTC instant, a valid_until UTC instant'.
    """
    now = utcnow()
    if valid_from is None:
        valid_from = iso_utc(now - timedelta(days=1))
    if valid_until is None:
        valid_until = iso_utc(now + timedelta(days=365))
    defaults: Dict[str, Any] = {
        "pass_type": pass_type,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Park — PRD §3.2
# ---------------------------------------------------------------------------
def create_park_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2: 'name (1 through 120 characters, unique), its short
    code (2 through 10 characters of uppercase letters and digits,
    unique, matching the pattern ^[A-Z0-9]+$), its IANA timezone, its
    timed_entry_daily_capacity, and optionally its
    timed_entry_window_minutes (defaulting to 60 when not supplied;
    must evenly divide 1440)'.
    """
    defaults: Dict[str, Any] = {
        "name": random_park_name(),
        "code": random_park_code(),
        "timezone": TEST_DEFAULTS["park_timezone"],
        "timed_entry_daily_capacity":
            TEST_DEFAULTS["park_timed_entry_daily_capacity"],
        "timed_entry_window_minutes": DEFAULT_TIMED_ENTRY_WINDOW_MINUTES,
    }
    defaults.update(overrides)
    return defaults


def patch_park_payload(version: Optional[int] = None,
                       **overrides) -> Dict[str, Any]:
    """PRD §3.2: 'PATCH that accepts an optional version for OCC and an
    optional name, timed_entry_daily_capacity, and
    timed_entry_window_minutes'.
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Campground — PRD §3.2
# ---------------------------------------------------------------------------
def create_campground_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2: 'name unique within that park (1 through 120 characters),
    a standard_site_count and a group_site_count, the per-night cost of
    each site class as nightly_standard_fee_cents and nightly_group_fee_
    cents, an optional max_consecutive_nights (1 through 30, defaulting
    to 14) ... and an optional waitlist_window_hours (1 through 168,
    defaulting to 24)'.
    """
    defaults: Dict[str, Any] = {
        "name": random_campground_name(),
        "standard_site_count": TEST_DEFAULTS["campground_standard_count"],
        "group_site_count": TEST_DEFAULTS["campground_group_count"],
        "nightly_standard_fee_cents": TEST_DEFAULTS["nightly_standard_fee_cents"],
        "nightly_group_fee_cents": TEST_DEFAULTS["nightly_group_fee_cents"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Backcountry zone — PRD §3.2
# ---------------------------------------------------------------------------
def create_backcountry_zone_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2: 'name unique within that park (1 through 80 characters),
    a nightly_quota_people ... an optional ranger_buffer_minutes (0
    through 720, defaulting to 30) ... a per_party_fee_cents flat
    permit fee'.
    """
    defaults: Dict[str, Any] = {
        "name": random_zone_name(),
        "nightly_quota_people": TEST_DEFAULTS["zone_nightly_quota"],
        "per_party_fee_cents": TEST_DEFAULTS["zone_per_party_fee_cents"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Lottery permit — PRD §3.2, §3.6
# ---------------------------------------------------------------------------
def create_lottery_permit_payload(
    lottery_open_at: Optional[str] = None,
    lottery_close_at: Optional[str] = None,
    draw_at: Optional[str] = None,
    hike_date: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: 'four UTC instants — lottery_open_at, lottery_close_at,
    draw_at, and hike_date — and the four numeric inputs that drive
    the draw: daily_slot_count (the total number of award slots offered
    for hike_date, at least 1), per_application_max_party (the per-
    application cap on party_size, 1 through 12, defaulting to 6),
    application_fee_cents (the non-refundable fee charged at application
    submission), and permit_fee_cents (the fee charged per awarded slot
    when the visitor accepts)'.
    """
    now = utcnow()
    if lottery_open_at is None:
        lottery_open_at = iso_utc(now - timedelta(days=2))
    if lottery_close_at is None:
        lottery_close_at = iso_utc(now + timedelta(days=2))
    if draw_at is None:
        draw_at = iso_utc(now + timedelta(days=3))
    if hike_date is None:
        hike_date = iso_utc(now + timedelta(days=10))
    defaults: Dict[str, Any] = {
        "name": random_lottery_name(),
        "lottery_open_at": lottery_open_at,
        "lottery_close_at": lottery_close_at,
        "draw_at": draw_at,
        "hike_date": hike_date,
        "daily_slot_count": TEST_DEFAULTS["lottery_daily_slot_count"],
        "per_application_max_party": 6,
        "application_fee_cents": TEST_DEFAULTS["lottery_application_fee_cents"],
        "permit_fee_cents": TEST_DEFAULTS["lottery_permit_fee_cents"],
    }
    defaults.update(overrides)
    return defaults


def create_lottery_application_payload(
    party_size: int = 2, **overrides,
) -> Dict[str, Any]:
    """PRD §3.6: 'submitting party_size'."""
    defaults: Dict[str, Any] = {"party_size": party_size}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Timed-entry reservation — PRD §3.3
# ---------------------------------------------------------------------------
def create_timed_entry_payload(
    vehicle_plate: Optional[str] = None,
    entry_date_local: Optional[str] = None,
    window_start_local: str = "09:00",
    pass_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'supplying their vehicle_plate (1 through 10 characters,
    uppercased on persist), an entry_date_local, a window_start_local,
    and an optional pass_id'.
    """
    if vehicle_plate is None:
        vehicle_plate = random_plate()
    if entry_date_local is None:
        entry_date_local = date_to_local_str(date.today() + timedelta(days=5))
    payload: Dict[str, Any] = {
        "vehicle_plate": vehicle_plate,
        "entry_date_local": entry_date_local,
        "window_start_local": window_start_local,
    }
    if pass_id is not None:
        payload["pass_id"] = pass_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Campground reservation — PRD §3.4
# ---------------------------------------------------------------------------
def create_campground_reservation_payload(
    site_kind: str = "STANDARD",
    party_size: int = 2,
    check_in_date_local: Optional[str] = None,
    check_out_date_local: Optional[str] = None,
    nights: int = 2,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.4: 'submitting site_kind (drawn from {STANDARD, GROUP}),
    party_size, check_in_date_local, and check_out_date_local'.
    """
    if check_in_date_local is None:
        check_in_date_local = date_to_local_str(date.today() + timedelta(days=30))
    if check_out_date_local is None:
        ci = parse_iso(check_in_date_local + "T00:00:00Z").date()
        check_out_date_local = date_to_local_str(ci + timedelta(days=nights))
    payload: Dict[str, Any] = {
        "site_kind": site_kind,
        "party_size": party_size,
        "check_in_date_local": check_in_date_local,
        "check_out_date_local": check_out_date_local,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Waitlist — PRD §3.5
# ---------------------------------------------------------------------------
def create_waitlist_payload(
    site_kind: str = "STANDARD",
    check_in_date_local: Optional[str] = None,
    nights: int = 2,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'supplying site_kind, check_in_date_local, and nights
    (1 through 14 inclusive)'.
    """
    if check_in_date_local is None:
        check_in_date_local = date_to_local_str(date.today() + timedelta(days=2))
    payload: Dict[str, Any] = {
        "site_kind": site_kind,
        "check_in_date_local": check_in_date_local,
        "nights": nights,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Backcountry permit — PRD §3.7
# ---------------------------------------------------------------------------
def create_backcountry_permit_payload(
    party_size: int = 2,
    entry_datetime_local: Optional[str] = None,
    exit_datetime_local: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.7: 'supplying party_size (1 through 15 inclusive),
    entry_datetime_local, and exit_datetime_local; the latter must be
    strictly after the former'.
    """
    if entry_datetime_local is None:
        entry_datetime_local = iso_utc(utcnow() + timedelta(days=10))
    if exit_datetime_local is None:
        exit_datetime_local = iso_utc(utcnow() + timedelta(days=12))
    payload: Dict[str, Any] = {
        "party_size": party_size,
        "entry_datetime_local": entry_datetime_local,
        "exit_datetime_local": exit_datetime_local,
    }
    payload.update(overrides)
    return payload


__all__ = [
    # time
    "iso_utc", "iso_now", "utcnow", "parse_iso",
    "add_minutes", "add_hours", "add_days", "add_seconds",
    "date_to_local_str", "local_hhmm",
    # random
    "random_suffix", "random_email", "random_park_code",
    "random_park_name", "random_campground_name",
    "random_zone_name", "random_lottery_name", "random_plate",
    # clock
    "clock_advance_payload",
    # visitor / pass
    "create_visitor_payload", "wallet_deposit_payload", "issue_pass_payload",
    # park
    "create_park_payload", "patch_park_payload",
    # campground
    "create_campground_payload",
    # backcountry zone
    "create_backcountry_zone_payload",
    # lottery
    "create_lottery_permit_payload", "create_lottery_application_payload",
    # reservations
    "create_timed_entry_payload",
    "create_campground_reservation_payload",
    "create_waitlist_payload",
    "create_backcountry_permit_payload",
]
