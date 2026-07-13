"""Pre-built role headers for every role in the PRD.

Only the Customer role is entity-backed (its X-User-ID must be the acting
Customer's id for ownership checks). IntakeTech, LabTech, ClaimsAdjuster,
and Admin carry opaque operator ids that are never compared to any entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Customer-role tests that
# do NOT exercise ownership (e.g., 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "intake_headers": build_user_headers("test-intake-1", "IntakeTech"),
    "lab_headers": build_user_headers("test-lab-1", "LabTech"),
    "claims_headers": build_user_headers("test-claims-1", "ClaimsAdjuster"),
    # Customer fallback: only valid where ownership is not enforced.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# Per-instance builder — required for the entity_backed Customer role.
def make_customer_headers(user_id: str) -> dict:
    """For the Customer role. Pass the actual Customer.id as user_id whenever
    the call is ownership-gated (creating/reading/paying/downloading/claiming
    on that customer's own order)."""
    return build_user_headers(user_id, "Customer")
