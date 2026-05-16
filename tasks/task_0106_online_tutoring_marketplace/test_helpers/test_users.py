"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Tutor is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Tutor, X-User-ID
  is the id of the acting Tutor row; ownership checks on any resource
  that references a Tutor (Credentials, SubjectTags, Sessions,
  PayoutBatches) compare the resource's tutor_id to X-User-ID." Every
  Tutor call whose success depends on owning the targeted Credential /
  SubjectTag / Session / PayoutBatch MUST mint headers via
  make_tutor_headers(tutor["id"]) — never via the TUTOR_FALLBACK_ID
  shared constant.

- Student is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Student,
  X-User-ID is the id of the acting Student row; ownership checks on
  any resource that references a Student (Sessions, RefundDisputes,
  ParentChildLinks) compare the resource's student_id to X-User-ID."
  Same per-instance rule applies.

- Parent is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Parent,
  X-User-ID is the id of the acting Parent row; ownership checks on any
  resource that references a Parent (ParentChildLinks) compare the
  resource's parent_id to X-User-ID, and a Parent's access to a child's
  Sessions or RefundDisputes is mediated by an ACTIVE ParentChildLink
  from X-User-ID to the Student." Same per-instance rule applies.

- CredentialVerifier, PlatformArbiter, PlatformAdmin are OPAQUE. PRD
  §2.1: "X-User-ID is an opaque operator identifier not tied to any
  persisted entity." The shared constants are canonical for these
  operator-only roles, with one exception:
    * PRD §3.6: "the admin marking a payout paid cannot equal the admin
      recorded in requested_by" — two distinct opaque admin ids are
      needed for the segregation-of-duties payout flow.
    * PRD §2.11: "A CredentialVerifier may not approve or reject a
      credential whose tutor_id equals their X-User-ID" — so when
      testing a successful credential approve, the verifier id must
      simply be any string different from the tutor's id; the shared
      constant suffices because tutor ids are server-minted UUIDs that
      will not collide with the literal "verifier-001".

