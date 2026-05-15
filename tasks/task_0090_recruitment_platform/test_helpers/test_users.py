"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- HrUser, HiringManager, HrApprover, FinanceApprover — all
  entity_backed:HrUser. X-User-ID is the id of an HrUser row.
  Ownership checks compare resource foreign-key fields (e.g., an
  Offer's hm_approver_user_id; an InterviewRound's interviewer_user_ids
  membership) and HR-binding integrity (HrUser.binding_status==ACTIVE
  against the target Company) against X-User-ID. The role header
  selects which approval stage the caller is asserting; the identity
  still resolves to a single HrUser.id. The shared constant is NOT
  bound to any company — use it only for tests where the request
  fails before HR-binding integrity (e.g., missing-resource 404).
  Ownership-gated tests MUST use make_hr_user_headers(hr_user["id"]).

- Candidate — entity_backed:Candidate. X-User-ID must equal a
  Candidate.id when the request is ownership-gated (reading a
  Candidate row, reading own Application/Offer, accepting an offer,
  confirming an interview slot). The shared constant is acceptable
  ONLY for tests where the request fails before ownership (e.g.,
  malformed payload on registration). For registration itself, the
  server creates the row from the request body; tests that need the
  resulting candidate must use the returned id for subsequent calls.

- HeadhunterUser — entity_backed:HeadhunterContract. X-User-ID is a
  HeadhunterContract.id (PRD §2.1: "the headhunter acts under a
  specific contract"). Ownership-gated calls (read own commission
  records) MUST use make_headhunter_headers(contract["id"]).

- PlatformAdmin — opaque. X-User-ID is not tied to any persisted
  entity; the shared constant is canonical.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifier — PlatformAdmin.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "admin-001"
PLATFORM_ADMIN_ID_ALT = "admin-002"


# ---------------------------------------------------------------------------
# Fallback string identifiers for entity_backed roles. These do NOT match
# any real persisted entity id, so they MUST NOT be used by tests whose
# success depends on ownership or HR-binding integrity. They exist for
# unauthorised/forbidden/payload-validation paths only.
# ---------------------------------------------------------------------------
HR_USER_FALLBACK_ID = "hr-user-fallback-001"
CANDIDATE_FALLBACK_ID = "candidate-fallback-001"
HEADHUNTER_FALLBACK_ID = "headhunter-fallback-001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin (opaque) — canonical shared constants.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),

    # HrUser fallback — for non-ownership tests (malformed payload, 404
    # on missing resource, wrong-role checks). Ownership-gated calls
    # MUST use make_hr_user_headers(hr_user["id"]).
    "hr_user_fallback_headers": build_user_headers(
        HR_USER_FALLBACK_ID, "HrUser",
    ),

    # Candidate fallback — for non-ownership tests only.
    "candidate_fallback_headers": build_user_headers(
        CANDIDATE_FALLBACK_ID, "Candidate",
    ),

    # HeadhunterUser fallback — for non-ownership tests only.
    "headhunter_fallback_headers": build_user_headers(
        HEADHUNTER_FALLBACK_ID, "HeadhunterUser",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for ownership-gated calls.
# ---------------------------------------------------------------------------
def make_hr_user_headers(hr_user_id: str) -> Dict[str, str]:
    """For HrUser. Pass the actual HrUser.id whenever the request is
    HR-binding- or HrUser-ownership-gated (most HR-side action endpoints)."""
    return build_user_headers(hr_user_id, "HrUser")


def make_hiring_manager_headers(hr_user_id: str) -> Dict[str, str]:
    """For HiringManager. Same identity rule as HrUser; the role tag
    selects the offer-approval stage being asserted (PRD §2.1, §3.6)."""
    return build_user_headers(hr_user_id, "HiringManager")


def make_hr_approver_headers(hr_user_id: str) -> Dict[str, str]:
    """For HrApprover (the second offer-approval stage). Same identity
    rule as HrUser. The actor must differ from the HiringManager (PRD §3.6)."""
    return build_user_headers(hr_user_id, "HrApprover")


def make_finance_approver_headers(hr_user_id: str) -> Dict[str, str]:
    """For FinanceApprover (the third offer-approval stage). Same identity
    rule as HrUser. The actor must differ from HiringManager and HrApprover
    (PRD §3.6)."""
    return build_user_headers(hr_user_id, "FinanceApprover")


def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """For Candidate. Pass the actual Candidate.id whenever the request
    is ownership-gated (PRD §2.1)."""
    return build_user_headers(candidate_id, "Candidate")


def make_headhunter_headers(contract_id: str) -> Dict[str, str]:
    """For HeadhunterUser. Pass the actual HeadhunterContract.id (PRD §2.1:
    "the headhunter acts under a specific contract, not as a free-standing
    person")."""
    return build_user_headers(contract_id, "HeadhunterUser")


def make_platform_admin_headers(admin_id: str = PLATFORM_ADMIN_ID
                                ) -> Dict[str, str]:
    """For PlatformAdmin. X-User-ID is opaque (PRD §2.1) — defaults to
    the canonical shared constant; pass an alternate string when a test
    wants a distinct actor_user_id on an AuditEvent."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "HR_USER_FALLBACK_ID",
    "CANDIDATE_FALLBACK_ID",
    "HEADHUNTER_FALLBACK_ID",
    "TEST_USERS",
    "make_hr_user_headers",
    "make_hiring_manager_headers",
    "make_hr_approver_headers",
    "make_finance_approver_headers",
    "make_candidate_headers",
    "make_headhunter_headers",
    "make_platform_admin_headers",
]
