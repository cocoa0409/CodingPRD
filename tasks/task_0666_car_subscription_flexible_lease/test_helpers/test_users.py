"""Pre-built role headers for every role in the PRD (PRD §2.1).

PlatformAdmin, FleetOperator, and BillingAdmin carry opaque X-User-ID identifiers
not tied to any persisted entity, so the shared constants below are canonical for them.

Member is entity_backed:Applicant — its X-User-ID must equal the acting subscription's
applicant_id for ownership-gated calls. Use make_member_headers(applicant_id) for those;
the shared TEST_USERS["member_headers"] constant is a fallback for non-ownership tests
(e.g. 401/403/404 negative cases that never reach the ownership check).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    "fleet_operator_headers": build_user_headers("test-fleet-operator", "FleetOperator"),
    "billing_admin_headers": build_user_headers("test-billing-admin", "BillingAdmin"),
    # Fallback only — for Member tests that do NOT exercise ownership.
    "member_headers": build_user_headers("test-member", "Member"),
}


def make_member_headers(applicant_id: str) -> dict:
    """For Member (entity_backed:Applicant). Pass the actual Applicant.id as X-User-ID
    whenever the call is ownership-gated (initiate-return, early-cancel, swap-requests)."""
    return build_user_headers(applicant_id, "Member")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary (user_id, role) headers — used for unauthenticated / unknown-role tests."""
    return build_user_headers(user_id, role)
