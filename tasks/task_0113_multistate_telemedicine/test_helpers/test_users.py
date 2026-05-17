"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 identity rules:

- PlatformAdmin is OPAQUE. PRD §2.1: "When X-User-Role is PlatformAdmin,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity; the server may record it in audit events (where the actor for
  a platform-admin-triggered transition is the value passed in
  X-User-ID) but does not compare it to any entity's id." Shared
  constants in TEST_USERS are canonical for this role.

- ComplianceOfficer is OPAQUE. PRD §2.1: "When X-User-Role is
  ComplianceOfficer, X-User-ID is likewise an opaque operator identifier
  not tied to any persisted entity; the server may record it in audit
  events but does not compare it to any entity's id." Shared constants
  are canonical.

- Payer is OPAQUE. PRD §2.1: "When X-User-Role is Payer, X-User-ID is an
  opaque operator identifier not tied to any persisted entity; the
  server records it in the audit event but does not compare it to any
  entity's id." Shared constants are canonical.

- Physician is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Physician,
  X-User-ID is the id of the acting Physician. Ownership checks on any
  resource that references a Physician — most importantly the
  physician_id on a Consult and the prescribing_physician_id on a
  Prescription — compare the resource's foreign-key field to X-User-ID,
  and a mismatch is rejected with ERR_FORBIDDEN."

  Every Physician-driven call whose success depends on owning the
  targeted Consult / Prescription / FollowUp MUST mint headers via
  make_physician_headers(physician["id"]) — never via the shared
  PHYSICIAN_FALLBACK_ID constant. Falling back to the shared constant
  for entity-backed roles reproduces the canonical bug: the literal
  "fallback-physician-1" never equals any real Physician.id, so every
  ownership check rejects every request, cascading "Setup failed" into
  dozens of tests downstream.

The shared PHYSICIAN_FALLBACK_ID constant is ONLY safe for tests that
DO NOT exercise ownership (auth-missing, role-mismatch, NotFound on
unrelated paths). Ownership-gated Physician calls MUST use the
per-instance builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "admin-001"
PLATFORM_ADMIN_ID_ALT = "admin-002"

COMPLIANCE_OFFICER_ID = "compliance-001"
COMPLIANCE_OFFICER_ID_ALT = "compliance-002"

PAYER_ID = "payer-001"
PAYER_ID_ALT = "payer-002"

# Entity-backed fallback id — DO NOT use for ownership-gated Physician
# calls.
PHYSICIAN_FALLBACK_ID = "fallback-physician-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin — opaque
    "admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # ComplianceOfficer — opaque
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer",
    ),
    "compliance_officer_headers_alt": build_user_headers(
        COMPLIANCE_OFFICER_ID_ALT, "ComplianceOfficer",
    ),
    # Payer — opaque
    "payer_headers": build_user_headers(PAYER_ID, "Payer"),
    "payer_headers_alt": build_user_headers(PAYER_ID_ALT, "Payer"),
    # Physician — entity-backed FALLBACK. Safe only for auth/role/
    # NotFound paths; ownership-gated calls MUST use
    # make_physician_headers.
    "physician_fallback_headers": build_user_headers(
        PHYSICIAN_FALLBACK_ID, "Physician",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed Physician.
# ---------------------------------------------------------------------------
def make_physician_headers(physician_id: str) -> Dict[str, str]:
    """For Physician (entity_backed:Physician). Pass the actual
    Physician.id of the acting clinician.

    PRD §2.1: "When X-User-Role is Physician, X-User-ID is the id of the
    acting Physician. Ownership checks on any resource that references a
    Physician — most importantly the physician_id on a Consult and the
    prescribing_physician_id on a Prescription — compare the resource's
    foreign-key field to X-User-ID, and a mismatch is rejected with
    ERR_FORBIDDEN."

    Every Physician-driven call whose success depends on owning the
    targeted Consult / Prescription / FollowUp MUST use this builder,
    not the shared PHYSICIAN_FALLBACK_ID constant.
    """
    return build_user_headers(physician_id, "Physician")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque). Any non-empty operator id is
    fine."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_payer_headers(user_id: str) -> Dict[str, str]:
    """For Payer (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "Payer")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "COMPLIANCE_OFFICER_ID",
    "COMPLIANCE_OFFICER_ID_ALT",
    "PAYER_ID",
    "PAYER_ID_ALT",
    "PHYSICIAN_FALLBACK_ID",
    "TEST_USERS",
    "make_physician_headers",
    "make_admin_headers",
    "make_compliance_officer_headers",
    "make_payer_headers",
]
