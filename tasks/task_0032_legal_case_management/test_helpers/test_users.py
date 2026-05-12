"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes role identity binding:

- PartnerLawyer / SeniorLawyer / JuniorLawyer: identity is **entity_backed
  on Lawyer**. ``X-User-ID`` is the ``id`` of the acting Lawyer row, and
  any ownership / segregation-of-duties / rank check on a draft, time
  entry, evidence, or hearing compares foreign-key fields to that id.
  For ownership-gated calls, helpers MUST mint headers with the actual
  Lawyer.id via ``make_partner_headers(lawyer_id)``,
  ``make_senior_headers(lawyer_id)``, or
  ``make_junior_headers(lawyer_id)``. Falling back to a shared constant
  reproduces the canonical bug — a hard-coded id that never matches any
  real lawyer's id, causing every ownership check to reject the request.

- IntakeClerk / SystemIntegrator: identity is **opaque**. The shared
  TEST_USERS constants are canonical for these roles. The server may
  record the value on AuditLog but does not compare it to any entity.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
# Opaque roles: shared constants are canonical (tests for IntakeClerk /
# SystemIntegrator never need a per-instance id).
#
# Entity-backed roles (Partner/Senior/Junior): the shared constant is a
# fallback used ONLY by tests that do not depend on ownership comparison
# (e.g., RBAC ERR_FORBIDDEN where the role itself is rejected before any
# ownership check fires, or generic 401 ERR_AUTH_REQUIRED tests).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles
    "intake_clerk_headers": build_user_headers("intake-clerk-001",
                                               "IntakeClerk"),
    "intake_clerk_headers_alt": build_user_headers("intake-clerk-002",
                                                   "IntakeClerk"),
    "system_integrator_headers": build_user_headers("system-integ-001",
                                                    "SystemIntegrator"),
    # Entity-backed fallbacks (use only for non-ownership tests)
    "partner_headers_fallback": build_user_headers(
        "partner-fallback-001", "PartnerLawyer"),
    "senior_headers_fallback": build_user_headers(
        "senior-fallback-001", "SeniorLawyer"),
    "junior_headers_fallback": build_user_headers(
        "junior-fallback-001", "JuniorLawyer"),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed lawyer roles
# ---------------------------------------------------------------------------
def make_partner_headers(lawyer_id: str) -> Dict[str, str]:
    """PartnerLawyer headers. PRD §2.1: 'When X-User-Role is PartnerLawyer
    ... the value of X-User-ID is the id of the acting Lawyer row;
    ownership and segregation-of-duties checks on any resource that
    references a Lawyer ... compare those foreign-key fields to
    X-User-ID.'

    Pass the actual Lawyer.id whenever the call is ownership-gated.
    """
    return build_user_headers(lawyer_id, "PartnerLawyer")


def make_senior_headers(lawyer_id: str) -> Dict[str, str]:
    """SeniorLawyer headers. See ``make_partner_headers`` — same identity
    rule applies (entity_backed:Lawyer)."""
    return build_user_headers(lawyer_id, "SeniorLawyer")


def make_junior_headers(lawyer_id: str) -> Dict[str, str]:
    """JuniorLawyer headers. See ``make_partner_headers`` — same identity
    rule applies (entity_backed:Lawyer)."""
    return build_user_headers(lawyer_id, "JuniorLawyer")


def make_intake_clerk_headers(
    actor_id: str = "intake-clerk-001",
) -> Dict[str, str]:
    """IntakeClerk headers; identity is opaque per PRD §2.1."""
    return build_user_headers(actor_id, "IntakeClerk")


def make_system_integrator_headers(
    actor_id: str = "system-integ-001",
) -> Dict[str, str]:
    """SystemIntegrator headers; identity is opaque per PRD §2.1."""
    return build_user_headers(actor_id, "SystemIntegrator")


__all__ = [
    "TEST_USERS",
    "make_partner_headers",
    "make_senior_headers",
    "make_junior_headers",
    "make_intake_clerk_headers",
    "make_system_integrator_headers",
]
