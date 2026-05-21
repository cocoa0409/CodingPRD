"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits
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


def iso_instant_utc(
    year: int, month: int, day: int,
    hour: int = 0, minute: int = 0, second: int = 0,
    millis: int = 0,
) -> str:
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_years(iso_ts: str, years: int) -> str:
    """Leap-year-aware ISO date math — advance whole years."""
    dt = parse_iso(iso_ts)
    try:
        return iso_utc(dt.replace(year=dt.year + years))
    except ValueError:
        # Feb 29 → Feb 28 fallback
        return iso_utc(dt.replace(year=dt.year + years, day=28))


# ---------------------------------------------------------------------------
# TIN generator — PRD §3.1: "exactly nine digits ... unique across the
# system"
# ---------------------------------------------------------------------------
_SUFFIX_CHARS = string.ascii_lowercase + string.digits


def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(_SUFFIX_CHARS, k=length))


_TIN_COUNTER = [0]


def random_tin() -> str:
    """9-digit TIN, unique per process via a monotonic counter combined
    with random padding."""
    _TIN_COUNTER[0] += 1
    n = _TIN_COUNTER[0]
    base = random.randint(100, 899)
    rest = n % 1_000_000
    return f"{base:03d}{rest:06d}"


# ---------------------------------------------------------------------------
# Taxpayer — PRD §3.1
# ---------------------------------------------------------------------------
def create_taxpayer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tin": random_tin(),
        "filing_status": "SINGLE",
        "monthly_disposable_income_cents": 200_000,
    }
    payload.update(overrides)
    return payload


def patch_taxpayer_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: filing_status and monthly_disposable_income_cents are
    mutable. version is optional (OCC)."""
    return {**overrides}


# ---------------------------------------------------------------------------
# Tax Liability — PRD §3.1
# ---------------------------------------------------------------------------
def create_tax_liability_payload(
    taxpayer_id: str,
    *,
    tax_year: int = 2019,
    assessment_date: Optional[str] = None,
    original_assessed_amount_cents: int = 1_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "tax_year": tax_year,
        "assessment_date": assessment_date or "2020-01-01T00:00:00.000Z",
        "original_assessed_amount_cents": original_assessed_amount_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Installment Agreement — PRD §3.4
# ---------------------------------------------------------------------------
def create_installment_agreement_payload(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    proposed_monthly_payment_cents: int = 200_000,
    payment_method: str = "CHECK",
    ddia_bank_account_last4: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "liability_ids": list(liability_ids),
        "proposed_monthly_payment_cents": proposed_monthly_payment_cents,
        "payment_method": payment_method,
    }
    if payment_method == "DDIA":
        # PRD §3.4: "When the payment method is DDIA the body must also
        # supply ddia_bank_account_last4"
        payload["ddia_bank_account_last4"] = (
            ddia_bank_account_last4 or "1234"
        )
    else:
        # PRD §3.4: "for any other payment method ddia_bank_account_last4
        # is null"
        if ddia_bank_account_last4 is not None:
            payload["ddia_bank_account_last4"] = ddia_bank_account_last4
    payload.update(overrides)
    return payload


def record_installment_payment_payload(
    amount_cents: int,
    received_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'Recording an installment receipt ... supplies
    amount_cents (positive integer) and received_at (ISO 8601 UTC).'"""
    payload: Dict[str, Any] = {
        "amount_cents": amount_cents,
        "received_at": received_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payment (general) — PRD §3.5
# ---------------------------------------------------------------------------
def create_payment_payload(
    taxpayer_id: str,
    amount_cents: int,
    received_at: str,
    payment_kind: str,
    *,
    agreement_id: Optional[str] = None,
    oic_id: Optional[str] = None,
    liability_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "amount_cents": amount_cents,
        "received_at": received_at,
        "payment_kind": payment_kind,
    }
    if agreement_id is not None:
        payload["agreement_id"] = agreement_id
    if oic_id is not None:
        payload["oic_id"] = oic_id
    if liability_ids is not None:
        payload["liability_ids"] = list(liability_ids)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Offer in Compromise — PRD §3.8
# ---------------------------------------------------------------------------
def create_offer_in_compromise_payload(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    offer_amount_cents: int = 1_500_000,
    schedule_months: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "liability_ids": list(liability_ids),
        "offer_amount_cents": offer_amount_cents,
        "schedule_months": schedule_months,
    }
    payload.update(overrides)
    return payload


def decide_offer_in_compromise_payload(decision: str,
                                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'Decide ... carries a body decision of ACCEPT or
    REJECT.'"""
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Federal Tax Lien — PRD §3.7
# ---------------------------------------------------------------------------
def create_lien_payload(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    filed_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "liability_ids": list(liability_ids),
        "filed_date": filed_date or iso_now(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CNC — PRD §3.11
# ---------------------------------------------------------------------------
def create_cnc_payload(
    taxpayer_id: str,
    liability_ids: List[str],
    *,
    hardship_reason: str = "NEGATIVE_DISPOSABLE_INCOME",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "taxpayer_id": taxpayer_id,
        "liability_ids": list(liability_ids),
        "hardship_reason": hardship_reason,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reconsideration — PRD §3.10
# ---------------------------------------------------------------------------
def create_reconsideration_payload(
    agreement_id: str,
    *,
    reason: str = "MISSED_PAYMENT_CURE",
    prior_request_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "agreement_id": agreement_id,
        "reason": reason,
    }
    if prior_request_id is not None:
        payload["prior_request_id"] = prior_request_id
    payload.update(overrides)
    return payload


def decide_reconsideration_payload(status: str,
                                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.10: 'an IRSOfficer decides the reconsideration with a body
    status of APPROVED or DENIED.'"""
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock — PRD §3.2
# ---------------------------------------------------------------------------
def clock_advance_payload(target_timestamp: str) -> Dict[str, Any]:
    """PRD §4: '/_clock/advance ... input: target_timestamp.'"""
    return {"target_timestamp": target_timestamp}


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "parse_iso",
    "add_days",
    "add_seconds",
    "add_years",
    "random_suffix",
    "random_tin",
    "create_taxpayer_payload",
    "patch_taxpayer_payload",
    "create_tax_liability_payload",
    "create_installment_agreement_payload",
    "record_installment_payment_payload",
    "create_payment_payload",
    "create_offer_in_compromise_payload",
    "decide_offer_in_compromise_payload",
    "create_lien_payload",
    "create_cnc_payload",
    "create_reconsideration_payload",
    "decide_reconsideration_payload",
    "clock_advance_payload",
]
