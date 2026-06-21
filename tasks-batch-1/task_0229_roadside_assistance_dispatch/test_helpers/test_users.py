"""Pre-built role headers for every role in the PRD (Roadside Assistance Dispatch).

  - DispatchOperator is an opaque operator identity (PRD §2.1): X-User-ID is never
    matched to a persisted entity, so the shared constant is the canonical form.
  - Member (entity_backed:Member) and ServiceProvider (entity_backed:ServiceProvider)
    shared constants are fallbacks for tests that do NOT exercise ownership (e.g.
    401/403/404 negative tests). Ownership-gated calls MUST use the per-instance
    builders below with the real entity id, because the server compares X-User-ID to
    the resource's member/provider reference.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "dispatch_operator_headers": build_user_headers("test-operator-1", "DispatchOperator"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "service_provider_headers": build_user_headers("test-provider-1", "ServiceProvider"),
}


# Per-instance builders — required for every entity_backed role.

def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id as X-User-ID
    whenever the call is ownership-gated (create call, cancel own call, file/resubmit
    own claim)."""
    return build_user_headers(member_id, "Member")


def make_provider_headers(provider_id: str) -> dict:
    """For ServiceProvider (entity_backed:ServiceProvider). Pass the acting
    ServiceProvider.id as X-User-ID whenever the call is ownership-gated (accept/decline
    an offer made to it, start/complete its assigned call, manage its shifts)."""
    return build_user_headers(provider_id, "ServiceProvider")
