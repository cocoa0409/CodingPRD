"""Pre-built role headers for every role in the PRD (§2.1).

Four roles (PlatformAdmin, CodeOfficer, HearingOfficer, FinanceClerk) carry an
opaque identity that is recorded but never ownership-checked, so the shared
constants below are always valid for them.

The Registrant role is entity-backed: its X-User-ID must equal the acting
Owner.id for ownership-gated calls (notice contest). Use make_registrant_headers()
with the real Owner.id whenever ownership matters; the shared constant is a
fallback only for tests that never reach an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    "code_officer_headers": build_user_headers("officer-operator-1", "CodeOfficer"),
    "hearing_officer_headers": build_user_headers("hearing-operator-1", "HearingOfficer"),
    "finance_clerk_headers": build_user_headers("finance-operator-1", "FinanceClerk"),
    # entity_backed fallback — valid ONLY for tests that do not exercise ownership.
    "registrant_headers": build_user_headers("test-registrant-1", "Registrant"),
}


def make_registrant_headers(owner_id: str) -> dict:
    """For Registrant (entity_backed:Owner). Pass the actual Owner.id as user_id
    whenever the call is ownership-gated — e.g. contesting a notice, where the
    server compares X-User-ID to the case property's owner of record."""
    return build_user_headers(owner_id, "Registrant")


def make_anonymous_headers() -> dict:
    """A request whose X-User-Role is not one of the five recognized roles."""
    return build_user_headers("anon-1", "Anonymous")
