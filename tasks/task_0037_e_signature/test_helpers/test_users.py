"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- TemplateAdmin, ContractInitiator, Signer, EvidenceArchivist:
  entity-backed on OrgUser. PRD §2.1: 'When X-User-Role is one of these
  four, X-User-ID is the id of the acting OrgUser; ownership and
  segregation checks compare resource fields (such as the
  initiator_user_id recorded on a Contract) directly to X-User-ID.'

  Ownership/segregation-gated calls (POST /contracts/{id}/activate
  cross-checked against publisher; POST /contracts/{id}/evidence/seal
  cross-checked against initiator_user_id; POST /signing-parties/{id}/sign
  cross-checked against signer_user_id; etc.) MUST use the per-instance
  builders below with the actual OrgUser.id.

- PlatformAdmin, SystemSweeper: opaque operator identifiers. PRD §2.1:
  'not tied to any persisted entity. The server may record them on
  append-only AuditLog rows but does not compare them to any entity's id.'
  The shared TEST_USERS constant is canonical for these roles.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For the two opaque roles, these are canonical. For the
# four entity-backed roles, the constants are fallbacks for tests that
# don't exercise ownership comparison (e.g., ERR_FORBIDDEN wrong-role
# tests, ERR_NOT_FOUND on missing resource, schema-violation tests).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles -- canonical shared constants.
    "platform_admin_headers": build_user_headers(
        "admin-001", "PlatformAdmin"
    ),
    "platform_admin_headers_alt": build_user_headers(
        "admin-002", "PlatformAdmin"
    ),
    "system_sweeper_headers": build_user_headers(
        "sweeper-001", "SystemSweeper"
    ),

    # Fallback constants for entity-backed roles. Use only when the call
    # under test does NOT exercise an ownership / segregation comparison.
    "template_admin_headers": build_user_headers(
        "template-admin-fallback", "TemplateAdmin"
    ),
    "contract_initiator_headers": build_user_headers(
        "contract-initiator-fallback", "ContractInitiator"
    ),
    "signer_headers": build_user_headers(
        "signer-fallback", "Signer"
    ),
    "evidence_archivist_headers": build_user_headers(
        "evidence-archivist-fallback", "EvidenceArchivist"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed roles (PRD §2.1).
# Use these whenever the call is ownership-gated or part of a
# segregation-of-duties check.
# ---------------------------------------------------------------------------
def make_template_admin_headers(user_id: str) -> Dict[str, str]:
    """TemplateAdmin headers (entity_backed:OrgUser).

    Pass the OrgUser.id of the acting admin -- e.g., the publisher of a
    TemplateVersion. PRD §3.3 requires that the activator of a Contract
    is NOT the same OrgUser who published the referenced TemplateVersion.
    """
    return build_user_headers(user_id, "TemplateAdmin")


def make_contract_initiator_headers(user_id: str) -> Dict[str, str]:
    """ContractInitiator headers (entity_backed:OrgUser).

    Pass the OrgUser.id of the acting initiator. PRD §3.11 forbids the
    initiator from sealing the EvidencePackage (segregation of duties);
    that check compares X-User-ID to Contract.initiator_user_id.
    """
    return build_user_headers(user_id, "ContractInitiator")


def make_signer_headers(user_id: str) -> Dict[str, str]:
    """Signer headers (entity_backed:OrgUser).

    Pass the OrgUser.id of the human signer. PRD §3.5 requires the acting
    X-User-ID to equal the SigningParty.signer_user_id (or an authorized
    delegate of it).
    """
    return build_user_headers(user_id, "Signer")


def make_evidence_archivist_headers(user_id: str) -> Dict[str, str]:
    """EvidenceArchivist headers (entity_backed:OrgUser).

    Pass the OrgUser.id of the archivist. PRD §3.11: the seal action
    requires that the acting user is NOT the same OrgUser as
    Contract.initiator_user_id.
    """
    return build_user_headers(user_id, "EvidenceArchivist")


def make_platform_admin_headers(
    admin_id: str = "admin-001",
) -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_system_sweeper_headers(
    sweeper_id: str = "sweeper-001",
) -> Dict[str, str]:
    return build_user_headers(sweeper_id, "SystemSweeper")


__all__ = [
    "TEST_USERS",
    "make_template_admin_headers",
    "make_contract_initiator_headers",
    "make_signer_headers",
    "make_evidence_archivist_headers",
    "make_platform_admin_headers",
    "make_system_sweeper_headers",
]
