"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON body shape the PRD declares for the
request (PRD §3 narratives + §4 endpoint table). Tests pass overrides
for the values they want to control. Only PRD-declared input fields are
produced; computed / system fields are intentionally omitted.

PRD §2.10: timestamps are ISO 8601 UTC with three fractional digits.
PRD §3.1: `date_of_birth` is a calendar date `YYYY-MM-DD`.
"""
from __future__ import annotations

import hashlib
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.10 ISO 8601 UTC with three fractional digits.
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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00'."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def add_years(iso_ts: str, years: int) -> str:
    dt = parse_iso(iso_ts)
    try:
        new_dt = dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap.
        new_dt = dt.replace(year=dt.year + years, day=28)
    return iso_utc(new_dt)


def date_only_string(year: int, month: int, day: int) -> str:
    """Render a calendar date as ISO `YYYY-MM-DD`."""
    return f"{year:04d}-{month:02d}-{day:02d}"


def add_business_days(iso_ts: str, business_days: int) -> str:
    """Add `business_days` to `iso_ts` skipping Saturdays and Sundays.

    PRD §2.10: "the day the Pre-Adverse notice is sent counts as day 0
    and is excluded from the elapsed tally". This helper mirrors that
    semantic: starting from `iso_ts`, advance until exactly
    `business_days` weekday-days have been counted forward. weekday() ==
    5 -> Saturday, 6 -> Sunday.
    """
    dt = parse_iso(iso_ts)
    counted = 0
    while counted < business_days:
        dt = dt + timedelta(days=1)
        if dt.weekday() < 5:
            counted += 1
    return iso_utc(dt)


# ---------------------------------------------------------------------------
# Random suffix — cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_email(prefix: str = "candidate") -> str:
    return f"{prefix}.{random_suffix(10)}@example.test"


def unique_full_name(prefix: str = "Test Candidate") -> str:
    return f"{prefix} {random_suffix(6)}"


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unique_disclosure_hash(prefix: str = "disclosure") -> str:
    """Return a deterministic-shape SHA-256 hex string."""
    return sha256_hex(f"{prefix}-{random_suffix(16)}")


# ---------------------------------------------------------------------------
# Candidate — POST /fcra/candidates (PRD §3.1)
# Required input: full_name, email, residence_jurisdiction, date_of_birth.
# Optional input: salary_history (only valid when jurisdiction's
# salary_history_ban is FALSE).
# ---------------------------------------------------------------------------
def create_candidate_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    residence_jurisdiction: str = "CA",
    date_of_birth: str = "1990-01-15",
    salary_history: Optional[int] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name(),
        "email": email or unique_email(),
        "residence_jurisdiction": residence_jurisdiction,
        "date_of_birth": date_of_birth,
    }
    if salary_history is not None:
        payload["salary_history"] = salary_history
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def update_candidate_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    salary_history: Optional[int] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PATCH /fcra/candidates/{id} — partial body, OCC via version
    (PRD §2.5)."""
    payload: Dict[str, Any] = {}
    if full_name is not None:
        payload["full_name"] = full_name
    if email is not None:
        payload["email"] = email
    if salary_history is not None:
        payload["salary_history"] = salary_history
    if version is not None:
        payload["version"] = version
    return payload


