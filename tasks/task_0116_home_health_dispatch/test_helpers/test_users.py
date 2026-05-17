"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- FieldClinician is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  FieldClinician, X-User-ID is the id of the acting Clinician;
  ownership checks on any resource that references a Clinician compare
  the resource's foreign-key field to X-User-ID. In particular,
  completing a visit requires that X-User-ID equal the clinician_id
  recorded on the Visit."

  Every FieldClinician-driven call whose success depends on owning the
  targeted Visit (POST /visits/{visitId}/complete) or recording mileage
  for that visit (POST /visits/{visitId}/mileage) MUST mint headers via
  make_field_clinician_headers(clinician["id"]) — never the shared
  FIELD_CLINICIAN_FALLBACK_ID constant. The fallback constant
  ("fallback-clinician-1") never equals any real Clinician.id, so every
  ownership check rejects every request, cascading "Setup failed" into
  every downstream test.

- IntakeCoordinator, BillingSpecialist, and PlatformAdmin are OPAQUE.
  PRD §2.1: "When X-User-Role is IntakeCoordinator, BillingSpecialist,
  or PlatformAdmin, X-User-ID is an opaque operator identifier not tied
  to any persisted entity. The server may record it for audit but does
  not compare it to any entity's id." Shared constants in TEST_USERS
  are canonical for these three roles.

The FIELD_CLINICIAN_FALLBACK_ID is ONLY safe for tests that DO NOT
exercise ownership (auth-missing, role-mismatch, NotFound on an
unrelated path). Ownership-gated calls MUST use the per-instance
builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
INTAKE_COORDINATOR_ID = "intake-coordinator-001"
INTAKE_COORDINATOR_ID_ALT = "intake-coordinator-002"

BILLING_SPECIALIST_ID = "billing-specialist-001"
BILLING_SPECIALIST_ID_ALT = "billing-specialist-002"

PLATFORM_ADMIN_ID = "platform-admin-001"
PLATFORM_ADMIN_ID_ALT = "platform-admin-002"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
FIELD_CLINICIAN_FALLBACK_ID = "fallback-clinician-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # IntakeCoordinator — opaque
    "intake_coordinator_headers": build_user_headers(
        INTAKE_COORDINATOR_ID, "IntakeCoordinator",
    ),
    "intake_coordinator_headers_alt": build_user_headers(
        INTAKE_COORDINATOR_ID_ALT, "IntakeCoordinator",
    ),
    # BillingSpecialist — opaque
    "billing_specialist_headers": build_user_headers(
        BILLING_SPECIALIST_ID, "BillingSpecialist",
    ),
    "billing_specialist_headers_alt": build_user_headers(
        BILLING_SPECIALIST_ID_ALT, "BillingSpecialist",
    ),
    # PlatformAdmin — opaque
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # FieldClinician — entity-backed FALLBACK. Safe only for auth/role/
    # NotFound paths; ownership-gated calls MUST use
    # make_field_clinician_headers.
    "field_clinician_fallback_headers": build_user_headers(
        FIELD_CLINICIAN_FALLBACK_ID, "FieldClinician",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed FieldClinician.
# ---------------------------------------------------------------------------
def make_field_clinician_headers(clinician_id: str) -> Dict[str, str]:
    """For FieldClinician (entity_backed:Clinician). Pass the actual
    Clinician.id of the acting clinician.

    PRD §2.1: "When X-User-Role is FieldClinician, X-User-ID is the id
    of the acting Clinician; ownership checks on any resource that
    references a Clinician compare the resource's foreign-key field to
    X-User-ID. In particular, completing a visit requires that
    X-User-ID equal the clinician_id recorded on the Visit."

    Every FieldClinician-driven call whose success depends on owning
    the targeted Visit (POST /visits/{visitId}/complete or POST
    /visits/{visitId}/mileage) MUST use this builder.
    """
    return build_user_headers(clinician_id, "FieldClinician")


def make_intake_coordinator_headers(user_id: str) -> Dict[str, str]:
    """For IntakeCoordinator (opaque). Any non-empty operator id is
    acceptable; the server does not compare X-User-ID to any persisted
    entity for opaque roles."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_billing_specialist_headers(user_id: str) -> Dict[str, str]:
    """For BillingSpecialist (opaque). Any non-empty operator id is
    acceptable."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_platform_admin_headers(user_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id is
    acceptable."""
    return build_user_headers(user_id, "PlatformAdmin")


__all__ = [
    "INTAKE_COORDINATOR_ID",
    "INTAKE_COORDINATOR_ID_ALT",
    "BILLING_SPECIALIST_ID",
    "BILLING_SPECIALIST_ID_ALT",
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "FIELD_CLINICIAN_FALLBACK_ID",
    "TEST_USERS",
    "make_field_clinician_headers",
    "make_intake_coordinator_headers",
    "make_billing_specialist_headers",
    "make_platform_admin_headers",
]
