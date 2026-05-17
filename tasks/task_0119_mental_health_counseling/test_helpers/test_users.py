"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 identity rules:

- PracticeAdmin is OPAQUE. PRD §2.1: "X-User-ID for this role is an
  opaque operator identifier that is not tied to any persisted entity;
  the server may record it for audit purposes but never compares it to
  an entity's id."
- BillingClerk is OPAQUE. PRD §2.1: "X-User-ID for this role is an
  opaque operator identifier not tied to any persisted entity; the
  server may record it but does not match it against an entity id."
- Therapist is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Therapist,
  X-User-ID is the id of the acting Therapist entity; ownership checks
  on any resource that references a Therapist ... compare the
  resource's foreign-key field to X-User-ID."
- Supervisor is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Supervisor, X-User-ID is the id of the acting Supervisor entity;
  ownership checks compare a resource's supervisor_id foreign key to
  X-User-ID."

Every Therapist-driven call whose success depends on the caller owning
the targeted resource MUST mint headers via
make_therapist_headers(therapist["id"]) — never via the shared fallback
constant. Examples: completing the session for the appointment whose
therapist_id matches, creating a session under that appointment,
authoring a crisis assessment or safety plan under a patient with whom
the calling therapist has an in-window care relationship, scheduling an
appointment as the acting therapist.

Falling back to a shared constant for entity-backed roles reproduces
the canonical bug: a literal "fallback" string never equals any real
entity id, so every ownership check rejects every request, cascading
"Setup failed" into dozens of tests downstream.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PRACTICE_ADMIN_ID = "practice-admin-001"
BILLING_CLERK_ID = "billing-clerk-001"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
THERAPIST_FALLBACK_ID = "fallback-therapist-1"
SUPERVISOR_FALLBACK_ID = "fallback-supervisor-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ---------------- Opaque roles (shared constants canonical) ----------
    "practice_admin_headers": build_user_headers(
        PRACTICE_ADMIN_ID, "PracticeAdmin",
    ),
    "billing_clerk_headers": build_user_headers(
        BILLING_CLERK_ID, "BillingClerk",
    ),
    # ---------------- Entity-backed FALLBACK constants ------------------
    # Safe ONLY for auth/role-mismatch tests, opaque tests that do not
    # exercise ownership, or tests whose intended outcome is rejection
    # due to wrong owner. Ownership-gated calls MUST use the per-instance
    # builders below.
    "therapist_fallback_headers": build_user_headers(
        THERAPIST_FALLBACK_ID, "Therapist",
    ),
    "supervisor_fallback_headers": build_user_headers(
        SUPERVISOR_FALLBACK_ID, "Supervisor",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# ---------------------------------------------------------------------------
def make_therapist_headers(therapist_id: str) -> Dict[str, str]:
    """For Therapist (entity_backed:Therapist). Pass the actual
    Therapist.id of the acting clinician.

    PRD §2.1: "When X-User-Role is Therapist, X-User-ID is the id of
    the acting Therapist entity; ownership checks on any resource that
    references a Therapist (for example, the therapist_id foreign key
    carried by an Appointment or a SupervisionAssignment) compare the
    resource's foreign-key field to X-User-ID."

    Every Therapist call whose success depends on owning the targeted
    resource (creating the session under an appointment whose
    therapist_id matches, completing that session, recording a crisis
    assessment, authoring a safety plan, scheduling an appointment for
    self) MUST use this builder — never the shared
    THERAPIST_FALLBACK_ID constant.
    """
    return build_user_headers(therapist_id, "Therapist")


def make_supervisor_headers(supervisor_id: str) -> Dict[str, str]:
    """For Supervisor (entity_backed:Supervisor). Pass the actual
    Supervisor.id of the acting supervisor.

    PRD §2.1: "When X-User-Role is Supervisor, X-User-ID is the id of
    the acting Supervisor entity; ownership checks compare a resource's
    supervisor_id foreign key to X-User-ID."

    Use this builder for Supervisor GET calls whose authorisation
    requires the acting supervisor to own the targeted resource.
    """
    return build_user_headers(supervisor_id, "Supervisor")


def make_practice_admin_headers(user_id: str = PRACTICE_ADMIN_ID
                                ) -> Dict[str, str]:
    """For PracticeAdmin (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "PracticeAdmin")


def make_billing_clerk_headers(user_id: str = BILLING_CLERK_ID
                               ) -> Dict[str, str]:
    """For BillingClerk (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "BillingClerk")


__all__ = [
    "PRACTICE_ADMIN_ID",
    "BILLING_CLERK_ID",
    "THERAPIST_FALLBACK_ID",
    "SUPERVISOR_FALLBACK_ID",
    "TEST_USERS",
    "make_therapist_headers",
    "make_supervisor_headers",
    "make_practice_admin_headers",
    "make_billing_clerk_headers",
]
