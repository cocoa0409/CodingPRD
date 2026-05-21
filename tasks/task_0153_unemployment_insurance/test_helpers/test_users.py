"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    - Claimant: entity-backed. When X-User-Role is Claimant, X-User-ID is
      the id of the acting Claimant. Ownership checks on any resource that
      references a Claimant (a Claim, a WeeklyCertification, an
      Overpayment, an Appeal) compare the resource's owning claimant_id
      (resolved through the Claim if necessary) to X-User-ID. A mismatch
      yields ERR_NOT_OWNER.
    - Adjudicator: opaque operator identifier not tied to any persisted
      entity. The server records it on the adjudicated claim as
      assigned_adjudicator_id precisely so the later appeal flow can
      enforce segregation of duties; otherwise it is not compared to any
      entity's id.
    - AppealOfficer: opaque operator identifier. Compared to the appeal's
      assigned_appeal_officer_id to confirm assignment, and against the
      appeal's assigned_adjudicator_id to enforce segregation of duties.
    - EmployerAgent: entity-backed. When X-User-Role is EmployerAgent,
      X-User-ID is the id of the acting Employer; ownership checks on any
      resource that references an Employer (notably EmployerCharge lists
      and the relief endpoint) compare the resource's employer_id to
      X-User-ID.
    - SystemAdmin: opaque operator identifier.

The shared *_headers constants below use deterministic seed strings.
They are appropriate ONLY for:
    * Claimant/EmployerAgent tests whose success does NOT depend on the
      caller owning the subject resource (e.g., ERR_UNAUTHENTICATED probes,
      404-on-missing-resource probes, ERR_FORBIDDEN probes).
    * The opaque roles (Adjudicator, AppealOfficer, SystemAdmin), where
      X-User-ID is never compared against any entity id (except the
      AppealOfficer's assigned_appeal_officer_id and assigned_adjudicator_id
      comparisons — which take role-specific operator ids passed via the
      per-instance builders below).

For any Claimant-scoped operation whose acceptance depends on the caller
being the resource owner (every claim submit / adjudicate /
apply-extension, every weekly-certification create, every overpayment
repay, every appeal create / withdraw), tests and fixtures MUST mint
headers via make_claimant_headers(claimant_id) with the real Claimant.id
returned by POST /claimants. Similarly for EmployerAgent on charge
relief and charges list.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — safe for opaque roles and non-ownership probes.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed:Claimant — shared constant is reserved for tests that
    # don't exercise ownership (auth/404/FORBIDDEN probes, etc.).
    "claimant_headers": build_user_headers(
        "claimant-shared-0001", "Claimant",
    ),
    # entity_backed:Employer — shared constant is reserved for tests that
    # don't exercise ownership.
    "employer_agent_headers": build_user_headers(
        "employer-shared-0001", "EmployerAgent",
    ),
    # Opaque operator roles — X-User-ID is not compared to any entity.
    "adjudicator_headers": build_user_headers(
        "adjudicator-0001", "Adjudicator",
    ),
    "appeal_officer_headers": build_user_headers(
        "appeal-officer-0001", "AppealOfficer",
    ),
    "system_admin_headers": build_user_headers(
        "system-admin-0001", "SystemAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles whenever the
# downstream call is ownership-gated.
# ---------------------------------------------------------------------------
def make_claimant_headers(claimant_id: str) -> Dict[str, str]:
    """Headers for a specific Claimant. Use this whenever the call is
    ownership-gated — i.e. any operation against a Claim, WeeklyCertification,
    Overpayment, or Appeal that records claimant_id.

    PRD §2.1: "Ownership checks on any resource that references a Claimant
    (a Claim, a WeeklyCertification, an Overpayment, an Appeal) compare
    the resource's owning claimant_id (resolved through the Claim if
    necessary) to X-User-ID. A mismatch yields ERR_NOT_OWNER."
    """
    return build_user_headers(claimant_id, "Claimant")


def make_employer_agent_headers(employer_id: str) -> Dict[str, str]:
    """Headers for a specific Employer's agent. Use this whenever the
    call is ownership-gated — i.e. /employers/{id}, /employers/{id}/charges,
    and /employers/{id}/charges/{charge_id}/relieve.

    PRD §2.1: "Ownership checks on any resource that references an
    Employer (notably EmployerCharge lists and the relief endpoint)
    compare the resource's employer_id to X-User-ID."
    """
    return build_user_headers(employer_id, "EmployerAgent")


def make_adjudicator_headers(
    operator_id: str = "adjudicator-0001",
) -> Dict[str, str]:
    """Headers for an Adjudicator operator. Opaque per PRD §2.1.

    Each test that exercises segregation-of-duties may pass a distinct
    operator_id to control whether it collides with the assigned
    AppealOfficer of an appeal.
    """
    return build_user_headers(operator_id, "Adjudicator")


def make_appeal_officer_headers(
    operator_id: str = "appeal-officer-0001",
) -> Dict[str, str]:
    """Headers for an AppealOfficer operator. Opaque per PRD §2.1.

    The operator_id MUST equal the appeal's assigned_appeal_officer_id
    for start-hearing / decide to succeed, and MUST NOT equal the
    appeal's assigned_adjudicator_id (segregation of duties).
    """
    return build_user_headers(operator_id, "AppealOfficer")


def make_system_admin_headers(
    operator_id: str = "system-admin-0001",
) -> Dict[str, str]:
    """Headers for a SystemAdmin operator. Opaque per PRD §2.1."""
    return build_user_headers(operator_id, "SystemAdmin")


__all__ = [
    "TEST_USERS",
    "make_claimant_headers",
    "make_employer_agent_headers",
    "make_adjudicator_headers",
    "make_appeal_officer_headers",
    "make_system_admin_headers",
]
