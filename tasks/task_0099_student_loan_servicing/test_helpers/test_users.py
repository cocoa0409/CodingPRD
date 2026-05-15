"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

ENTITY-BACKED role — X-User-ID is the id of a persisted entity:

  - Borrower: PRD §2.1 — "A Borrower is the end user, and is the only
    role whose identity is entity-backed. When X-User-Role is Borrower,
    X-User-ID is the id of the acting Borrower record; ownership checks
    on any nested resource (loan, plan, payment, hardship request,
    discharge application, employment certification) compare that
    resource's borrower_id field to X-User-ID, and a borrower may not
    read or mutate another borrower's resources."

    Every Borrower-role call whose success depends on owning the path-
    borrower resource MUST mint headers via make_borrower_headers(
    borrower_id) using the real Borrower.id returned by POST
    /borrowers. The shared BORROWER_FALLBACK_ID constant is ONLY safe
    for tests that DO NOT exercise ownership (header-missing checks,
    role-mismatch checks, NotFound paths, or calls where the Borrower
    role is provably not permitted for the endpoint).

OPAQUE roles — X-User-ID is an opaque operator identifier not tied to
any persisted entity row. Shared constants are PRD-correct because the
server records but does not match these against any entity id:
  - ServicerAdmin
  - ServicerCertifier (id is captured in reviewed_by on
    EmploymentCertification and HardshipRequest; segregation-of-duties
    in §2.9 compares discharge approver's id to these captured ids,
    so tests that exercise SoD need multiple DISTINCT certifier ids)
  - ServicerApprover (id captured in reviewed_by on
    DischargeApplication; SoD requires it differ from the
    EmploymentCertification certifier ids)
  - CollectionsOfficer (id captured in recorded_by on CollectionsAction)
  - SystemTest

Per PRD §2.9: "The ServicerApprover whose X-User-ID accompanies the
request that moves a DischargeApplication to APPROVED must not equal
any ServicerCertifier's X-User-ID recorded as reviewed_by on an
EmploymentCertification that is in APPROVED status for this borrower."
Therefore SoD tests need at least one ServicerCertifier id and one
ServicerApprover id that are DIFFERENT strings.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids.
# ---------------------------------------------------------------------------
SERVICER_ADMIN_ID = "servicer-admin-001"
SERVICER_ADMIN_ID_ALT = "servicer-admin-002"

SERVICER_CERTIFIER_ID = "certifier-001"
SERVICER_CERTIFIER_ID_ALT = "certifier-002"
SERVICER_CERTIFIER_ID_THIRD = "certifier-003"

# Distinct from any certifier id so that the default approver does NOT
# violate segregation of duties (PRD §2.9). Tests that intentionally
# exercise SoD violation can use SERVICER_CERTIFIER_ID as the approver
# header to force the rejection.
SERVICER_APPROVER_ID = "approver-001"
SERVICER_APPROVER_ID_ALT = "approver-002"

COLLECTIONS_OFFICER_ID = "collections-001"
COLLECTIONS_OFFICER_ID_ALT = "collections-002"

SYSTEM_TEST_ID = "system-test-001"


# ---------------------------------------------------------------------------
# Entity-backed-role fallback id. DO NOT USE for ownership-gated
# Borrower calls — use make_borrower_headers(borrower["id"]) instead,
# threading the real Borrower.id returned from POST /borrowers.
# ---------------------------------------------------------------------------
BORROWER_FALLBACK_ID = "borrower-fallback-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "servicer_admin_headers": build_user_headers(
        SERVICER_ADMIN_ID, "ServicerAdmin",
    ),
    "servicer_admin_headers_alt": build_user_headers(
        SERVICER_ADMIN_ID_ALT, "ServicerAdmin",
    ),
    "servicer_certifier_headers": build_user_headers(
        SERVICER_CERTIFIER_ID, "ServicerCertifier",
    ),
    "servicer_certifier_headers_alt": build_user_headers(
        SERVICER_CERTIFIER_ID_ALT, "ServicerCertifier",
    ),
    "servicer_certifier_headers_third": build_user_headers(
        SERVICER_CERTIFIER_ID_THIRD, "ServicerCertifier",
    ),
    "servicer_approver_headers": build_user_headers(
        SERVICER_APPROVER_ID, "ServicerApprover",
    ),
    "servicer_approver_headers_alt": build_user_headers(
        SERVICER_APPROVER_ID_ALT, "ServicerApprover",
    ),
    "collections_officer_headers": build_user_headers(
        COLLECTIONS_OFFICER_ID, "CollectionsOfficer",
    ),
    "collections_officer_headers_alt": build_user_headers(
        COLLECTIONS_OFFICER_ID_ALT, "CollectionsOfficer",
    ),
    "system_test_headers": build_user_headers(
        SYSTEM_TEST_ID, "SystemTest",
    ),

    # Entity-backed fallback — ONLY for non-ownership tests.
    "borrower_headers_fallback": build_user_headers(
        BORROWER_FALLBACK_ID, "Borrower",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """Mint Borrower headers bound to a real Borrower.id.

    PRD §2.1: "When X-User-Role is Borrower, X-User-ID is the id of
    the acting Borrower record; ownership checks on any nested
    resource ... compare that resource's borrower_id field to
    X-User-ID, and a borrower may not read or mutate another
    borrower's resources." Every borrower-side mutation (submit
    payment with source=BORROWER, create plan, activate plan, cancel
    plan, create hardship request, cancel hardship request, create
    discharge application, create employment certification, update
    self) MUST use this builder with the actual Borrower.id.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_servicer_admin_headers(admin_id: str) -> Dict[str, str]:
    return build_user_headers(admin_id, "ServicerAdmin")


def make_servicer_certifier_headers(certifier_id: str) -> Dict[str, str]:
    """For ServicerCertifier (opaque). The id is recorded in
    reviewed_by on EmploymentCertification / HardshipRequest, so SoD
    tests pin a SPECIFIC certifier id and then assert the discharge
    approver's id differs from it (PRD §2.9)."""
    return build_user_headers(certifier_id, "ServicerCertifier")


def make_servicer_approver_headers(approver_id: str) -> Dict[str, str]:
    """For ServicerApprover (opaque). PRD §2.9: must not equal any
    certifier id recorded as reviewed_by on this borrower's APPROVED
    EmploymentCertification rows."""
    return build_user_headers(approver_id, "ServicerApprover")


def make_collections_officer_headers(officer_id: str) -> Dict[str, str]:
    return build_user_headers(officer_id, "CollectionsOfficer")


def make_system_test_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "SystemTest")


__all__ = [
    "SERVICER_ADMIN_ID",
    "SERVICER_ADMIN_ID_ALT",
    "SERVICER_CERTIFIER_ID",
    "SERVICER_CERTIFIER_ID_ALT",
    "SERVICER_CERTIFIER_ID_THIRD",
    "SERVICER_APPROVER_ID",
    "SERVICER_APPROVER_ID_ALT",
    "COLLECTIONS_OFFICER_ID",
    "COLLECTIONS_OFFICER_ID_ALT",
    "SYSTEM_TEST_ID",
    "BORROWER_FALLBACK_ID",
    "TEST_USERS",
    "make_borrower_headers",
    "make_servicer_admin_headers",
    "make_servicer_certifier_headers",
    "make_servicer_approver_headers",
    "make_collections_officer_headers",
    "make_system_test_headers",
]
