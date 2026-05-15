"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1 identity rules — quoted in full:

- LabClerk: 'X-User-ID is an opaque operator identifier not tied to any
  persisted entity.' Shared constant is canonical.
- Tester: 'X-User-ID is the id of the acting Tester entity; ownership
  checks on any resource that references a Tester — most importantly
  the assigned_tester_id on TestTask and the tester_id on TestRecord —
  compare the resource's foreign-key field to X-User-ID.'
  Every ownership-gated Tester call MUST use make_tester_headers(
  tester['id']).
- Reviewer: 'X-User-ID is the id of the acting Reviewer entity, used to
  populate reviewer_id on Report when review is approved.' Ownership-
  gated calls MUST use make_reviewer_headers(reviewer['id']).
- Signatory: 'X-User-ID is the id of the acting Signatory entity; it is
  written to signatory_id on Report at signing time.' Ownership-gated
  calls MUST use make_signatory_headers(signatory['id']).
- LabManager: 'X-User-ID is an opaque operator identifier, recorded on
  audit and modification entries but not compared to any entity's id.'
  Shared constant is canonical.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and non-binding fallbacks for entity-backed
# roles. Use only for tests that do NOT exercise ownership.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    "lab_clerk_headers": build_user_headers(
        "lab-clerk-001", "LabClerk",
    ),
    "lab_clerk_headers_alt": build_user_headers(
        "lab-clerk-002", "LabClerk",
    ),
    "lab_manager_headers": build_user_headers(
        "lab-manager-001", "LabManager",
    ),
    "lab_manager_headers_alt": build_user_headers(
        "lab-manager-002", "LabManager",
    ),
    # Entity-backed fallback constants — these IDs do not equal any real
    # entity id, so they only support tests that do NOT need ownership.
    "tester_headers": build_user_headers(
        "tester-fallback", "Tester",
    ),
    "reviewer_headers": build_user_headers(
        "reviewer-fallback", "Reviewer",
    ),
    "signatory_headers": build_user_headers(
        "signatory-fallback", "Signatory",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity_backed Tester/Reviewer/Signatory.
# ---------------------------------------------------------------------------
def make_tester_headers(tester_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Tester, X-User-ID is the id of the
    acting Tester entity.' Pass Tester.id whenever the call is ownership-
    gated (start/complete a task, submit a record, modify a record,
    mint/submit a report)."""
    return build_user_headers(tester_id, "Tester")


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Reviewer, X-User-ID is the id of the
    acting Reviewer entity, used to populate reviewer_id on Report when
    review is approved.'"""
    return build_user_headers(reviewer_id, "Reviewer")


def make_signatory_headers(signatory_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Signatory, X-User-ID is the id of
    the acting Signatory entity; it is written to signatory_id on Report
    at signing time.'"""
    return build_user_headers(signatory_id, "Signatory")


def make_lab_clerk_headers(user_id: str) -> Dict[str, str]:
    """Opaque LabClerk header with a caller-supplied id (useful when two
    distinct clerk identifiers are needed in one test)."""
    return build_user_headers(user_id, "LabClerk")


def make_lab_manager_headers(user_id: str) -> Dict[str, str]:
    """Opaque LabManager header with a caller-supplied id."""
    return build_user_headers(user_id, "LabManager")


__all__ = [
    "TEST_USERS",
    "make_tester_headers",
    "make_reviewer_headers",
    "make_signatory_headers",
    "make_lab_clerk_headers",
    "make_lab_manager_headers",
]
