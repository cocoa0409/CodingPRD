"""Request payload builders.

Every builder returns a payload that satisfies field-value validation on its
own, and accepts keyword overrides so a test can bend exactly one field.
Monetary figures are emitted as whole-dollar integers, never strings.
"""

from itertools import count
from typing import List, Optional

from .constants import (
    CANONICAL_CARRIER,
    CANONICAL_CERT_EFFECTIVE,
    CANONICAL_CERT_EXPIRATION,
    CANONICAL_CLIENT_NAME,
    CANONICAL_CONTRACTOR_NAME,
    CANONICAL_INDUSTRY_CODE,
    CANONICAL_SITE_CODE,
    CANONICAL_STATISTIC,
    PER_OCCURRENCE_FLOORS,
)

_counter = count(1)


def unique_int() -> int:
    """A process-unique integer for building unique names and references."""
    return next(_counter)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Clients and sites
# ---------------------------------------------------------------------------


def client_payload(**overrides) -> dict:
    payload = {
        "legal_name": CANONICAL_CLIENT_NAME,
        "industry_code": CANONICAL_INDUSTRY_CODE,
    }
    payload.update(overrides)
    return payload


def site_payload(**overrides) -> dict:
    payload = {
        "site_code": CANONICAL_SITE_CODE,
        "required_hazard_classes": ["GENERAL"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contractors, workers and qualifications
# ---------------------------------------------------------------------------


def contractor_payload(**overrides) -> dict:
    payload = {
        "legal_name": CANONICAL_CONTRACTOR_NAME,
        "scope_of_work": ["MECHANICAL_TRADE"],
        "hazard_profile": ["GENERAL"],
        "employee_count": 40,
    }
    payload.update(overrides)
    return payload


def worker_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Ruiz",
        "employee_ref": "EMP-1001",
        "trade_code": "MECHANICAL_TRADE",
    }
    payload.update(overrides)
    return payload


def qualification_payload(**overrides) -> dict:
    payload = {
        "qualification_code": "OSHA10",
        "issued_date": "2026-01-15T00:00:00Z",
        "expiration_date": "2029-01-15T00:00:00Z",
        "training_provider": "SafeStart Institute",
        "evidence_ref": "CERT-OSHA10-1001",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Insurance certificates
# ---------------------------------------------------------------------------

# Limits that clear both the per-occurrence floor at verification and, absent
# any open severe incident, the depleted-aggregate floor at grading.
_ADEQUATE_LIMITS = {
    "GL": (1000000, 2000000),
    "WC": (500000, 1000000),
    "AUTO": (1000000, 1000000),
    "UMBRELLA": (2000000, 4000000),
}


def certificate_payload(coverage_type: str = "GL", **overrides) -> dict:
    each_occurrence, aggregate = _ADEQUATE_LIMITS.get(
        coverage_type, (PER_OCCURRENCE_FLOORS.get(coverage_type, 1000000), 2000000)
    )
    payload = {
        "coverage_type": coverage_type,
        "carrier_name": CANONICAL_CARRIER,
        "each_occurrence_limit": each_occurrence,
        "aggregate_limit": aggregate,
        "effective_date": CANONICAL_CERT_EFFECTIVE,
        "expiration_date": CANONICAL_CERT_EXPIRATION,
    }
    payload.update(overrides)
    return payload


def certificate_decision_payload(decision: str = "VERIFY") -> dict:
    return {"decision": decision}


# ---------------------------------------------------------------------------
# Prequalifications
# ---------------------------------------------------------------------------


def prequalification_payload(
    contractor_id: str,
    client_id: str,
    expected_contractor_version: int,
    cycle_year: int = 2026,
    **overrides,
) -> dict:
    payload = {
        "contractor_id": contractor_id,
        "client_id": client_id,
        "cycle_year": cycle_year,
        "expected_contractor_version": expected_contractor_version,
    }
    payload.update(overrides)
    return payload


def statistic_payload(**overrides) -> dict:
    payload = dict(CANONICAL_STATISTIC)
    payload.update(overrides)
    return payload


def statistic_decision_payload(decision: str = "VERIFY") -> dict:
    return {"decision": decision}


def program_payload(program_type: str = "HAZCOM", **overrides) -> dict:
    payload = {
        "program_type": program_type,
        "revision_date": "2026-06-01T00:00:00Z",
        "document_ref": f"DOC-{program_type}-1",
    }
    payload.update(overrides)
    return payload


def program_review_payload(decision: str = "ACCEPT", reviewer_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    return payload


def program_resubmit_payload(**overrides) -> dict:
    payload = {
        "document_ref": "DOC-REVISED-1",
        "revision_date": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Improvement plans, variances and audit findings
# ---------------------------------------------------------------------------


def improvement_plan_payload(
    expected_prequalification_version: int,
    due_date: str = "2026-10-01T00:00:00Z",
    milestone_count: int = 3,
    **overrides,
) -> dict:
    payload = {
        "due_date": due_date,
        "milestone_count": milestone_count,
        "expected_prequalification_version": expected_prequalification_version,
    }
    payload.update(overrides)
    return payload


def improvement_plan_submit_payload(evidence_ref: str = "EMR-REMEDIATION-PACKET-1") -> dict:
    return {"evidence_ref": evidence_ref}


def improvement_plan_decision_payload(decision: str = "ACCEPT") -> dict:
    return {"decision": decision}


def variance_payload(
    requirement_code: str = "EMR",
    requested_value: float = 1.05,
    justification: str = "Carrier re-rated the experience modifier after an audit correction.",
    **overrides,
) -> dict:
    payload = {
        "requirement_code": requirement_code,
        "requested_value": requested_value,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


def variance_decision_payload(decision: str = "APPROVE", expires_at: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    return payload


def audit_findings_payload(findings_count: int = 0) -> dict:
    return {"findings_count": findings_count}


# ---------------------------------------------------------------------------
# Site access grants
# ---------------------------------------------------------------------------


def grant_payload(
    worker_id: str,
    site_id: str,
    prequalification_id: str,
    expires_at: str = "2026-12-31T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "worker_id": worker_id,
        "site_id": site_id,
        "prequalification_id": prequalification_id,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def revoke_payload(revocation_reason: Optional[str] = "CLIENT_REVOKED") -> dict:
    if revocation_reason is None:
        return {}
    return {"revocation_reason": revocation_reason}


# ---------------------------------------------------------------------------
# Incident reports
# ---------------------------------------------------------------------------


def incident_payload(
    contractor_id: str,
    site_id: str,
    severity: str = "RECORDABLE",
    occurred_at: str = "2026-08-01T00:00:00Z",
    description: str = "Struck-by injury during pipe rigging",
    **overrides,
) -> dict:
    payload = {
        "contractor_id": contractor_id,
        "site_id": site_id,
        "occurred_at": occurred_at,
        "severity": severity,
        "osha_reportable": True,
        "description": description,
    }
    payload.update(overrides)
    return payload


def close_review_payload(findings_note: str = "Root cause addressed; procedure revised") -> dict:
    return {"findings_note": findings_note}


# ---------------------------------------------------------------------------
# Subcontractor links
# ---------------------------------------------------------------------------


def link_payload(
    parent_contractor_id: str,
    child_contractor_id: str,
    prequalification_id: str,
    scope_of_work: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "parent_contractor_id": parent_contractor_id,
        "child_contractor_id": child_contractor_id,
        "prequalification_id": prequalification_id,
        "scope_of_work": scope_of_work or ["SCAFFOLDING"],
    }
    payload.update(overrides)
    return payload
