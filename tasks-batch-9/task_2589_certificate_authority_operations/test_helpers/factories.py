"""Request payload builders.

Each builder returns a payload that satisfies every input constraint stated in
PRD section 3 for that endpoint, so a test only has to override the one field
it is exercising.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_EPOCH,
    DCV_METHOD_DNS_TXT,
    INCIDENT_PROCEDURAL,
    ROOT_PROGRAM_MOZILLA,
    SEVERITY_MINOR,
    VALIDATION_TYPE_DV,
    VALIDATION_TYPE_EV,
    VALIDATION_TYPE_OV,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that is unique within a single test process."""
    return str(next(_counter))


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel that removes a key from a factory payload."""

    def __repr__(self):  # pragma: no cover - debugging aid only
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ---------------------------------------------------------------------------
# Certificate profiles (PRD 3.1)
# ---------------------------------------------------------------------------
def profile_payload(**overrides) -> Dict[str, Any]:
    """A DV profile: `org_vetting_reuse_days` must be exactly 0 for DV."""
    base = {
        "name": "dv-profile-" + unique_suffix(),
        "validation_type": VALIDATION_TYPE_DV,
        "max_validity_days": 90,
        "dcv_reuse_days": 30,
        "max_dcv_reuse_count": 2,
        "org_vetting_reuse_days": 0,
        "allowed_dcv_methods": [DCV_METHOD_DNS_TXT],
        "required_sct_count": 1,
        "base_fee_cents": 8000,
        "crl_trigger_threshold": 100,
        "max_crl_validity_hours": 24,
    }
    return _merge(base, overrides)


dv_profile_payload = profile_payload


def ov_profile_payload(**overrides) -> Dict[str, Any]:
    base = profile_payload(
        name="ov-profile-" + unique_suffix(),
        validation_type=VALIDATION_TYPE_OV,
        org_vetting_reuse_days=825,
    )
    return _merge(base, overrides)


def ev_profile_payload(**overrides) -> Dict[str, Any]:
    base = profile_payload(
        name="ev-profile-" + unique_suffix(),
        validation_type=VALIDATION_TYPE_EV,
        org_vetting_reuse_days=825,
    )
    return _merge(base, overrides)


def crl_publication_payload(
    this_update: str, next_update: str, expected_profile_version: int, **overrides
) -> Dict[str, Any]:
    base = {
        "this_update": this_update,
        "next_update": next_update,
        "expected_profile_version": expected_profile_version,
    }
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Subscribers (PRD 3.2)
# ---------------------------------------------------------------------------
def subscriber_payload(**overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    base = {
        "legal_name": "Subscriber " + suffix,
        "jurisdiction_code": "DE",
        "registry_id": "DE-HRB" + suffix.zfill(6),
        "contact_email": "ops" + suffix + "@subscriber.example",
        "callback_phone": "+4930555" + suffix.zfill(4),
        "credit_limit_cents": 1_000_000,
    }
    return _merge(base, overrides)


def subscriber_amendment_payload(**overrides) -> Dict[str, Any]:
    return dict(overrides)


# ---------------------------------------------------------------------------
# Organization vetting (PRD 3.3)
# ---------------------------------------------------------------------------
def vetting_payload(required_level: str, **overrides) -> Dict[str, Any]:
    return _merge({"required_level": required_level}, overrides)


def check_payload(
    dimension: str, outcome: str, evidence_ref: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"dimension": dimension, "outcome": outcome}
    if evidence_ref is not None:
        base["evidence_ref"] = evidence_ref
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Domain control validation (PRD 3.4)
# ---------------------------------------------------------------------------
def authorization_payload(
    subscriber_id: str,
    profile_id: str,
    domain_name: str = "d1.example.org",
    method: str = DCV_METHOD_DNS_TXT,
    **overrides,
) -> Dict[str, Any]:
    base = {
        "subscriber_id": subscriber_id,
        "profile_id": profile_id,
        "domain_name": domain_name,
        "method": method,
    }
    return _merge(base, overrides)


def validate_payload(challenge_token: str, **overrides) -> Dict[str, Any]:
    return _merge({"challenge_token": challenge_token}, overrides)


def invalidate_payload(
    reason: str = "the DNS TXT record was removed by the registrant", **overrides
) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Certificate requests (PRD 3.5)
# ---------------------------------------------------------------------------
def certificate_request_payload(
    subscriber_id: str,
    profile_id: str,
    requested_domains: Optional[List[str]] = None,
    requested_validity_days: int = 90,
    csr_key_bits: int = 2048,
    expedited: bool = False,
    **overrides,
) -> Dict[str, Any]:
    base = {
        "subscriber_id": subscriber_id,
        "profile_id": profile_id,
        "requested_domains": list(requested_domains or ["d1.example.org"]),
        "requested_validity_days": requested_validity_days,
        "csr_key_bits": csr_key_bits,
        "expedited": expedited,
    }
    return _merge(base, overrides)


def return_payload(
    return_reason: str = "the organisation name in the request does not match the registry",
    **overrides,
) -> Dict[str, Any]:
    return _merge({"return_reason": return_reason}, overrides)


def reject_payload(
    rejected_reason: str = "the subscriber withdrew the order", **overrides
) -> Dict[str, Any]:
    return _merge({"rejected_reason": rejected_reason}, overrides)


def issue_payload(
    ceremony_id: str, supersedes_certificate_id: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"ceremony_id": ceremony_id}
    if supersedes_certificate_id is not None:
        base["supersedes_certificate_id"] = supersedes_certificate_id
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# CT log submissions (PRD 3.7)
# ---------------------------------------------------------------------------
def ct_submission_payload(
    log_operator: str, outcome: str, rejection_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"log_operator": log_operator, "outcome": outcome}
    if rejection_reason is not None:
        base["rejection_reason"] = rejection_reason
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# HSM partitions and key ceremonies (PRD 3.6)
# ---------------------------------------------------------------------------
def partition_payload(**overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    base = {"label": "part-" + suffix, "serial": "HSM-" + suffix.zfill(4)}
    return _merge(base, overrides)


def ceremony_payload(
    window_start: str = CLOCK_EPOCH,
    window_end: str = "2026-08-01T00:30:00Z",
    attestation_valid_days: int = 60,
    **overrides,
) -> Dict[str, Any]:
    base = {
        "window_start": window_start,
        "window_end": window_end,
        "attestation_valid_days": attestation_valid_days,
    }
    return _merge(base, overrides)


def attestation_revocation_payload(
    reason: str = "the ceremony video recording could not be produced", **overrides
) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


def abort_payload(
    reason: str = "the second key custodian was unavailable", **overrides
) -> Dict[str, Any]:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Revocation (PRD 3.8)
# ---------------------------------------------------------------------------
def revocation_payload(
    certificate_id: str,
    reason_code: str,
    expected_certificate_version: int,
    incident_id: Optional[str] = None,
    evidence_ref: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "certificate_id": certificate_id,
        "reason_code": reason_code,
        "expected_certificate_version": expected_certificate_version,
    }
    if incident_id is not None:
        base["incident_id"] = incident_id
    if evidence_ref is not None:
        base["evidence_ref"] = evidence_ref
    return _merge(base, overrides)


def denial_payload(
    denial_reason: str = "the subscriber withdrew the revocation request", **overrides
) -> Dict[str, Any]:
    return _merge({"denial_reason": denial_reason}, overrides)


# ---------------------------------------------------------------------------
# Misissuance incidents (PRD 3.9)
# ---------------------------------------------------------------------------
def incident_payload(
    scope_profile_id: str,
    category: str = INCIDENT_PROCEDURAL,
    scope_issued_from: str = "2026-07-01T00:00:00Z",
    scope_issued_to: str = "2026-09-01T00:00:00Z",
    subscriber_id: Optional[str] = None,
    scope_dcv_method: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "title": "Incident " + unique_suffix(),
        "category": category,
        "scope_profile_id": scope_profile_id,
        "scope_issued_from": scope_issued_from,
        "scope_issued_to": scope_issued_to,
    }
    if subscriber_id is not None:
        base["subscriber_id"] = subscriber_id
    if scope_dcv_method is not None:
        base["scope_dcv_method"] = scope_dcv_method
    return _merge(base, overrides)


def disclosure_payload(
    root_program: str = ROOT_PROGRAM_MOZILLA,
    body: str = "Initial disclosure of the misissuance to the root program.",
    **overrides,
) -> Dict[str, Any]:
    return _merge({"root_program": root_program, "body": body}, overrides)


def communication_payload(
    root_program: str = ROOT_PROGRAM_MOZILLA,
    body: str = "Follow-up correspondence with the root program.",
    **overrides,
) -> Dict[str, Any]:
    return _merge({"root_program": root_program, "body": body}, overrides)


# ---------------------------------------------------------------------------
# Root program audits (PRD 3.9)
# ---------------------------------------------------------------------------
def audit_payload(
    root_program: str = ROOT_PROGRAM_MOZILLA,
    period_start: str = "2026-01-01T00:00:00Z",
    period_end: str = "2026-09-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    base = {
        "root_program": root_program,
        "period_start": period_start,
        "period_end": period_end,
    }
    return _merge(base, overrides)


def finding_payload(
    severity: str = SEVERITY_MINOR,
    summary: str = "A control exception was observed during fieldwork.",
    **overrides,
) -> Dict[str, Any]:
    return _merge({"severity": severity, "summary": summary}, overrides)
