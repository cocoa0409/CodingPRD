"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin, Underwriter and ClaimsApprover are opaque operator roles — a
shared constant header set is canonical. Policyholder and Adjuster are
entity-backed: their X-User-ID must equal the id of the Grower / Adjuster
entity they act as, so ownership-gated calls MUST use the per-instance
builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_approver_headers": build_user_headers("test-claims-approver-1", "ClaimsApprover"),
    # Entity-backed roles — fallback only for tests that never touch an
    # ownership-gated resource (e.g. pure RBAC-denial probes).
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
    "adjuster_headers": build_user_headers("test-adjuster-1", "Adjuster"),
}


def make_policyholder_headers(grower_id: str) -> dict:
    """Policyholder is entity-backed by Grower: pass the real Grower.id for any
    call that touches a grower-owned resource (reports, claims, payments)."""
    return build_user_headers(grower_id, "Policyholder")


def make_adjuster_headers(adjuster_id: str) -> dict:
    """Adjuster is entity-backed by Adjuster: pass the real Adjuster.id for any
    call gated on the claim's assigned adjuster (inspections, submit-for-review)."""
    return build_user_headers(adjuster_id, "Adjuster")


def make_approver_headers(user_id: str = "test-claims-approver-1") -> dict:
    """ClaimsApprover is opaque; the server records X-User-ID as reviewer_id.
    Use a distinct user_id when a test needs a specific approver identity."""
    return build_user_headers(user_id, "ClaimsApprover")
