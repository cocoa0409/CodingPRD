"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD declares for the
request body. Only PRD-declared input fields are produced; computed and
system-managed fields are intentionally omitted so the implementation
cannot accidentally accept them as inputs.

PRD §2.9: timestamps are ISO 8601 UTC strings with three fractional
digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.9 format with three fractional digits.
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
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp back into a timezone-aware
    datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def iso_date(d: date) -> str:
    return d.isoformat()


# ---------------------------------------------------------------------------
# Random utilities.
# ---------------------------------------------------------------------------
_ALPHANUM_UPPER = string.ascii_uppercase + string.digits
_DIGITS = string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM_UPPER, k=n))


def random_member_id() -> str:
    """Unique insurance member identifier — PRD §3.1: unique across the
    system. No format is specified, so a prefixed random suffix is
    sufficient."""
    return f"MEM-{random_suffix(10)}"


def random_npi() -> str:
    """PRD §3.1: "the npi (the National Provider Identifier — exactly
    10 digits and unique across the system)."
    """
    return "".join(random.choices(_DIGITS, k=10))


def random_catalog_code(kind: str = "SERVICE") -> str:
    """A unique-enough catalog code; PRD §3.1 calls it a CPT/HCPCS/NDC
    string but does not pin a format beyond uniqueness."""
    if kind == "DRUG":
        return f"NDC-{random_suffix(8)}"
    return f"CPT-{random_suffix(6)}"


def random_uri(prefix: str = "s3://") -> str:
    """Opaque storage reference per PRD §3.3."""
    return f"{prefix}bucket/{random_suffix(12)}.pdf"


