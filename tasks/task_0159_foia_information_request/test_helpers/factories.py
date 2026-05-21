"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system / append-only fields are
intentionally omitted.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.9: all monetary values are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def unique_email() -> str:
    return f"r-{random_suffix()}@example.test"


def unique_third_party_id(prefix: str = "tp") -> str:
    return f"{prefix}-{random_suffix()}"


# ---------------------------------------------------------------------------
# Requester — POST /foia/requesters
# ---------------------------------------------------------------------------
def create_requester_payload(
    *,
    full_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    requester_tier: str = "COMMERCIAL",
    tier_justification: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or TEST_DEFAULTS["REQUESTER_FULL_NAME"],
        "contact_email": contact_email or unique_email(),
        "requester_tier": requester_tier,
    }
    if tier_justification is not None:
        payload["tier_justification"] = tier_justification
    elif requester_tier != "COMMERCIAL":
        # PRD §3.1: non-commercial tiers require non-empty justification.
        payload["tier_justification"] = (
            "Qualifying use under non-commercial tier."
        )
    payload.update(extra)
    return payload


def patch_requester_payload(
    *,
    version: Optional[int] = None,
    requester_tier: Optional[str] = None,
    tier_justification: Optional[str] = None,
    contact_email: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if requester_tier is not None:
        payload["requester_tier"] = requester_tier
    if tier_justification is not None:
        payload["tier_justification"] = tier_justification
    if contact_email is not None:
        payload["contact_email"] = contact_email
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Request — POST /foia/requests
# ---------------------------------------------------------------------------
def create_request_payload(
    *,
    requester_id: str,
    subject_summary: Optional[str] = None,
    fee_waiver_requested: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requester_id": requester_id,
        "subject_summary": subject_summary or TEST_DEFAULTS["REQUEST_SUBJECT_SUMMARY"],
    }
    if fee_waiver_requested is not None:
        payload["fee_waiver_requested"] = fee_waiver_requested
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Tolling — POST /foia/requests/{id}/start-tolling
# ---------------------------------------------------------------------------
def start_tolling_payload(*, reason: Optional[str] = None,
                          **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason": reason or TEST_DEFAULTS["TOLLING_REASON"],
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Glomar — POST /foia/requests/{id}/issue-glomar
# ---------------------------------------------------------------------------
def issue_glomar_payload(
    *,
    glomar_exemption_basis: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "glomar_exemption_basis": (
            list(glomar_exemption_basis)
            if glomar_exemption_basis is not None
            else ["B1"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ResponsiveRecord — POST /foia/responsive-records
# ---------------------------------------------------------------------------
def create_responsive_record_payload(
    *,
    request_id: str,
    title: Optional[str] = None,
    page_count: int = 10,
    contains_third_party_info: bool = False,
    third_party_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "title": title or f"{TEST_DEFAULTS['RECORD_TITLE']} {random_suffix(4)}",
        "page_count": page_count,
        "contains_third_party_info": contains_third_party_info,
    }
    if contains_third_party_info or third_party_id is not None:
        payload["third_party_id"] = third_party_id
    payload.update(extra)
    return payload


def patch_record_disposition_payload(
    *,
    disposition: str,
    version: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "disposition": disposition,
        "version": version,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ExemptionClaim — POST /foia/exemption-claims
# ---------------------------------------------------------------------------
def create_exemption_claim_payload(
    *,
    record_id: str,
    exemption_code: str = "B5",
    redaction_scope: str = "FULL",
    rationale: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "record_id": record_id,
        "exemption_code": exemption_code,
        "redaction_scope": redaction_scope,
        "rationale": rationale or TEST_DEFAULTS["EXEMPTION_RATIONALE"],
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ThirdPartyNotice — POST /foia/third-party-notices
# ---------------------------------------------------------------------------
def create_third_party_notice_payload(
    *,
    request_id: str,
    record_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "record_id": record_id,
    }
    payload.update(extra)
    return payload


def object_third_party_payload(
    *,
    objection_grounds: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "objection_grounds": (
            objection_grounds or TEST_DEFAULTS["OBJECTION_GROUNDS"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Appeal — POST /foia/appeals + /decide
# ---------------------------------------------------------------------------
def create_appeal_payload(
    *,
    request_id: str,
    appellant_role: str = "REQUESTER",
    grounds: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "appellant_role": appellant_role,
        "grounds": grounds or TEST_DEFAULTS["APPEAL_GROUNDS"],
    }
    payload.update(extra)
    return payload


def decide_appeal_payload(*, decision: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# FeeAssessment — POST /foia/fee-assessments
# ---------------------------------------------------------------------------
def create_fee_assessment_payload(
    *,
    request_id: str,
    estimated_pages: int = 150,
    estimated_search_hours: float = 4,
    estimated_review_hours: float = 2,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "estimated_pages": estimated_pages,
        "estimated_search_hours": estimated_search_hours,
        "estimated_review_hours": estimated_review_hours,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Clock — POST /foia/_clock/advance
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to_iso_datetime: str,
                          **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso_datetime": to_iso_datetime}
    payload.update(extra)
    return payload


__all__ = [
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_days",
    "random_suffix", "unique_email", "unique_third_party_id",
    "create_requester_payload",
    "patch_requester_payload",
    "create_request_payload",
    "start_tolling_payload",
    "issue_glomar_payload",
    "create_responsive_record_payload",
    "patch_record_disposition_payload",
    "create_exemption_claim_payload",
    "create_third_party_notice_payload",
    "object_third_party_payload",
    "create_appeal_payload",
    "decide_appeal_payload",
    "create_fee_assessment_payload",
    "clock_advance_payload",
]
