"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.2 / §2.4: timestamps are ISO 8601 UTC with three fractional
digits.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp / random helpers — PRD §2.2 / §2.4 ISO 8601 with 3 fractional
# digits.
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


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(
        base + timedelta(days=days, hours=hours, minutes=minutes),
    )


def parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


# ===========================================================================
# Clock advance — PRD §2.11, §3.16
# ===========================================================================
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    """PRD §3.16: "The CourtClerk may advance the logical clock to a
    supplied to_timestamp instant; the request body for the
    clock-advance capability carries that single field."
    """
    return {"to_timestamp": to_timestamp}


# ===========================================================================
# Estate — PRD §3.1
# ===========================================================================
def create_estate_payload(
    *,
    testator_name: Optional[str] = None,
    domicile_state: Optional[str] = None,
    filing_court_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "A new estate is created by an Executor posting
    testator_name, domicile_state (the two-letter US state code where
    probate will be filed), and filing_court_id".
    """
    body: Dict[str, Any] = {
        "testator_name": (
            testator_name if testator_name is not None
            else f"{TEST_DEFAULTS['TESTATOR_NAME']} {random_suffix(4)}"
        ),
        "domicile_state": (
            domicile_state if domicile_state is not None
            else TEST_DEFAULTS["DOMICILE_STATE"]
        ),
        "filing_court_id": (
            filing_court_id if filing_court_id is not None
            else f"{TEST_DEFAULTS['FILING_COURT_ID']}-{random_suffix(4)}"
        ),
    }
    body.update(overrides)
    return body


def estate_state_payload(to_status: str, *,
                         version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Asset — PRD §3.1, §3.4
# ===========================================================================
def create_asset_payload(
    *,
    asset_class: str = "FINANCIAL",
    description: Optional[str] = None,
    declared_value_cents: int = 100_000_00,
    requires_poa_for_mutation: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "Asset declarations specify an asset_class chosen from
    REAL_ESTATE, FINANCIAL, PERSONAL_PROPERTY, or DIGITAL; a free-text
    description up to 500 characters; a non-negative
    declared_value_cents representing the executor's initial estimate;
    and an optional requires_poa_for_mutation flag."
    """
    body: Dict[str, Any] = {
        "asset_class": asset_class,
        "description": (
            description if description is not None
            else f"{TEST_DEFAULTS['ASSET_DESCRIPTION']} {random_suffix(4)}"
        ),
        "declared_value_cents": declared_value_cents,
    }
    if requires_poa_for_mutation is not None:
        body["requires_poa_for_mutation"] = requires_poa_for_mutation
    body.update(overrides)
    return body


def asset_state_payload(to_status: str, *,
                        appraised_value_cents: Optional[int] = None,
                        distribution_id: Optional[str] = None,
                        version: Optional[int] = None,
                        **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if appraised_value_cents is not None:
        body["appraised_value_cents"] = appraised_value_cents
    if distribution_id is not None:
        body["distribution_id"] = distribution_id
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Beneficiary — PRD §3.1, §3.9
# ===========================================================================
def create_beneficiary_payload(
    *,
    full_name: Optional[str] = None,
    relationship: str = "CHILD",
    is_minor: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "Beneficiaries carry a full_name, a relationship
    chosen from SPOUSE, CHILD, PARENT, SIBLING, CHARITY, or OTHER, and
    a boolean is_minor (true if the beneficiary is under 18 at the
    moment of estate filing)."
    """
    body: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"{TEST_DEFAULTS['BENEFICIARY_NAME']} {random_suffix(4)}"
        ),
        "relationship": relationship,
    }
    if is_minor is not None:
        body["is_minor"] = is_minor
    body.update(overrides)
    return body


def beneficiary_state_payload(to_status: str, *,
                              version: Optional[int] = None,
                              **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Designation — PRD §3.6
# ===========================================================================
def create_designation_payload(
    *,
    asset_id: str,
    beneficiary_id: str,
    share_basis_points: int,
    priority_rank: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.6: "Each designation supplies an asset_id, a
    beneficiary_id ..., a share_basis_points integer in the range 0
    to 10000, and a priority_rank integer that breaks ties when the
    waterfall fires."
    """
    body: Dict[str, Any] = {
        "asset_id": asset_id,
        "beneficiary_id": beneficiary_id,
        "share_basis_points": share_basis_points,
        "priority_rank": priority_rank,
    }
    body.update(overrides)
    return body


# ===========================================================================
# Fiduciary — PRD §3.1
# ===========================================================================
def create_fiduciary_payload(
    *,
    scope_type: str = "EXECUTOR",
    full_name: Optional[str] = None,
    contact_user_id: Optional[str] = None,
    bond_amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "Each Fiduciary row carries an estate_id, a
    scope_type from EXECUTOR | TRUSTEE | GUARDIAN, a full_name, and a
    contact_user_id (the X-User-ID that this fiduciary will use to
    sign requests, used as the ownership anchor for self-only
    operations). The optional bond_amount_cents declares the court
    bond the nominee proposes to post."
    """
    body: Dict[str, Any] = {
        "scope_type": scope_type,
        "full_name": (
            full_name if full_name is not None
            else f"{TEST_DEFAULTS['FIDUCIARY_NAME']} {random_suffix(4)}"
        ),
        "contact_user_id": (
            contact_user_id if contact_user_id is not None
            else f"signer-{random_suffix(8)}"
        ),
    }
    if bond_amount_cents is not None:
        body["bond_amount_cents"] = bond_amount_cents
    body.update(overrides)
    return body


def fiduciary_state_payload(to_status: str, *,
                            version: Optional[int] = None,
                            **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Guardianship — PRD §3.1
# ===========================================================================
def create_guardianship_payload(
    *,
    minor_beneficiary_id: str,
    guardian_fiduciary_id: str,
    effective_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "The creation payload includes minor_beneficiary_id
    (a Beneficiary whose is_minor is true), guardian_fiduciary_id (a
    Fiduciary with scope_type GUARDIAN), and an effective_at ISO 8601
    UTC wall-clock instant."
    """
    body: Dict[str, Any] = {
        "minor_beneficiary_id": minor_beneficiary_id,
        "guardian_fiduciary_id": guardian_fiduciary_id,
        "effective_at": effective_at,
    }
    body.update(overrides)
    return body


def guardianship_state_payload(to_status: str, *,
                               version: Optional[int] = None,
                               **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# HIPAA — PRD §3.1
# ===========================================================================
def create_hipaa_payload(
    *,
    authorized_recipient: Optional[str] = None,
    scope: str = "ALL",
    signed_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "HIPAA authorizations name an authorized_recipient,
    a scope chosen from MEDICAL_RECORDS, MENTAL_HEALTH,
    SUBSTANCE_ABUSE, or ALL, a signed_at timestamp, and an optional
    expires_at."
    """
    body: Dict[str, Any] = {
        "authorized_recipient": (
            authorized_recipient if authorized_recipient is not None
            else TEST_DEFAULTS["HIPAA_RECIPIENT"]
        ),
        "scope": scope,
        "signed_at": (
            signed_at if signed_at is not None else iso_now()
        ),
    }
    if expires_at is not None:
        body["expires_at"] = expires_at
    body.update(overrides)
    return body


def hipaa_state_payload(to_status: str, *,
                        version: Optional[int] = None,
                        **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# PowerOfAttorney — PRD §3.1
# ===========================================================================
def create_poa_payload(
    *,
    poa_type: str = "FINANCIAL_DURABLE",
    agent_fiduciary_id: str,
    asset_class_scope: Optional[List[str]] = None,
    effective_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "Powers of Attorney drafted in this phase declare a
    poa_type from FINANCIAL_DURABLE, MEDICAL, or LIMITED; an
    agent_fiduciary_id naming the agent; an asset_class_scope array
    containing the subset of {REAL_ESTATE, FINANCIAL,
    PERSONAL_PROPERTY, DIGITAL} the POA covers ...; and an
    effective_at timestamp."
    """
    body: Dict[str, Any] = {
        "poa_type": poa_type,
        "agent_fiduciary_id": agent_fiduciary_id,
        "asset_class_scope": (
            asset_class_scope if asset_class_scope is not None
            else ["FINANCIAL"]
        ),
        "effective_at": (
            effective_at if effective_at is not None
            else iso_offset(days=1)
        ),
    }
    body.update(overrides)
    return body


def poa_state_payload(to_status: str, *,
                      version: Optional[int] = None,
                      **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# EndOfLifeDirective — PRD §3.1, §3.13
# ===========================================================================
def create_directive_payload(
    *,
    directive_type: str = "LIVING_WILL",
    instructions: Optional[str] = None,
    requires_hipaa_scope: str = "ALL",
    supersedes_directive_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: "End-of-life directives declare a directive_type
    from LIVING_WILL, DNR, DNI, or POLST; free-text instructions up
    to 4000 characters; and a requires_hipaa_scope value naming the
    minimum HIPAA scope ... required to execute the directive.
    Optionally supersedes_directive_id points at an earlier directive."
    """
    body: Dict[str, Any] = {
        "directive_type": directive_type,
        "instructions": (
            instructions if instructions is not None
            else TEST_DEFAULTS["DIRECTIVE_INSTRUCTIONS"]
        ),
        "requires_hipaa_scope": requires_hipaa_scope,
    }
    if supersedes_directive_id is not None:
        body["supersedes_directive_id"] = supersedes_directive_id
    body.update(overrides)
    return body


def directive_state_payload(to_status: str, *,
                            version: Optional[int] = None,
                            **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# ProbateFiling — PRD §3.7
# ===========================================================================
def create_filing_payload(
    *,
    filing_type: str,
    filed_by_fiduciary_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.7: "Each filing carries a filed_by_fiduciary_id
    identifying the fiduciary who submitted it."
    """
    body: Dict[str, Any] = {
        "filing_type": filing_type,
        "filed_by_fiduciary_id": filed_by_fiduciary_id,
    }
    body.update(overrides)
    return body


def filing_state_payload(to_status: str, *,
                         rejection_reason: Optional[str] = None,
                         version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if rejection_reason is not None:
        body["rejection_reason"] = rejection_reason
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Distribution — PRD §3.11
# ===========================================================================
def distribution_state_payload(to_status: str, *,
                               actual_amount_cents: Optional[int] = None,
                               version: Optional[int] = None,
                               **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"to_status": to_status}
    if actual_amount_cents is not None:
        body["actual_amount_cents"] = actual_amount_cents
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "random_suffix",
    "clock_advance_payload",
    "create_estate_payload",
    "estate_state_payload",
    "create_asset_payload",
    "asset_state_payload",
    "create_beneficiary_payload",
    "beneficiary_state_payload",
    "create_designation_payload",
    "create_fiduciary_payload",
    "fiduciary_state_payload",
    "create_guardianship_payload",
    "guardianship_state_payload",
    "create_hipaa_payload",
    "hipaa_state_payload",
    "create_poa_payload",
    "poa_state_payload",
    "create_directive_payload",
    "directive_state_payload",
    "create_filing_payload",
    "filing_state_payload",
    "distribution_state_payload",
]