# ---------------------------------------------------------------------------
# Patient — PRD §3.1 / §4
# ---------------------------------------------------------------------------
def create_patient_payload(
    *,
    member_id: Optional[str] = None,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    plan_type: str = "COMMERCIAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /patients — PlatformAdmin only.

    PRD §3.1: required input fields are member_id (unique), full_name,
    date_of_birth (ISO 8601 calendar date), and plan_type (COMMERCIAL,
    MEDICARE, MEDICAID).
    """
    payload: Dict[str, Any] = {
        "member_id": (
            member_id if member_id is not None else random_member_id()
        ),
        "full_name": (
            full_name if full_name is not None
            else f"Patient {random_suffix(4)}"
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None else "1980-01-15"
        ),
        "plan_type": plan_type,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Provider — PRD §3.1 / §4
# ---------------------------------------------------------------------------
def create_provider_payload(
    *,
    npi: Optional[str] = None,
    full_name: Optional[str] = None,
    specialty: str = "CARDIOLOGY",
    in_network: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /providers — PlatformAdmin only.

    PRD §3.1: required input fields are npi (exactly 10 digits, unique),
    full_name, specialty. in_network is optional and defaults to true.
    """
    payload: Dict[str, Any] = {
        "npi": npi if npi is not None else random_npi(),
        "full_name": (
            full_name if full_name is not None
            else f"Provider {random_suffix(4)}"
        ),
        "specialty": specialty,
    }
    if in_network is not None:
        payload["in_network"] = in_network
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServiceCatalogItem — PRD §3.1 / §4
# ---------------------------------------------------------------------------
def create_service_catalog_item_payload(
    *,
    code: Optional[str] = None,
    kind: str = "SERVICE",
    name: Optional[str] = None,
    requires_pa: Optional[bool] = None,
    standard_sla_hours: Optional[int] = None,
    expedited_sla_hours: Optional[int] = None,
    approval_validity_days: Optional[int] = None,
    required_evidence_categories: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /service-catalog-items — PlatformAdmin only.

    PRD §3.1: required input fields are code (unique CPT/HCPCS/NDC),
    kind (SERVICE | DRUG), name. Optional fields with PRD defaults:
    requires_pa (true), standard_sla_hours (336), expedited_sla_hours
    (72), approval_validity_days (90), required_evidence_categories.
    """
    payload: Dict[str, Any] = {
        "code": code if code is not None else random_catalog_code(kind),
        "kind": kind,
        "name": (
            name if name is not None
            else f"Service {random_suffix(4)}"
        ),
    }
    if requires_pa is not None:
        payload["requires_pa"] = requires_pa
    if standard_sla_hours is not None:
        payload["standard_sla_hours"] = standard_sla_hours
    if expedited_sla_hours is not None:
        payload["expedited_sla_hours"] = expedited_sla_hours
    if approval_validity_days is not None:
        payload["approval_validity_days"] = approval_validity_days
    if required_evidence_categories is not None:
        payload["required_evidence_categories"] = list(
            required_evidence_categories,
        )
    else:
        payload["required_evidence_categories"] = list(
            TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"],
        )
    payload.update(overrides)
    return payload


def patch_service_catalog_item_payload(
    *,
    name: Optional[str] = None,
    standard_sla_hours: Optional[int] = None,
    expedited_sla_hours: Optional[int] = None,
    approval_validity_days: Optional[int] = None,
    required_evidence_categories: Optional[List[str]] = None,
    status: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /service-catalog-items/{itemId} — PlatformAdmin.

    PRD §3.1: "An admin may retire a catalog item by moving its status
    to RETIRED." So status is also patchable.
    """
    payload: Dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if standard_sla_hours is not None:
        payload["standard_sla_hours"] = standard_sla_hours
    if expedited_sla_hours is not None:
        payload["expedited_sla_hours"] = expedited_sla_hours
    if approval_validity_days is not None:
        payload["approval_validity_days"] = approval_validity_days
    if required_evidence_categories is not None:
        payload["required_evidence_categories"] = list(
            required_evidence_categories,
        )
    if status is not None:
        payload["status"] = status
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AuthorizationRequest — PRD §3.2 / §4
# ---------------------------------------------------------------------------
def create_authorization_request_payload(
    *,
    patient_id: str,
    provider_id: str,
    service_catalog_item_id: str,
    urgency: Optional[str] = None,
    clinical_justification: Optional[str] = None,
    requested_units: Optional[int] = None,
    prior_request_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /authorization-requests — Provider only.

    PRD §3.2: required input fields are patient_id, provider_id,
    service_catalog_item_id, clinical_justification (free-text capped
    at 4000 chars), requested_units (>= 1). Optional: urgency
    (STANDARD default), prior_request_id (resubmission only).
    """
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "service_catalog_item_id": service_catalog_item_id,
        "clinical_justification": (
            clinical_justification
            if clinical_justification is not None
            else TEST_DEFAULTS["DEFAULT_JUSTIFICATION"]
        ),
        "requested_units": (
            requested_units if requested_units is not None
            else TEST_DEFAULTS["DEFAULT_REQUESTED_UNITS"]
        ),
    }
    if urgency is not None:
        payload["urgency"] = urgency
    if prior_request_id is not None:
        payload["prior_request_id"] = prior_request_id
    payload.update(overrides)
    return payload


def patch_authorization_request_payload(
    *,
    clinical_justification: Optional[str] = None,
    requested_units: Optional[int] = None,
    urgency: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /authorization-requests/{authId} — Provider.

    PRD §3.2: "While in DRAFT, the provider may freely revise
    clinical_justification, requested_units, or urgency".
    """
    payload: Dict[str, Any] = {}
    if clinical_justification is not None:
        payload["clinical_justification"] = clinical_justification
    if requested_units is not None:
        payload["requested_units"] = requested_units
    if urgency is not None:
        payload["urgency"] = urgency
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def occ_payload(version: Optional[int] = None,
                **overrides: Any) -> Dict[str, Any]:
    """A minimal action-payload that only carries an optional version
    for optimistic-concurrency checks (PRD §2.6). Many state-change
    actions accept this shape: nothing in the body except version."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ClinicalEvidence — PRD §3.3 / §4
# ---------------------------------------------------------------------------
def attach_clinical_evidence_payload(
    *,
    category: str = "LAB",
    title: Optional[str] = None,
    uri: Optional[str] = None,
    byte_size: int = 1024,
    sourced_from_request_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /authorization-requests/{authId}/clinical-evidence — Provider.

    PRD §3.3: required input fields are category (LAB | IMAGING |
    NOTES | MED_HISTORY | OTHER), title, uri (opaque storage ref),
    byte_size (1..50_000_000). sourced_from_request_id is optional and
    is set when reusing evidence from an EXPIRED prior request.
    """
    payload: Dict[str, Any] = {
        "category": category,
        "title": (
            title if title is not None
            else f"Evidence {random_suffix(5)}"
        ),
        "uri": uri if uri is not None else random_uri(),
        "byte_size": byte_size,
    }
    if sourced_from_request_id is not None:
        payload["sourced_from_request_id"] = sourced_from_request_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PeerToPeerReview — PRD §3.5 / §4
# ---------------------------------------------------------------------------
def schedule_peer_to_peer_payload(
    *,
    scheduled_at: str,
    duration_minutes: int = 30,
    payer_reviewer_id: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /authorization-requests/{authId}/peer-to-peer — Provider.

    PRD §3.5: required input fields are scheduled_at (strictly after
    now, ISO 8601 UTC), duration_minutes (15..60 inclusive),
    payer_reviewer_id (opaque).
    """
    payload: Dict[str, Any] = {
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "payer_reviewer_id": (
            payer_reviewer_id
            if payer_reviewer_id is not None
            else f"payer-rev-{random_suffix(4)}"
        ),
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def complete_peer_to_peer_payload(
    *,
    outcome: str = "UPHELD",
    notes: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /peer-to-peer-reviews/{p2pId}/complete — PayerReviewer.

    PRD §3.5: outcome must be one of UPHELD, OVERTURNED, NO_SHOW;
    notes optional.
    """
    payload: Dict[str, Any] = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Decision — PRD §3.9 / §4
# ---------------------------------------------------------------------------
def decide_authorization_payload(
    *,
    outcome: str = "APPROVED",
    rationale: Optional[str] = None,
    approved_units: Optional[int] = None,
    denial_reason_code: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /authorization-requests/{authId}/decide — InitialReviewer.

    PRD §3.9: outcome is APPROVED | DENIED; rationale capped at 4000;
    approved_units must be in [1, requested_units] when APPROVED, 0
    when DENIED; denial_reason_code required when DENIED.
    """
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "rationale": (
            rationale if rationale is not None
            else f"Decision rationale {random_suffix(4)}"
        ),
    }
    if approved_units is not None:
        payload["approved_units"] = approved_units
    elif outcome == "DENIED":
        payload["approved_units"] = 0
    if denial_reason_code is not None:
        payload["denial_reason_code"] = denial_reason_code
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appeal — PRD §3.11 / §4
# ---------------------------------------------------------------------------
def file_appeal_payload(
    *,
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /authorization-requests/{authId}/appeals — Provider.

    PRD §3.11: reason is free-text (max 4000 chars). tier is computed
    server-side; superseded_decision_id is set by the system.
    """
    payload: Dict[str, Any] = {
        "reason": (
            reason if reason is not None
            else f"Appeal reason {random_suffix(4)}"
        ),
    }
    payload.update(overrides)
    return payload


def decide_appeal_payload(
    *,
    outcome: str = "UPHELD",
    rationale: Optional[str] = None,
    approved_units: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /appeals/{appealId}/decide — tier-restricted reviewer.

    PRD §3.11: outcome is UPHELD | OVERTURNED. approved_units required
    (>= 1) when OVERTURNED; ignored on UPHELD.
    """
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "rationale": (
            rationale if rationale is not None
            else f"Appeal-decision rationale {random_suffix(4)}"
        ),
    }
    if approved_units is not None:
        payload["approved_units"] = approved_units
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §3.10 / §4
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — PlatformAdmin only.

    PRD §3.10: "an admin-only test-driving capability advances the
    logical clock to a supplied to instant".
    """
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


__all__ = [
    # time helpers
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "iso_date",
    # random
    "random_suffix",
    "random_member_id",
    "random_npi",
    "random_catalog_code",
    "random_uri",
    # payloads
    "create_patient_payload",
    "create_provider_payload",
    "create_service_catalog_item_payload",
    "patch_service_catalog_item_payload",
    "create_authorization_request_payload",
    "patch_authorization_request_payload",
    "occ_payload",
    "attach_clinical_evidence_payload",
    "schedule_peer_to_peer_payload",
    "complete_peer_to_peer_payload",
    "decide_authorization_payload",
    "file_appeal_payload",
    "decide_appeal_payload",
    "clock_advance_payload",
]
