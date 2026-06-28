"""Pre-built role headers for every role in the PRD (§2.1).

Five of the six roles (PlatformAdmin, SalesRep, Scheduler, WarrantyAgent) are
opaque operator identities not tied to any persisted entity, so the shared
constant is the canonical form. Customer and Crew are entity_backed: their
X-User-ID must equal the acting entity's id for ownership-gated calls, so each
gets a per-instance builder that fixtures MUST use with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe for opaque roles, and for tests that do not exercise
# resource ownership (400-on-bad-payload, 404-on-missing-resource, etc.).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sales_rep_headers": build_user_headers("test-sales-1", "SalesRep"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "warranty_agent_headers": build_user_headers("test-warranty-1", "WarrantyAgent"),
    # entity_backed fallbacks — only for non-ownership tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "crew_headers": build_user_headers("test-crew-1", "Crew"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (accept, decline, claim, resubmit)."""
    return build_user_headers(user_id, "Customer")


def make_crew_headers(user_id: str) -> dict:
    """For Crew (entity_backed:Crew). Pass the actual Crew.id as user_id whenever
    the call references that crew (start, complete)."""
    return build_user_headers(user_id, "Crew")
