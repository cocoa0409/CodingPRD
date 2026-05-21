"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally
omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.8: all monetary values are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_MONTHLY_FSA_CAP_CENTS,
    TEST_DEFAULTS,
)


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


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_email() -> str:
    return f"rider-{random_suffix()}@example.test"


def unique_idempotency_key(prefix: str = "k") -> str:
    return f"{prefix}-{random_suffix(10)}"


def unique_device_fingerprint(prefix: str = "dev") -> str:
    return f"{prefix}-{random_suffix(12)}"


# ---------------------------------------------------------------------------
# Rider — POST /transit/riders
# ---------------------------------------------------------------------------
def create_rider_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or TEST_DEFAULTS["RIDER_FULL_NAME"],
        "email": email or unique_email(),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Employer — POST /transit/employers
# ---------------------------------------------------------------------------
def create_employer_payload(
    *,
    legal_name: Optional[str] = None,
    monthly_contribution_cap_cents: int = DEFAULT_MONTHLY_FSA_CAP_CENTS,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name or TEST_DEFAULTS["EMPLOYER_LEGAL_NAME"],
        "monthly_contribution_cap_cents": monthly_contribution_cap_cents,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# FareCard — POST /transit/cards
# ---------------------------------------------------------------------------
def create_card_payload(
    *,
    rider_id: str,
    discount_class: str = "STANDARD",
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rider_id": rider_id,
        "discount_class": discount_class,
        "valid_from": valid_from or "2026-01-01T00:00:00.000Z",
        "valid_until": valid_until or "2026-12-31T23:59:59.000Z",
    }
    payload.update(extra)
    return payload


def topup_card_payload(*, amount_cents: int,
                       version: Optional[int] = None,
                       **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ReducedFareCertificate — POST /transit/reduced-fare-certificates
# ---------------------------------------------------------------------------
def create_reduced_fare_certificate_payload(
    *,
    rider_id: str,
    program_type: str = "SENIOR",
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rider_id": rider_id,
        "program_type": program_type,
        "valid_from": valid_from or "2026-01-01T00:00:00.000Z",
        "valid_until": valid_until or "2027-01-01T00:00:00.000Z",
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# LowIncomeVerification — POST /transit/low-income-verifications
# ---------------------------------------------------------------------------
def create_low_income_verification_payload(
    *,
    rider_id: str,
    declared_annual_income_cents: int = 2_500_000,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rider_id": rider_id,
        "declared_annual_income_cents": declared_annual_income_cents,
    }
    payload.update(extra)
    return payload


def approve_low_income_verification_payload(
    *,
    verified_annual_income_cents: int,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "verified_annual_income_cents": verified_annual_income_cents,
    }
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# MobilePaymentToken — POST /transit/mobile-tokens
# ---------------------------------------------------------------------------
def create_mobile_token_payload(
    *,
    rider_id: str,
    wallet_provider: str = "APPLE_PAY",
    device_fingerprint: Optional[str] = None,
    bound_card_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rider_id": rider_id,
        "wallet_provider": wallet_provider,
        "device_fingerprint": (
            device_fingerprint or unique_device_fingerprint()
        ),
    }
    if bound_card_id is not None:
        payload["bound_card_id"] = bound_card_id
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Trip — POST /transit/trips
# ---------------------------------------------------------------------------
def create_trip_payload(
    *,
    card_id: str,
    idempotency_key: Optional[str] = None,
    tap_in_at: Optional[str] = None,
    mobile_token_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "card_id": card_id,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
        "tap_in_at": tap_in_at or iso_now(),
    }
    if mobile_token_id is not None:
        payload["mobile_token_id"] = mobile_token_id
    payload.update(extra)
    return payload


def tap_out_payload(
    *,
    tap_out_at: str,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"tap_out_at": tap_out_at}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# CommuterBenefitAccount + FSAContribution — PRD §3.9
# ---------------------------------------------------------------------------
def create_fsa_account_payload(
    *,
    rider_id: str,
    employer_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "rider_id": rider_id,
        "employer_id": employer_id,
    }
    payload.update(extra)
    return payload


def create_fsa_contribution_payload(
    *,
    account_id: str,
    amount_cents: int,
    contribution_month: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "contribution_month": contribution_month,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# DisputeCase — PRD §3.7
# ---------------------------------------------------------------------------
def create_dispute_payload(
    *,
    trip_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"trip_id": trip_id}
    payload.update(extra)
    return payload


def resolve_dispute_payload(
    *,
    decision: str,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Clock — POST /transit/_clock/advance
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# version-only — for /suspend, /reactivate, /close, /approve, /revoke,
# /reverse, /claim, /request-evidence, top-up etc when supplying an
# optional OCC version.
# ---------------------------------------------------------------------------
def version_payload(version: Optional[int] = None,
                    **extra: Any) -> Optional[Dict[str, Any]]:
    if version is None and not extra:
        return None
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


__all__ = [
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_days",
    "random_suffix", "unique_email",
    "unique_idempotency_key", "unique_device_fingerprint",
    "create_rider_payload",
    "create_employer_payload",
    "create_card_payload", "topup_card_payload",
    "create_reduced_fare_certificate_payload",
    "create_low_income_verification_payload",
    "approve_low_income_verification_payload",
    "create_mobile_token_payload",
    "create_trip_payload", "tap_out_payload",
    "create_fsa_account_payload",
    "create_fsa_contribution_payload",
    "create_dispute_payload",
    "resolve_dispute_payload",
    "clock_advance_payload",
    "version_payload",
]
