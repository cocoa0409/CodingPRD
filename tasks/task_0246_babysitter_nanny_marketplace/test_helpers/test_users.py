"""Pre-built role headers for every role in the PRD (Section 2.1).

PlatformAdmin's X-User-ID is an opaque operator identifier not tied to any
persisted entity — the shared constant is the canonical form. Family and
Caregiver are entity_backed: ownership checks compare the resource's family_id /
caregiver_id foreign key to X-User-ID, so any ownership-gated call MUST use the
per-instance builder with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque role: shared constant is canonical.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests
    # only (e.g. 403/404/validation checks where ownership is not the gate).
    "family_headers": build_user_headers("test-family-1", "Family"),
    "caregiver_headers": build_user_headers("test-caregiver-1", "Caregiver"),
}


def make_admin_headers() -> dict:
    """PlatformAdmin (opaque identity). The id is never compared to any entity."""
    return build_user_headers("test-admin-1", "PlatformAdmin")


def make_family_headers(user_id: str) -> dict:
    """For Family (entity_backed:Family). Pass the actual Family.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Family")


def make_caregiver_headers(user_id: str) -> dict:
    """For Caregiver (entity_backed:Caregiver). Pass the actual Caregiver.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Caregiver")
