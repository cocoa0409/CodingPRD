"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes the entity-backed RightsHolder role from the opaque
PlatformAdmin role.

For RightsHolder, ownership-gated calls (PATCH a Work, terminate a License,
sign a Contract, respond to / escalate / dismiss / resolve an InfringementCase,
etc.) require X-User-ID to equal the acting RightsHolder.id. Tests MUST call
make_rights_holder_headers(rh["id"]) — the shared TEST_USERS["rights_holder_headers"]
constant is only safe for tests whose success does NOT depend on owning a
specific resource (e.g., 401 on missing headers, 404 on missing path, role-only
authorization checks where the caller is rejected before identity is consulted).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque PlatformAdmin (whose X-User-ID is opaque
# and not compared against any entity id), and for tests that don't exercise
# RightsHolder ownership checks.
TEST_USERS = {
    # PlatformAdmin: shared constant is canonical (PRD §2.1 — opaque identity).
    "admin_headers": build_user_headers("admin-001", "PlatformAdmin"),

    # RightsHolder: shared constant is a FALLBACK for non-ownership tests only.
    # Any ownership-gated call MUST use make_rights_holder_headers(rh["id"]).
    "rights_holder_headers": build_user_headers("test-rights-holder-001", "RightsHolder"),
}


# --- Per-instance builder for the entity-backed RightsHolder role ---

def make_rights_holder_headers(rights_holder_id: str) -> dict:
    """For RightsHolder (entity-backed). Pass the actual RightsHolder.id as
    X-User-ID whenever the request is ownership-gated. PRD §2.1: 'When
    X-User-Role is RightsHolder, X-User-ID is the id of the acting RightsHolder;
    ownership checks ... compare the resource's foreign-key field to X-User-ID.'
    """
    return build_user_headers(rights_holder_id, "RightsHolder")


def make_admin_headers(admin_id: str = "admin-001") -> dict:
    """PlatformAdmin headers with optional explicit operator id.

    PRD §2.1: PlatformAdmin's X-User-ID is opaque — the server may record it
    in audit rows but does not compare it to any entity id.
    """
    return build_user_headers(admin_id, "PlatformAdmin")
