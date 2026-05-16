"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Parent is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Parent,
  X-User-ID is the id of the acting ParentAccount; any ownership check
  on a Student, FrlApplication, AllergyProfileEntry, or top-up/refund
  operation compares the resource's parent_account_id (directly, or via
  the student's parent_account_id) to the header value." Every Parent
  call whose success depends on owning the targeted Student /
  FrlApplication / AllergyProfileEntry / ParentAccount MUST mint
  headers via make_parent_headers(parent_account["id"]) — never via the
  PARENT_FALLBACK_ID shared constant.

- DistrictReviewer is OPAQUE. PRD §2.1: "The three other roles —
  DistrictReviewer, CafeteriaManager, and AuditOfficer — are opaque
  operator identifiers. Their X-User-ID is not tied to any persisted
  entity." Shared constant is canonical.

- CafeteriaManager is OPAQUE per the same passage.

- AuditOfficer is OPAQUE per the same passage.

The PARENT_FALLBACK_ID shared constant is ONLY safe for tests that DO
NOT exercise ownership (header-missing, role-mismatch, NotFound paths).
Ownership-gated calls MUST use the per-instance builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — DistrictReviewer, CafeteriaManager,
# and AuditOfficer are all opaque per PRD §2.1.
# ---------------------------------------------------------------------------
DISTRICT_REVIEWER_ID: str = "reviewer-001"
DISTRICT_REVIEWER_ID_ALT: str = "reviewer-002"
CAFETERIA_MANAGER_ID: str = "cafeteria-001"
CAFETERIA_MANAGER_ID_ALT: str = "cafeteria-002"
AUDIT_OFFICER_ID: str = "audit-001"
AUDIT_OFFICER_ID_ALT: str = "audit-002"

# Parent fallback id — ONLY safe for tests that do NOT exercise
# ownership (header-missing tests, role-mismatch tests, NotFound paths).
# Ownership-gated calls MUST instead mint headers via
# make_parent_headers(parent_account["id"]).
PARENT_FALLBACK_ID: str = "fallback-parent-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque DistrictReviewer — shared constant is canonical.
    "reviewer_headers": build_user_headers(
        DISTRICT_REVIEWER_ID, "DistrictReviewer",
    ),
    "reviewer_headers_alt": build_user_headers(
        DISTRICT_REVIEWER_ID_ALT, "DistrictReviewer",
    ),
    # Opaque CafeteriaManager — shared constant is canonical.
    "cafeteria_headers": build_user_headers(
        CAFETERIA_MANAGER_ID, "CafeteriaManager",
    ),
    "cafeteria_headers_alt": build_user_headers(
        CAFETERIA_MANAGER_ID_ALT, "CafeteriaManager",
    ),
    # Opaque AuditOfficer — shared constant is canonical.
    "audit_headers": build_user_headers(
        AUDIT_OFFICER_ID, "AuditOfficer",
    ),
    "audit_headers_alt": build_user_headers(
        AUDIT_OFFICER_ID_ALT, "AuditOfficer",
    ),
    # Entity-backed Parent fallback — DO NOT use for ownership-gated calls.
    "parent_headers": build_user_headers(PARENT_FALLBACK_ID, "Parent"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Parent role.
# The runtime ParentAccount.id minted by POST /parent-accounts is the
# value the implementation will compare against.
# ---------------------------------------------------------------------------
def make_parent_headers(parent_account_id: str) -> Dict[str, str]:
    """For Parent (entity_backed:ParentAccount). Pass the actual
    ParentAccount.id of the acting parent.

    PRD §2.1: "When X-User-Role is Parent, X-User-ID is the id of the
    acting ParentAccount; any ownership check on a Student,
    FrlApplication, AllergyProfileEntry, or top-up/refund operation
    compares the resource's parent_account_id (directly, or via the
    student's parent_account_id) to the header value." Every Parent
    call whose success depends on owning the targeted Student,
    FrlApplication, AllergyProfileEntry, or ParentAccount (e.g., POST
    /students, POST /allergy-entries, POST /frl-applications, POST
    /frl-applications/{id}/submit, POST /parent-accounts/{id}/top-up)
    MUST use this builder, not the PARENT_FALLBACK_ID shared constant.
    """
    return build_user_headers(parent_account_id, "Parent")


def make_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """For DistrictReviewer (opaque). Any non-empty operator id is
    fine; this builder is provided for tests that want a distinct
    reviewer id (e.g., for segregation-of-duties tests where two
    reviewers must be distinct).
    """
    return build_user_headers(reviewer_id, "DistrictReviewer")


def make_cafeteria_headers(manager_id: str) -> Dict[str, str]:
    """For CafeteriaManager (opaque). Any non-empty operator id is
    fine; this builder is provided for tests that want a distinct
    cafeteria-manager id (e.g., concurrent-serving race tests).
    """
    return build_user_headers(manager_id, "CafeteriaManager")


def make_audit_headers(officer_id: str) -> Dict[str, str]:
    """For AuditOfficer (opaque). Any non-empty operator id is fine;
    this builder is provided for tests that want a distinct
    audit-officer id (e.g., the AuditOfficer-finalizing-claim
    segregation-of-duties test where the finaliser must be distinct
    from the reviewer who approved the contained application).
    """
    return build_user_headers(officer_id, "AuditOfficer")


__all__ = [
    "DISTRICT_REVIEWER_ID",
    "DISTRICT_REVIEWER_ID_ALT",
    "CAFETERIA_MANAGER_ID",
    "CAFETERIA_MANAGER_ID_ALT",
    "AUDIT_OFFICER_ID",
    "AUDIT_OFFICER_ID_ALT",
    "PARENT_FALLBACK_ID",
    "TEST_USERS",
    "make_parent_headers",
    "make_reviewer_headers",
    "make_cafeteria_headers",
    "make_audit_headers",
]
