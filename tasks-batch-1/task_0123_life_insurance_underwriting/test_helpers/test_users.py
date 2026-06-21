"""Pre-built role headers for every role in the PRD (§2.1).

Three roles:
  - Admin       : opaque identity; X-User-ID is not tied to any entity.
  - Underwriter : entity_backed:Underwriter; X-User-ID must be the acting
                  Underwriter's id for any segregation/ownership check.
  - PolicyOwner : entity_backed:Applicant; X-User-ID must be the Applicant id
                  behind the policy for ownership checks.

Shared constants are safe ONLY for tests that do not exercise ownership/segregation
(e.g. 401/403/404/422 negative paths, or Admin calls). Ownership-gated calls MUST
use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "policyowner_headers": build_user_headers("test-policyowner-1", "PolicyOwner"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For Admin (opaque). X-User-ID is recorded but never compared to an entity id."""
    return build_user_headers(user_id, "Admin")


def make_underwriter_headers(user_id: str) -> dict:
    """For Underwriter (entity_backed:Underwriter). Pass the acting Underwriter.id
    whenever the call is segregation- or ownership-gated."""
    return build_user_headers(user_id, "Underwriter")


def make_policyowner_headers(user_id: str) -> dict:
    """For PolicyOwner (entity_backed:Applicant). Pass the Applicant.id behind the
    policy whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PolicyOwner")
