"""Pre-built role headers for every role in the PRD (§2.1).

PRD §2.1 identity rules:

- ExamAdmin, Proctor, Marker, AppealOfficer, TestHarness are OPAQUE
  operator identifiers — "the server may record it ... but does not
  compare it to the id of any entity." Shared constants are safe for
  these roles.

- Candidate is ENTITY-BACKED: "When X-User-Role is Candidate, X-User-ID
  is the candidate_id of the acting CandidateRegistration. Ownership
  checks on any ExamAttempt traverse the attempt's registration_id to
  the underlying CandidateRegistration and compare its candidate_id to
  X-User-ID."

  Every ownership-gated Candidate-role call therefore MUST use
  make_candidate_headers(<candidate_id>) where <candidate_id> is the
  exact candidate_id used at registration creation. Falling back to a
  shared constant guarantees the ownership traversal fails for any real
  candidate id, cascading "Setup failed" into every downstream test.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants (PRD §2.1: ExamAdmin / Proctor / Marker /
# AppealOfficer / TestHarness are opaque). Plus a non-binding fallback for
# the entity-backed Candidate role, used only for tests that do not
# exercise candidate-ownership (missing-auth, wrong-role, missing-resource).
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    "exam_admin_headers": build_user_headers(
        "exam-admin-001", "ExamAdmin",
    ),
    "exam_admin_headers_alt": build_user_headers(
        "exam-admin-002", "ExamAdmin",
    ),
    "proctor_headers": build_user_headers(
        "proctor-001", "Proctor",
    ),
    "proctor_headers_alt": build_user_headers(
        "proctor-002", "Proctor",
    ),
    "marker_headers": build_user_headers(
        "marker-001", "Marker",
    ),
    "marker_headers_alt": build_user_headers(
        "marker-002", "Marker",
    ),
    "marker_headers_third": build_user_headers(
        "marker-003", "Marker",
    ),
    "appeal_officer_headers": build_user_headers(
        "appeal-officer-001", "AppealOfficer",
    ),
    "appeal_officer_headers_alt": build_user_headers(
        "appeal-officer-002", "AppealOfficer",
    ),
    "test_harness_headers": build_user_headers(
        "test-harness-001", "TestHarness",
    ),
    # Entity-backed fallback — use ONLY for non-ownership negative tests
    # (e.g., "Candidate role calls ExamAdmin endpoint → 403"). For any call
    # that traverses attempt → registration → candidate_id, use the
    # per-instance builder below with the real candidate_id.
    "candidate_headers": build_user_headers(
        "candidate-fallback", "Candidate",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. REQUIRED for the entity_backed Candidate role
# whenever the downstream call is ownership-gated (PRD §2.1).
# ---------------------------------------------------------------------------
def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """PRD §2.1: "When X-User-Role is Candidate, X-User-ID is the
    candidate_id of the acting CandidateRegistration."

    Pass the candidate_id used at registration creation whenever the
    downstream call performs an ownership traversal (create-attempt,
    begin-identity-check, identity-verifications, network-disconnect,
    network-resume, submit, create-appeal, list-own-attempts/appeals).
    """
    return build_user_headers(candidate_id, "Candidate")


def make_marker_headers(marker_id: str) -> Dict[str, str]:
    """PRD §2.1: Marker is opaque, but tests often need distinct
    marker identities to satisfy the double-blind invariant (PRD §3.6:
    "marker has not previously claimed the sibling blind_slot for the
    same (attempt_id, question_id) pair"). Each call to this builder
    yields a distinct, stable Marker identity.
    """
    return build_user_headers(marker_id, "Marker")


def make_appeal_officer_headers(officer_id: str) -> Dict[str, str]:
    """PRD §2.1: AppealOfficer is opaque, but the segregation-of-duties
    check in PRD §3.7 compares the officer's X-User-ID against
    GradingAssignment.marker_id. Tests that exercise this invariant need
    distinct identities for marker vs. appeal officer.
    """
    return build_user_headers(officer_id, "AppealOfficer")


def make_exam_admin_headers(user_id: str = "exam-admin-001") -> Dict[str, str]:
    """PRD §2.1: ExamAdmin is opaque."""
    return build_user_headers(user_id, "ExamAdmin")


def make_proctor_headers(user_id: str = "proctor-001") -> Dict[str, str]:
    """PRD §2.1: Proctor is opaque."""
    return build_user_headers(user_id, "Proctor")


def make_test_harness_headers(user_id: str = "test-harness-001") -> Dict[str, str]:
    """PRD §2.1: TestHarness is opaque."""
    return build_user_headers(user_id, "TestHarness")


__all__ = [
    "TEST_USERS",
    "make_candidate_headers",
    "make_marker_headers",
    "make_appeal_officer_headers",
    "make_exam_admin_headers",
    "make_proctor_headers",
    "make_test_harness_headers",
]
