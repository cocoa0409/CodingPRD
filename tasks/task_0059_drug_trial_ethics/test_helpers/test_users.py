"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Applicant: PRD says X-User-ID 'is an opaque principal-investigator
  identifier not tied to any persisted entity. The server records it as
  applicant_id on the Application it owns; thereafter, every write
  action that names a specific application ... compares the addressed
  Application's applicant_id to X-User-ID and rejects mismatches with
  ERR_FORBIDDEN.' Therefore: the per-instance builder
  make_applicant_headers(applicant_id) is mandatory whenever a write
  action targets a specific application — the applicant_id used at
  Application creation MUST be threaded through every subsequent call.

- Secretary: opaque operator identifier. Shared constant is canonical.

- Chairperson: ENTITY-BACKED. PRD §2.1: 'X-User-ID is the id of the
  acting CommitteeMember; the member referenced must currently be
  active. Ownership checks on any action a chair performs compare
  against this CommitteeMember.id.' make_chair_headers(member_id) is
  required wherever an actual member id is the caller.

- CommitteeMember: ENTITY-BACKED. PRD §2.1: 'X-User-ID is the id of the
  acting CommitteeMember; attendance and vote endpoints compare the
  resource's member_id to X-User-ID.' make_committee_member_headers(
  member_id) is required whenever the request is ownership-gated.

- RegulatoryWatcher: opaque external-observer identifier. Shared
  constant is canonical.

Fall-back constants in TEST_USERS exist only for tests whose success
does NOT depend on the caller owning the subject resource (missing-
auth, wrong-role, missing-resource). For ownership-gated calls, the
builder MUST be used with the actual entity's id.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and non-binding fallbacks
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "secretary_headers": build_user_headers(
        "secretary-001", "Secretary",
    ),
    "secretary_headers_alt": build_user_headers(
        "secretary-002", "Secretary",
    ),
    "regulatory_watcher_headers": build_user_headers(
        "watcher-001", "RegulatoryWatcher",
    ),
    # Applicant fallback — useful only for tests where the call is NOT
    # gated by Application ownership (e.g., wrong-role or missing-resource).
    "applicant_headers": build_user_headers(
        "applicant-fallback", "Applicant",
    ),
    # Entity-backed fallbacks — use ONLY for tests that do not exercise
    # ownership (missing-auth, wrong-role, missing-resource).
    "chairperson_headers": build_user_headers(
        "chair-fallback", "Chairperson",
    ),
    "committee_member_headers": build_user_headers(
        "member-fallback", "CommitteeMember",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. PRD §2.1 ownership rules:
# ---------------------------------------------------------------------------
def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Applicant, X-User-ID is an opaque
    principal-investigator identifier ... The server records it as
    applicant_id on the Application it owns; thereafter, every write
    action that names a specific application ... compares the addressed
    Application's applicant_id to X-User-ID.'

    Use this builder whenever a write action targets an Application; the
    id used here MUST match Application.applicant_id (whatever string
    was used at Application creation time)."""
    return build_user_headers(applicant_id, "Applicant")


def make_secretary_headers(
    user_id: str = "secretary-001",
) -> Dict[str, str]:
    """PRD §2.1: Secretary X-User-ID is an opaque operator identifier."""
    return build_user_headers(user_id, "Secretary")


def make_chair_headers(member_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Chairperson, X-User-ID is the id
    of the acting CommitteeMember; the member referenced must currently
    be active.' Pass the active CommitteeMember.id."""
    return build_user_headers(member_id, "Chairperson")


def make_committee_member_headers(member_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is CommitteeMember, X-User-ID is the
    id of the acting CommitteeMember; attendance and vote endpoints
    compare the resource's member_id to X-User-ID.' Pass the actual
    CommitteeMember.id whenever the call is ownership-gated."""
    return build_user_headers(member_id, "CommitteeMember")


def make_regulatory_watcher_headers(
    user_id: str = "watcher-001",
) -> Dict[str, str]:
    """PRD §2.1: RegulatoryWatcher X-User-ID is an opaque external-
    observer identifier."""
    return build_user_headers(user_id, "RegulatoryWatcher")


__all__ = [
    "TEST_USERS",
    "make_applicant_headers",
    "make_secretary_headers",
    "make_chair_headers",
    "make_committee_member_headers",
    "make_regulatory_watcher_headers",
]
