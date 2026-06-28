"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "agency_admin_headers": build_user_headers("test-admin-1", "AgencyAdmin"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only
    # (e.g. 404-on-missing-resource, 400-on-bad-payload, RBAC-denial).
    "counselor_headers": build_user_headers("test-counselor-1", "Counselor"),
    "creditor_rep_headers": build_user_headers("test-creditor-1", "CreditorRep"),
}


def make_agency_admin_headers(user_id: str = "test-admin-1") -> dict:
    """AgencyAdmin (opaque). X-User-ID is never compared to an entity id."""
    return build_user_headers(user_id, "AgencyAdmin")


def make_counselor_headers(user_id: str) -> dict:
    """For Counselor (entity_backed:Counselor). Pass the actual Counselor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Counselor")


def make_creditor_rep_headers(user_id: str) -> dict:
    """For CreditorRep (entity_backed:Creditor). Pass the actual Creditor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CreditorRep")
