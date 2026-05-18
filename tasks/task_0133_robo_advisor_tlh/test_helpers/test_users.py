"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- ComplianceOfficer / TaxAdmin / system are OPAQUE. PRD §2.1: "the same
  opaque rule applies when X-User-Role is TaxAdmin (1099-B preparation)
  and when X-User-Role is system (automated runners exposed via the
  test-driving endpoints listed in §4)" and "When X-User-Role is
  ComplianceOfficer, X-User-ID is an opaque operator identifier not
  tied to any persisted entity". Shared constants are canonical.

- ClientUser is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  ClientUser, X-User-ID is the id of the acting Client; ownership
  checks on any resource that references a Client (the client's own
  Account, the trades, positions, harvest opportunities, and forms
  beneath each Account) compare the resource's client_id foreign-key
  field to X-User-ID. A ClientUser may only act on the client whose id
  equals their X-User-ID."

  Every ClientUser-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_client_user_headers(client["id"]) — never via the shared
  CLIENT_USER_FALLBACK_ID constant. Falling back to the shared constant
  for an entity-backed role reproduces the canonical bug: the literal
  "fallback-client-1" never equals any real Client.id, so every
  ownership check rejects every request as ERR_AUTH_IDENTITY_UNKNOWN
  (or ERR_AUTH_FORBIDDEN) regardless of implementation correctness.

- Advisor identity is treated OPAQUELY in this suite because PRD
  §2.1 explicitly downgrades enforcement: "advisor-side operations are
  scoped to advisors assigned to the relevant client (the platform
  records but does not over-enforce the assignment graph for endpoints
  listed as Advisor-permitted)." There is no PRD endpoint to register
  an Advisor entity, so tests use a shared constant for Advisor
  headers and do NOT exercise advisor-ownership comparisons.

The shared CLIENT_USER_FALLBACK_ID constant is ONLY safe for tests that
DO NOT exercise ownership (header-missing, role-mismatch on a
non-existent resource, or 404 paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
COMPLIANCE_OFFICER_ID: str = "compliance-officer-001"
COMPLIANCE_OFFICER_ID_ALT: str = "compliance-officer-002"

TAX_ADMIN_ID: str = "tax-admin-001"

SYSTEM_ID: str = "system-runner-001"

# PRD §2.1 declares Advisor entity_backed but PRD provides no endpoint to
# register an Advisor entity. PRD §2.1 also explicitly downgrades
# enforcement. Use a shared opaque-style id; do not assert ownership.
ADVISOR_ID: str = "advisor-001"

# Entity-backed fallback id — DO NOT use for ownership-gated ClientUser
# calls. Safe only for header-missing / role-mismatch / NotFound paths.
CLIENT_USER_FALLBACK_ID: str = "fallback-client-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque ComplianceOfficer — shared constant is canonical.
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer",
    ),
    "compliance_officer_headers_alt": build_user_headers(
        COMPLIANCE_OFFICER_ID_ALT, "ComplianceOfficer",
    ),
    # Opaque TaxAdmin — shared constant is canonical.
    "tax_admin_headers": build_user_headers(TAX_ADMIN_ID, "TaxAdmin"),
    # Opaque system — shared constant is canonical.
    "system_headers": build_user_headers(SYSTEM_ID, "system"),
    # Advisor — PRD does not provide a create-Advisor endpoint and
    # explicitly relaxes ownership enforcement for advisors. Use the
    # shared constant; do not test advisor-ownership comparisons.
    "advisor_headers": build_user_headers(ADVISOR_ID, "Advisor"),
    # Entity-backed ClientUser fallback — DO NOT use for ownership-
    # gated calls. Safe only for header-missing / role-mismatch /
    # 404 paths.
    "client_user_fallback_headers": build_user_headers(
        CLIENT_USER_FALLBACK_ID, "ClientUser",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed ClientUser.
# The runtime Client.id minted by POST /clients is the value the
# implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_client_user_headers(client_id: str) -> Dict[str, str]:
    """For ClientUser (entity_backed:Client). Pass the actual Client.id
    of the acting client.

    PRD §2.1: "When X-User-Role is ClientUser, X-User-ID is the id of
    the acting Client; ownership checks on any resource that references
    a Client ... compare the resource's client_id foreign-key field to
    X-User-ID. A ClientUser may only act on the client whose id equals
    their X-User-ID."

    Every ClientUser-driven call whose success depends on owning the
    targeted Client / Account / Trade / Position / HarvestOpportunity /
    Form1099B MUST use this builder, not the shared
    CLIENT_USER_FALLBACK_ID constant.
    """
    return build_user_headers(client_id, "ClientUser")


def make_compliance_officer_headers(officer_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque). Any non-empty operator id is
    fine; this builder exists so tests that want a distinct officer id
    (e.g., for audit-token discrimination) can supply one without
    relying on a single shared constant.
    """
    return build_user_headers(officer_id, "ComplianceOfficer")


def make_tax_admin_headers(admin_id: str) -> Dict[str, str]:
    """For TaxAdmin (opaque)."""
    return build_user_headers(admin_id, "TaxAdmin")


def make_system_headers(runner_id: str) -> Dict[str, str]:
    """For system (opaque, used by /_clock/advance, /_quarterly/run,
    /_settle/run)."""
    return build_user_headers(runner_id, "system")


def make_advisor_headers(advisor_id: str) -> Dict[str, str]:
    """For Advisor. PRD §2.1 does not over-enforce advisor ownership;
    any non-empty id works.
    """
    return build_user_headers(advisor_id, "Advisor")


__all__ = [
    "COMPLIANCE_OFFICER_ID",
    "COMPLIANCE_OFFICER_ID_ALT",
    "TAX_ADMIN_ID",
    "SYSTEM_ID",
    "ADVISOR_ID",
    "CLIENT_USER_FALLBACK_ID",
    "TEST_USERS",
    "make_client_user_headers",
    "make_compliance_officer_headers",
    "make_tax_admin_headers",
    "make_system_headers",
    "make_advisor_headers",
]
