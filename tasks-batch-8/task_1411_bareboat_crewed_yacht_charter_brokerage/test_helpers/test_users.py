"""Pre-built role headers for every role in the PRD.

Only PlatformAdmin has an opaque identity (PRD 2.1: an opaque operator
identifier never compared to any resource's id), so its shared constant is
canonical. Operator, Client, RetailBroker and CentralAgent are entity-backed:
their X-User-ID must reference an existing entity (for brokers, one whose
broker_type admits the declared role), so callers MUST use the per-instance
builders below with the real entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("pa-shared-1", "PlatformAdmin"),

    # Entity-backed roles: shared constants are fallbacks for tests whose
    # outcome does not depend on the caller owning the subject resource
    # (e.g. 400-on-bad-payload probes). Never use them for ownership-gated
    # calls — the ids below reference no persisted entity.
    "operator_headers": build_user_headers("op-shared-1", "Operator"),
    "client_headers": build_user_headers("cl-shared-1", "Client"),
    "retail_broker_headers": build_user_headers("rb-shared-1", "RetailBroker"),
    "central_agent_headers": build_user_headers("ca-shared-1", "CentralAgent"),
}


def make_platform_admin_headers(user_id: str = "pa-shared-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_operator_headers(operator_id: str) -> dict:
    """For Operator (entity-backed). Pass the actual Operator.id."""
    return build_user_headers(operator_id, "Operator")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity-backed). Pass the actual Client.id."""
    return build_user_headers(client_id, "Client")


def make_retail_broker_headers(broker_id: str) -> dict:
    """For RetailBroker (entity-backed: Broker with type RETAIL_BROKER or BOTH)."""
    return build_user_headers(broker_id, "RetailBroker")


def make_central_agent_headers(broker_id: str) -> dict:
    """For CentralAgent (entity-backed: Broker with type CENTRAL_AGENT or BOTH)."""
    return build_user_headers(broker_id, "CentralAgent")
