"""Pre-built role headers for every role in the PRD (§2.1).

Three of the four roles (Appraiser, StoreClerk, Manager) have `opaque` identity —
their X-User-ID is an operator identifier never compared to any entity id, so the
shared constants below are the canonical form for those roles.

The `Patron` role is entity-backed: ownership checks on GET /patrons/{id} compare
X-User-ID to the patron's own id. Use make_patron_headers(patron_id) whenever a
Patron reads its own owned resource. All state-changing operations are performed by
the opaque operator roles, so shared constants suffice for every write path.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque operator roles — shared constant is canonical
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
    "storeclerk_headers": build_user_headers("test-clerk-1", "StoreClerk"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    # entity-backed Patron role — shared constant only for non-ownership reads
    "patron_headers": build_user_headers("test-patron-1", "Patron"),
}


def make_patron_headers(user_id: str) -> dict:
    """Headers for the Patron role (entity_backed:Patron). Pass the actual Patron.id
    as user_id when the call is ownership-gated (e.g. a patron reading own profile)."""
    return build_user_headers(user_id, "Patron")
