"""Pre-built role headers for every role in the PRD.

Three roles are entity-backed (Provider, Member, Employer): their X-User-ID
must be the id of the persisted resource the call acts on. Use the per-instance
builders (make_*_headers) whenever a call is ownership-gated.

Two roles are opaque (PlatformAdmin, Anonymous): X-User-ID is an untracked
operator identifier; the shared constant is the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership tests
# (e.g., 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed fallbacks — only for tests that do NOT exercise ownership.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
}


def make_admin_headers() -> dict:
    return build_user_headers("test-admin-1", "PlatformAdmin")


def make_anonymous_headers() -> dict:
    return build_user_headers("test-anon-1", "Anonymous")


def make_provider_headers(user_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id when
    the call is ownership-gated on a clinical resource."""
    return build_user_headers(user_id, "Provider")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id when the
    call is ownership-gated (booking, cancel, charge, messaging, etc.)."""
    return build_user_headers(user_id, "Member")


def make_employer_headers(user_id: str) -> dict:
    """For Employer (entity_backed:Employer). Pass the actual Employer.id when
    the call is ownership-gated (seat allocation / occupancy)."""
    return build_user_headers(user_id, "Employer")
