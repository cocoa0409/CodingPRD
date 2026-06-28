"""Pre-built role headers for every role in the PRD.

Three roles: Accountholder (entity_backed:Accountholder), Employer
(entity_backed:Employer), AccountAdmin (opaque).

Ownership-gated calls for Accountholder/Employer MUST use the per-instance builders
below with the actual entity id, never the shared constants — the shared X-User-ID is a
string that never equals any real entity's id, so every ownership check would reject it.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque AccountAdmin, and for tests that do not exercise
# ownership (e.g. 401/403/404/422 negatives where the request never passes the ownership gate).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "AccountAdmin"),
    # second distinct admin for segregation-of-duties tests.
    "admin_b_headers": build_user_headers("test-admin-2", "AccountAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "accountholder_headers": build_user_headers("test-holder-1", "Accountholder"),
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
}


# Per-instance builders — required for every entity_backed role on ownership-gated calls.
def make_accountholder_headers(user_id: str) -> dict:
    """For Accountholder (entity_backed:Accountholder). Pass the actual Accountholder.id
    as user_id whenever the call is holder-scoped (verify, request distribution, card ops)."""
    return build_user_headers(user_id, "Accountholder")


def make_employer_headers(user_id: str) -> dict:
    """For Employer (entity_backed:Employer). Pass the actual Employer.id as user_id when
    creating/reading payroll contributions on sponsored accounts."""
    return build_user_headers(user_id, "Employer")


def make_admin_headers(user_id: str) -> dict:
    """For AccountAdmin (opaque). The X-User-ID is recorded where transitions demand it
    (e.g. Distribution.cleared_by_user_id) but never compared to any entity id. Use distinct
    user_ids to exercise the segregation-of-duties check."""
    return build_user_headers(user_id, "AccountAdmin")
