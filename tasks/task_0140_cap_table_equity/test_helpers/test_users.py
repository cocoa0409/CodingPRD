"""Pre-built role headers for every role in the PRD (§2.1).

Administrator, BoardApprover, Auditor carry OPAQUE identity — X-User-ID is an
operator id never matched against any entity, so a shared constant is the
canonical form. Stakeholder is ENTITY-BACKED (X-User-ID is the acting
Shareholder.id); ownership-gated calls MUST use make_stakeholder_headers(shareholder_id).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these as their canonical form. The
# Stakeholder shared constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "administrator_headers": build_user_headers("admin-1", "Administrator"),
    "board_approver_headers": build_user_headers("approver-1", "BoardApprover"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # Fallback for ownership-agnostic Stakeholder tests; not tied to a real Shareholder.
    "stakeholder_headers": build_user_headers("stakeholder-1", "Stakeholder"),
}


def make_administrator_headers(user_id: str) -> dict:
    """Administrator with an explicit X-User-ID (opaque). Used to drive the
    segregation-of-duties tests where the drafter's id must be controlled."""
    return build_user_headers(user_id, "Administrator")


def make_board_approver_headers(user_id: str) -> dict:
    """BoardApprover with an explicit X-User-ID (opaque). approved_by_user_id is
    stamped from this id; used to ensure the approver differs from the drafter."""
    return build_user_headers(user_id, "BoardApprover")


def make_stakeholder_headers(shareholder_id: str) -> dict:
    """For Stakeholder (entity_backed:Shareholder). Pass the actual Shareholder.id
    as user_id whenever the call is ownership-gated (exercise / file election /
    own-holding read)."""
    return build_user_headers(shareholder_id, "Stakeholder")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
