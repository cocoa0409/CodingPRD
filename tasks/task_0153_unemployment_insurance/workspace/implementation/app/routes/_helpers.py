"""Shared helpers for routes."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_EMPLOYER_AGENT,
    ROLE_SYSTEM_ADMIN,
    current_role,
    current_user_id,
)
from ..errors import APIError
from ..store import get_store


def lookup_claimant(claimant_id: str) -> Dict[str, Any]:
    c = get_store().claimants.get(claimant_id)
    if c is None:
        raise APIError("ERR_NOT_FOUND", f"Claimant '{claimant_id}' not found", 404)
    return c


def lookup_employer(employer_id: str) -> Dict[str, Any]:
    e = get_store().employers.get(employer_id)
    if e is None:
        raise APIError("ERR_NOT_FOUND", f"Employer '{employer_id}' not found", 404)
    return e


def lookup_claim(claim_id: str) -> Dict[str, Any]:
    cl = get_store().claims.get(claim_id)
    if cl is None:
        raise APIError("ERR_NOT_FOUND", f"Claim '{claim_id}' not found", 404)
    return cl


def lookup_certification(cert_id: str) -> Dict[str, Any]:
    c = get_store().weekly_certifications.get(cert_id)
    if c is None:
        raise APIError("ERR_NOT_FOUND", f"WeeklyCertification '{cert_id}' not found", 404)
    return c


def lookup_overpayment(overpayment_id: str) -> Dict[str, Any]:
    o = get_store().overpayments.get(overpayment_id)
    if o is None:
        raise APIError("ERR_NOT_FOUND", f"Overpayment '{overpayment_id}' not found", 404)
    return o


def lookup_appeal(appeal_id: str) -> Dict[str, Any]:
    a = get_store().appeals.get(appeal_id)
    if a is None:
        raise APIError("ERR_NOT_FOUND", f"Appeal '{appeal_id}' not found", 404)
    return a


def require_claimant_ownership(claimant_id: str) -> None:
    """When the caller is a Claimant, enforce X-User-ID == claimant_id."""
    if current_role() == ROLE_CLAIMANT and current_user_id() != claimant_id:
        raise APIError("ERR_NOT_OWNER", "Claimant may only act on own resources", 403)


def require_claim_owner(claim: Dict[str, Any]) -> None:
    if current_role() == ROLE_CLAIMANT and current_user_id() != claim["claimant_id"]:
        raise APIError("ERR_NOT_OWNER", "Claimant does not own this Claim", 403)


def require_employer_owner(employer_id: str) -> None:
    if current_role() == ROLE_EMPLOYER_AGENT and current_user_id() != employer_id:
        raise APIError("ERR_NOT_OWNER", "EmployerAgent does not own this Employer", 403)


def sort_by_created_at(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda x: x.get("created_at", ""))
