"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Patron (entity_backed — X-User-ID must equal the acting Patron.id
for ownership-gated calls), Librarian (opaque), BranchManager (opaque).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For the opaque roles (Librarian, BranchManager) the shared
# constant is the canonical form — X-User-ID is never compared to an entity id.
# For the Patron entity_backed role the shared constant is a fallback usable ONLY
# by tests that do not exercise ownership (e.g. 404/400/401/403-on-wrong-role).
TEST_USERS = {
    "patron_headers": build_user_headers("test-patron-1", "Patron"),
    "librarian_headers": build_user_headers("test-librarian-1", "Librarian"),
    "branch_manager_headers": build_user_headers("test-manager-1", "BranchManager"),
}


def make_patron_headers(patron_id: str) -> dict:
    """For the Patron role (entity_backed:Patron). Pass the actual Patron.id as
    X-User-ID whenever the call is ownership-gated (renew/cancel/return/book own
    resource) — PRD §2.1."""
    return build_user_headers(patron_id, "Patron")


def make_librarian_headers(user_id: str = "test-librarian-1") -> dict:
    """Librarian is opaque; X-User-ID is an operator id never matched to an entity."""
    return build_user_headers(user_id, "Librarian")


def make_branch_manager_headers(user_id: str = "test-manager-1") -> dict:
    """BranchManager is opaque; X-User-ID is an operator id never matched to an entity."""
    return build_user_headers(user_id, "BranchManager")
