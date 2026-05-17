"""Pre-built role headers for every role defined in PRD §2.1.

PRD §2.1 identity rules:

- LoanOfficer is OPAQUE: "X-User-ID is an opaque operator identifier not
  tied to any persisted entity; the server records it (for example, as
  assigned_loan_officer_id on a LoanApplication when intake captures the
  assignment) but does not compare it to any entity's id."
- ComplianceOfficer is OPAQUE: "X-User-ID is likewise an opaque operator
  identifier; the server records it as compliance_reviewer_id on the
  LoanApplication at the moment underwriting is opened, and as
  reviewer_user_id on each UDAAP review."
- Admin is OPAQUE: "X-User-ID is an opaque operator identifier with no
  entity binding."
- Borrower is ENTITY-BACKED: "When X-User-Role is Borrower, X-User-ID is
  the id of the acting Borrower; ownership checks on any resource that
  references a Borrower compare the resource's borrower_id to X-User-ID."

For the Borrower role, every Borrower-acting call whose success depends
on owning the targeted resource (POST .../disclosures/{id}/acknowledge,
GET /borrowers/{id}, GET /loan-applications/{id} as a Borrower) MUST
mint headers via make_borrower_headers(borrower["id"]) — never via the
shared BORROWER_FALLBACK_ID constant. Falling back to the shared
constant for an entity-backed role reproduces the canonical bug: the
literal "fallback-borrower-1" never equals any real Borrower.id, so
every ownership check rejects every request.

SEGREGATION OF DUTIES — PRD §2.1 / §2.10:
- "on underwrite-decision and on clear-to-close, the actor's X-User-ID
  must not equal the compliance_reviewer_id recorded on the
  application. Violations are rejected with ERR_UDAAP_SOD_VIOLATION."
- "on the UDAAP-review endpoint: the actor's X-User-ID must equal the
  compliance_reviewer_id on the application — a compliance officer can
  only review the applications to which they have been assigned."

The LOAN_OFFICER_ID, LOAN_OFFICER_ID_ALT, COMPLIANCE_OFFICER_ID, and
COMPLIANCE_OFFICER_ID_ALT constants below let tests model two distinct
operators for SoD scenarios.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
LOAN_OFFICER_ID = "lo-001"
LOAN_OFFICER_ID_ALT = "lo-002"

COMPLIANCE_OFFICER_ID = "co-001"
COMPLIANCE_OFFICER_ID_ALT = "co-002"

ADMIN_ID = "admin-001"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
BORROWER_FALLBACK_ID = "fallback-borrower-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque LoanOfficer — shared constant is canonical.
    "loan_officer_headers": build_user_headers(
        LOAN_OFFICER_ID, "LoanOfficer",
    ),
    "loan_officer_headers_alt": build_user_headers(
        LOAN_OFFICER_ID_ALT, "LoanOfficer",
    ),
    # Opaque ComplianceOfficer — shared constant is canonical.
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer",
    ),
    "compliance_officer_headers_alt": build_user_headers(
        COMPLIANCE_OFFICER_ID_ALT, "ComplianceOfficer",
    ),
    # Opaque Admin — shared constant is canonical.
    "admin_headers": build_user_headers(ADMIN_ID, "Admin"),
    # Entity-backed Borrower fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / NotFound
    # paths where ownership is not exercised.
    "borrower_fallback_headers": build_user_headers(
        BORROWER_FALLBACK_ID, "Borrower",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Borrower.
# The runtime Borrower.id minted by POST /borrowers is the value the
# implementation compares against in ownership checks (PRD §2.1).
# ---------------------------------------------------------------------------
def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """For Borrower (entity_backed:Borrower). Pass the actual
    Borrower.id of the acting borrower.

    PRD §2.1: "When X-User-Role is Borrower, X-User-ID is the id of the
    acting Borrower; ownership checks on any resource that references a
    Borrower compare the resource's borrower_id to X-User-ID."

    Every Borrower-acting call whose success depends on owning the
    targeted resource — POST .../disclosures/{id}/acknowledge,
    GET /borrowers/{id}, GET /loan-applications/{id} as a Borrower —
    MUST use this builder, not the shared BORROWER_FALLBACK_ID constant.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_loan_officer_headers(loan_officer_id: str) -> Dict[str, str]:
    """For LoanOfficer (opaque). Any non-empty operator id is fine; the
    builder exists so tests that want a distinct loan-officer id (for
    intake assignment, SoD scenarios, or to model two different officers
    creating contention) can supply one without relying on a single
    shared constant.
    """
    return build_user_headers(loan_officer_id, "LoanOfficer")


def make_compliance_headers(compliance_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque)."""
    return build_user_headers(compliance_id, "ComplianceOfficer")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For Admin (opaque)."""
    return build_user_headers(admin_id, "Admin")


__all__ = [
    "LOAN_OFFICER_ID",
    "LOAN_OFFICER_ID_ALT",
    "COMPLIANCE_OFFICER_ID",
    "COMPLIANCE_OFFICER_ID_ALT",
    "ADMIN_ID",
    "BORROWER_FALLBACK_ID",
    "TEST_USERS",
    "make_borrower_headers",
    "make_loan_officer_headers",
    "make_compliance_headers",
    "make_admin_headers",
]
