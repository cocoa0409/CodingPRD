"""Pre-built role headers for the four roles of PRD §2.1.

CustomerAdmin is entity-backed: its X-User-ID must be the acting Company's id
whenever the call is ownership-gated (PRD §2.1). Use make_customer_admin_headers
with the real company id for any company-scoped call; the shared
TEST_USERS["customer_admin_headers"] constant is a fallback only for tests that
never pass an ownership check (e.g. malformed-payload or cross-company denial
tests).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — X-User-ID is not tied to any persisted entity (PRD §2.1).
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "ops_agent_headers": build_user_headers("test-ops-agent-1", "OpsAgent"),
    "counsel_headers": build_user_headers("test-counsel-1", "Counsel"),
    # entity_backed:Company — fallback for non-ownership-gated calls only.
    "customer_admin_headers": build_user_headers("test-customer-admin-1", "CustomerAdmin"),
}


def make_customer_admin_headers(company_id: str) -> dict:
    """CustomerAdmin headers whose X-User-ID is the acting Company's id.

    Mandatory for any company-scoped call (project create, notices, claims,
    waivers, payments, bonding, referrals, stop notices, bond claims).
    """
    return build_user_headers(company_id, "CustomerAdmin")
