"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (FirmAdmin, Billing) whose X-User-ID is not tied
# to any persisted entity, and for entity-backed roles in tests that do NOT exercise ownership.
TEST_USERS = {
    "firm_admin_headers": build_user_headers("firm-admin-1", "FirmAdmin"),
    "billing_headers": build_user_headers("billing-1", "Billing"),
    # entity_backed fallbacks (non-ownership tests only):
    "analyst_headers": build_user_headers("analyst-shared", "Analyst"),
    "client_headers": build_user_headers("client-shared", "Client"),
}


def make_analyst_headers(user_id: str) -> dict:
    """For Analyst (entity_backed:Analyst). Pass the actual Analyst.id as user_id
    whenever the call is ownership-gated or records the acting analyst (e.g. created_by_analyst_id)."""
    return build_user_headers(user_id, "Analyst")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated (portal accept/pay/read-own)."""
    return build_user_headers(user_id, "Client")


def make_firm_admin_headers(user_id: str = "firm-admin-1") -> dict:
    return build_user_headers(user_id, "FirmAdmin")


def make_billing_headers(user_id: str = "billing-1") -> dict:
    return build_user_headers(user_id, "Billing")
