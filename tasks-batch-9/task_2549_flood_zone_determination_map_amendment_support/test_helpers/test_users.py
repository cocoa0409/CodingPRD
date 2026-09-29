"""Pre-built role headers for every role named in the PRD (PRD 2.1).

Identity semantics differ by role.  A ``Lender`` caller's ``X-User-ID`` is the
``id`` of the acting Lender row, so ownership-gated calls MUST use
``make_lender_headers(lender["id"])``.  A ``Borrower`` caller's ``X-User-ID``
is the opaque string compared against the folio's ``borrower_user_id``, so
borrower calls MUST use ``make_borrower_headers(folio["borrower_user_id"])``.
``ProviderAnalyst``, ``ProviderReviewer`` and ``AgencyOfficer`` identities are
opaque operator identifiers that the server records but never compares to any
entity's ``id``.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque operator roles and for any test whose
# outcome does not depend on the caller owning the subject folio.
TEST_USERS = {
    "provider_analyst_headers": build_user_headers("analyst-1", "ProviderAnalyst"),
    "provider_analyst_2_headers": build_user_headers("analyst-2", "ProviderAnalyst"),
    "provider_reviewer_headers": build_user_headers("reviewer-1", "ProviderReviewer"),
    "provider_reviewer_2_headers": build_user_headers("reviewer-2", "ProviderReviewer"),
    "agency_officer_headers": build_user_headers("agency-1", "AgencyOfficer"),
    "agency_officer_2_headers": build_user_headers("agency-2", "AgencyOfficer"),
    # entity_backed Lender: this shared constant is a deliberate non-owner.
    "lender_headers": build_user_headers("lender-not-a-real-row", "Lender"),
    # opaque Borrower identifier: the canonical borrower of the default folio.
    "borrower_headers": build_user_headers("borrower-a", "Borrower"),
}

ANALYST_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"
REVIEWER_USER_ID = "reviewer-1"
REVIEWER_2_USER_ID = "reviewer-2"
AGENCY_USER_ID = "agency-1"
AGENCY_2_USER_ID = "agency-2"
BORROWER_USER_ID = "borrower-a"


def make_lender_headers(lender_id: str) -> dict:
    """For a Lender caller (X-User-ID is the acting Lender row's id)."""
    return build_user_headers(lender_id, "Lender")


def make_borrower_headers(borrower_user_id: str) -> dict:
    """For a Borrower caller (X-User-ID is the folio's borrower_user_id)."""
    return build_user_headers(borrower_user_id, "Borrower")


def make_analyst_headers(user_id: str = ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, "ProviderAnalyst")


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "ProviderReviewer")


def make_agency_headers(user_id: str = AGENCY_USER_ID) -> dict:
    return build_user_headers(user_id, "AgencyOfficer")


def role_only_headers(role: str) -> dict:
    """Headers carrying X-User-Role but no X-User-ID.

    PRD 2.1: read-only requests may omit X-User-ID.
    """
    return {"X-User-Role": role}


def user_id_only_headers(user_id: str) -> dict:
    """Headers carrying X-User-ID but no X-User-Role."""
    return {"X-User-ID": user_id}
