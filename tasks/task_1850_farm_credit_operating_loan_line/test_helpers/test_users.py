"""Pre-built role headers for every role in the PRD (section 2.1).

Borrower is entity-backed: when the caller role is Borrower, X-User-ID must be
the id of the acting Borrower record, so ownership-gated calls MUST use
make_borrower_headers(borrower["id"]). The other five roles are opaque operator
identities, never compared to any entity's id; shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Borrower (entity_backed): shared constant only for tests where the caller
    # does not need to own the subject resource (e.g. role-denial probes).
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    # Opaque roles: shared constants are the canonical form.
    "loan_officer_headers": build_user_headers("officer-1", "LoanOfficer"),
    "loan_officer2_headers": build_user_headers("officer-2", "LoanOfficer"),
    "committee_headers": build_user_headers("committee-1", "CreditCommittee"),
    "committee2_headers": build_user_headers("committee-9", "CreditCommittee"),
    "adjuster_headers": build_user_headers("adjuster-1", "InsuranceAdjuster"),
    "board_headers": build_user_headers("board-1", "AssociationBoard"),
    "system_headers": build_user_headers("system-1", "System"),
}


def make_borrower_headers(user_id: str) -> dict:
    """For the Borrower role (entity-backed). Pass the actual Borrower.id as
    user_id whenever the call is ownership-gated (own draws, budgets,
    repayments, deferrals, claims, policies)."""
    return build_user_headers(user_id, "Borrower")


def make_officer_headers(user_id: str) -> dict:
    """LoanOfficer with a specific opaque operator id (segregation anchors)."""
    return build_user_headers(user_id, "LoanOfficer")


def make_committee_headers(user_id: str) -> dict:
    """CreditCommittee with a specific opaque operator id (segregation anchors)."""
    return build_user_headers(user_id, "CreditCommittee")
