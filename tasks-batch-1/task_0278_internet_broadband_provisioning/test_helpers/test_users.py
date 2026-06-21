"""Pre-built role headers for every role in the PRD.

All four roles use an opaque identity model (PRD §2.1): X-User-ID is never
resolved against an entity primary key. The one ownership relationship the
server enforces is keyed on the stored Account.customer_user_id field — so for
Customer-ownership tests, headers are built with build_customer_headers(user_id)
passing the exact customer_user_id the account was created with.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles, safe for every non-ownership test.
TEST_USERS = {
    "customer_headers": build_user_headers("cust-shared", "Customer"),
    "provisioning_agent_headers": build_user_headers("agent-1", "ProvisioningAgent"),
    "network_ops_headers": build_user_headers("netops-1", "NetworkOps"),
    "dispatcher_headers": build_user_headers("dispatch-1", "Dispatcher"),
}


def build_customer_headers(customer_user_id: str) -> dict:
    """Customer headers whose X-User-ID equals the account's customer_user_id.

    Required wherever a Customer action is ownership-gated (PRD §2.1): the server
    compares X-User-ID to Account.customer_user_id, so the header's user id must
    be the literal customer_user_id the account was created under.
    """
    return build_user_headers(customer_user_id, "Customer")