The shared TUTOR_FALLBACK_ID / STUDENT_FALLBACK_ID / PARENT_FALLBACK_ID
constants are ONLY safe for tests that DO NOT exercise ownership
(header-missing, role-mismatch, NotFound paths). Ownership-gated calls
MUST use the per-instance builders.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "admin-001"
PLATFORM_ADMIN_ID_ALT = "admin-002"
CREDENTIAL_VERIFIER_ID = "verifier-001"
CREDENTIAL_VERIFIER_ID_ALT = "verifier-002"
PLATFORM_ARBITER_ID = "arbiter-001"
PLATFORM_ARBITER_ID_ALT = "arbiter-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
TUTOR_FALLBACK_ID = "fallback-tutor-1"
STUDENT_FALLBACK_ID = "fallback-student-1"
PARENT_FALLBACK_ID = "fallback-parent-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlatformAdmin — shared constant is canonical.
    "admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # Opaque CredentialVerifier — shared constant is canonical.
    "verifier_headers": build_user_headers(
        CREDENTIAL_VERIFIER_ID, "CredentialVerifier",
    ),
    "verifier_headers_alt": build_user_headers(
        CREDENTIAL_VERIFIER_ID_ALT, "CredentialVerifier",
    ),
    # Opaque PlatformArbiter — shared constant is canonical.
    "arbiter_headers": build_user_headers(
        PLATFORM_ARBITER_ID, "PlatformArbiter",
    ),
    "arbiter_headers_alt": build_user_headers(
        PLATFORM_ARBITER_ID_ALT, "PlatformArbiter",
    ),
    # Entity-backed fallbacks — DO NOT use for ownership-gated calls.
    "tutor_headers": build_user_headers(TUTOR_FALLBACK_ID, "Tutor"),
    "student_headers": build_user_headers(STUDENT_FALLBACK_ID, "Student"),
    "parent_headers": build_user_headers(PARENT_FALLBACK_ID, "Parent"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Tutor, Student, Parent.
# The runtime <Entity>.id minted by the create endpoints is the value
# the implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_tutor_headers(tutor_id: str) -> Dict[str, str]:
    """For Tutor (entity_backed:Tutor). Pass the actual Tutor.id of the
    acting tutor.

    PRD §2.1: "ownership checks on any resource that references a Tutor
    (Credentials, SubjectTags, Sessions, PayoutBatches) compare the
    resource's tutor_id to X-User-ID." Every Tutor call whose success
    depends on owning the targeted Credential, SubjectTag, Session, or
    PayoutBatch (e.g., POST /tutoring/sessions/{id}/confirm, POST
    /tutoring/sessions/{id}/complete, POST /tutoring/disputes/{id}/respond,
    POST /tutoring/disputes/{id}/counter, POST /tutoring/tutors/{id}/
    credentials) MUST use this builder, not the shared
    TUTOR_FALLBACK_ID constant.
    """
    return build_user_headers(tutor_id, "Tutor")


def make_student_headers(student_id: str) -> Dict[str, str]:
    """For Student (entity_backed:Student). Pass the actual Student.id
    of the acting student.

    PRD §2.1: "ownership checks on any resource that references a
    Student (Sessions, RefundDisputes, ParentChildLinks) compare the
    resource's student_id to X-User-ID." Every Student call whose
    success depends on owning the targeted Session or RefundDispute
    (e.g., POST /tutoring/sessions for ADULT self-bookers, POST
    /tutoring/sessions/{id}/cancel, POST /tutoring/disputes) MUST use
    this builder, not the shared STUDENT_FALLBACK_ID constant.
    """
    return build_user_headers(student_id, "Student")


def make_parent_headers(parent_id: str) -> Dict[str, str]:
    """For Parent (entity_backed:Parent). Pass the actual Parent.id of
    the acting parent.

    PRD §2.1: "ownership checks on any resource that references a Parent
    (ParentChildLinks) compare the resource's parent_id to X-User-ID,
    and a Parent's access to a child's Sessions or RefundDisputes is
    mediated by an ACTIVE ParentChildLink from X-User-ID to the
    Student." Every Parent call whose success depends on owning the
    link or being the linked parent for a child's session (e.g., POST
    /tutoring/parents/{id}/links/{lid}/approve, DELETE /tutoring/
    parents/{id}/links/{lid}, POST /tutoring/sessions on behalf of a
    MINOR child, POST /tutoring/disputes for a MINOR child) MUST use
    this builder, not the shared PARENT_FALLBACK_ID constant.
    """
    return build_user_headers(parent_id, "Parent")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id is fine;
    this builder is provided so tests of payout segregation-of-duties
    can use a distinct admin id from the admin who created the payout
    (PRD §3.6)."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_verifier_headers(verifier_id: str) -> Dict[str, str]:
    """For CredentialVerifier (opaque). Any non-empty operator id is
    fine; this builder is provided so tests of credential
    segregation-of-duties can supply a verifier id that intentionally
    collides with the tutor's id (PRD §2.11)."""
    return build_user_headers(verifier_id, "CredentialVerifier")


def make_arbiter_headers(arbiter_id: str) -> Dict[str, str]:
    """For PlatformArbiter (opaque). Any non-empty operator id is fine;
    this builder is provided so tests of arbitration
    segregation-of-duties can supply an arbiter id that intentionally
    collides with the session's tutor/student/parent id (PRD §2.11)."""
    return build_user_headers(arbiter_id, "PlatformArbiter")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "CREDENTIAL_VERIFIER_ID",
    "CREDENTIAL_VERIFIER_ID_ALT",
    "PLATFORM_ARBITER_ID",
    "PLATFORM_ARBITER_ID_ALT",
    "TUTOR_FALLBACK_ID",
    "STUDENT_FALLBACK_ID",
    "PARENT_FALLBACK_ID",
    "TEST_USERS",
    "make_tutor_headers",
    "make_student_headers",
    "make_parent_headers",
    "make_admin_headers",
    "make_verifier_headers",
    "make_arbiter_headers",
]
