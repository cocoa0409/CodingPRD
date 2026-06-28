"""Pre-built role headers for every role in the PRD.

Three roles are operator (opaque) identities: BillingAdmin, ScreeningOfficer,
Matchmaker. Their X-User-ID is an opaque operator id never matched to an entity,
so a shared constant is the canonical form.

The Member role is entity-backed: X-User-ID must equal the acting Member's id.
Ownership-gated calls MUST use make_member_headers(member_id) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque operators use these directly. The "member_headers"
# shared constant is a fallback ONLY for tests that do not exercise ownership
# (e.g., 400/404 on a non-owned-resource shape). Ownership-gated Member calls
# must use make_member_headers(member_id).
TEST_USERS = {
    "billing_admin_headers": build_user_headers("operator-billing-1", "BillingAdmin"),
    "screening_officer_headers": build_user_headers("operator-screening-1", "ScreeningOfficer"),
    "matchmaker_headers": build_user_headers("operator-matchmaker-1", "Matchmaker"),
    "member_headers": build_user_headers("member-generic-1", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (respond, feedback, own
    preferences, own dates, own coaching, own checks)."""
    return build_user_headers(member_id, "Member")


def no_auth_headers() -> dict:
    """Headers with the auth pair stripped — used to exercise ERR_UNAUTHENTICATED."""
    return {"Content-Type": "application/json"}