# ---------------------------------------------------------------------------
# ConsentDisclosure — POST /fcra/candidates/{id}/consent (PRD §3.2)
# Required: disclosure_text_hash, consent_signature,
# consent_timestamp, disclosure_presented_at.
# ---------------------------------------------------------------------------
def record_consent_payload(
    *,
    disclosure_text_hash: Optional[str] = None,
    consent_signature: str = "Signed: I, the candidate, consent.",
    consent_timestamp: Optional[str] = None,
    disclosure_presented_at: Optional[str] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    # PRD §3.2: disclosure_presented_at <= consent_timestamp <= now.
    # Sample wall-clock once so both default timestamps share the same
    # instant (otherwise two separate `utcnow()` calls can produce
    # `disclosure_presented_at` strictly later than `consent_timestamp`
    # which violates the temporal contract).
    _now_iso = iso_utc(utcnow())
    payload: Dict[str, Any] = {
        "disclosure_text_hash":
            disclosure_text_hash or unique_disclosure_hash(),
        "consent_signature": consent_signature,
        "consent_timestamp":
            consent_timestamp or _now_iso,
        "disclosure_presented_at":
            disclosure_presented_at or _now_iso,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# JurisdictionPolicy — PUT /fcra/jurisdiction-policies/{code}
# Required: criminal_lookback_years, salary_history_ban,
# ban_the_box_stage, adverse_action_waiting_business_days.
# ---------------------------------------------------------------------------
def upsert_jurisdiction_policy_payload(
    *,
    criminal_lookback_years: int = 7,
    salary_history_ban: bool = False,
    ban_the_box_stage: str = "PRE_OFFER",
    adverse_action_waiting_business_days: int = 5,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "criminal_lookback_years": criminal_lookback_years,
        "salary_history_ban": salary_history_ban,
        "ban_the_box_stage": ban_the_box_stage,
        "adverse_action_waiting_business_days":
            adverse_action_waiting_business_days,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# BackgroundCheckOrder — POST /fcra/orders (PRD §3.3)
# Required: candidate_id, consent_disclosure_id, stage_at_order,
# requested_packages.
# ---------------------------------------------------------------------------
def create_order_payload(
    *,
    candidate_id: str,
    consent_disclosure_id: str,
    stage_at_order: str = "POST_OFFER",
    requested_packages: Optional[List[str]] = None,
    salary_history: Optional[int] = None,
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    if requested_packages is None:
        requested_packages = ["CRIMINAL", "MVR", "EDUCATION"]
    payload: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "consent_disclosure_id": consent_disclosure_id,
        "stage_at_order": stage_at_order,
        "requested_packages": list(requested_packages),
    }
    if salary_history is not None:
        payload["salary_history"] = salary_history
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# VerificationItem return — POST /fcra/verification-items/{id}/return
# Required: raw_finding (kind-specific shape per PRD §3.4).
# ---------------------------------------------------------------------------
def criminal_raw_finding(
    *,
    conviction_date: str,
    severity: str = "MISDEMEANOR",
) -> Dict[str, Any]:
    """PRD §3.4: "a `CRIMINAL` finding carries a `conviction_date` and
    a `severity` of `INFRACTION`, `MISDEMEANOR`, or `FELONY`".
    """
    return {
        "conviction_date": conviction_date,
        "severity": severity,
    }


def mvr_raw_finding(
    *,
    violations_3yr: int = 0,
    license_status: str = "VALID",
) -> Dict[str, Any]:
    """PRD §3.4: "an `MVR` finding carries a `violations_3yr` integer
    and a `license_status`".
    """
    return {
        "violations_3yr": violations_3yr,
        "license_status": license_status,
    }


def education_raw_finding(
    *,
    institution: str = "Test University",
    claim_verified: bool = True,
) -> Dict[str, Any]:
    """PRD §3.4: "an `EDUCATION` finding carries an `institution` and a
    `claim_verified` boolean".
    """
    return {
        "institution": institution,
        "claim_verified": claim_verified,
    }


def return_item_payload(
    *,
    raw_finding: Dict[str, Any],
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"raw_finding": raw_finding}
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Dispute — POST /fcra/disputes (PRD §3.7)
# Required: verification_item_id, reason_text (1..1000 chars).
# ---------------------------------------------------------------------------
def create_dispute_payload(
    *,
    verification_item_id: str,
    reason_text: str = "I dispute the recorded finding.",
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "verification_item_id": verification_item_id,
        "reason_text": reason_text,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def resolve_dispute_payload(
    *,
    status: str,
    resolution_note: str = "Resolved by adjudicator.",
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """status MUST be 'UPHELD' or 'OVERTURNED' (PRD §3.7)."""
    payload: Dict[str, Any] = {
        "status": status,
        "resolution_note": resolution_note,
    }
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Rework — POST /fcra/orders/{id}/request-rework (PRD §3.7)
# Required: target_item_ids.
# ---------------------------------------------------------------------------
def request_rework_payload(
    *,
    target_item_ids: List[str],
    omit: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_item_ids": list(target_item_ids)}
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — POST /fcra/_clock/advance (PRD §3.10)
# Required: seconds.
# ---------------------------------------------------------------------------
def clock_advance_payload(*, seconds: int) -> Dict[str, Any]:
    """PRD §3.10: "The clock-advance capability accepts a `seconds`
    integer and pushes the server's current time forward by that many
    seconds; no automatic state transitions fire as a result."
    """
    return {"seconds": seconds}


__all__ = [
    # Time helpers
    "iso_utc", "utcnow", "parse_iso",
    "add_seconds", "add_minutes", "add_hours", "add_days", "add_years",
    "add_business_days",
    "date_only_string",
    # Uniqueness / hashing
    "random_suffix",
    "unique_email", "unique_full_name", "unique_disclosure_hash",
    "sha256_hex",
    # Payload factories
    "create_candidate_payload",
    "update_candidate_payload",
    "record_consent_payload",
    "upsert_jurisdiction_policy_payload",
    "create_order_payload",
    "criminal_raw_finding",
    "mvr_raw_finding",
    "education_raw_finding",
    "return_item_payload",
    "create_dispute_payload",
    "resolve_dispute_payload",
    "request_rework_payload",
    "clock_advance_payload",
]
