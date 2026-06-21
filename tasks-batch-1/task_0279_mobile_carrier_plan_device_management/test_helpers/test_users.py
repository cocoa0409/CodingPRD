"""Pre-built role headers for every role in the PRD (§2.1).

CarrierAgent, PortingOps, and BillingSystem carry opaque X-User-ID values that
the server records for audit but never compares to an entity id. Subscriber's
X-User-ID is the id of the Account they own — ownership checks compare a
resource's owning account_id to X-User-ID — so any ownership-gated Subscriber
call MUST use make_subscriber_headers(account_id), never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Subscriber tests whose
# success does NOT depend on owning the subject resource (e.g. 401/403/404
# probes). For ownership-gated Subscriber calls, use make_subscriber_headers().
TEST_USERS = {
    "carrier_agent_headers": build_user_headers("op-carrier-agent-1", "CarrierAgent"),
    "porting_ops_headers": build_user_headers("op-porting-ops-1", "PortingOps"),
    "billing_system_headers": build_user_headers("op-billing-system-1", "BillingSystem"),
    # Subscriber shared constant: opaque fallback for non-ownership tests only.
    "subscriber_headers": build_user_headers("sub-unowned-1", "Subscriber"),
}


def make_subscriber_headers(account_id: str) -> dict:
    """For Subscriber (entity_backed:Account). Pass the owning Account.id as the
    X-User-ID whenever the call is ownership-gated (cancel line, cancel add-on,
    open port-request on own line)."""
    return build_user_headers(account_id, "Subscriber")


def make_carrier_agent_headers(user_id: str = "op-carrier-agent-1") -> dict:
    """CarrierAgent is opaque; X-User-ID is not entity-checked."""
    return build_user_headers(user_id, "CarrierAgent")


def make_porting_ops_headers(user_id: str = "op-porting-ops-1") -> dict:
    """PortingOps is opaque; X-User-ID is not entity-checked."""
    return build_user_headers(user_id, "PortingOps")


def make_billing_system_headers(user_id: str = "op-billing-system-1") -> dict:
    """BillingSystem is opaque; X-User-ID is not entity-checked."""
    return build_user_headers(user_id, "BillingSystem")
