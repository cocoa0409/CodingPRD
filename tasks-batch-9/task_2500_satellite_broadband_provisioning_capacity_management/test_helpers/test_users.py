"""Pre-built role headers for every role in the PRD.

Four roles carry opaque identity — their `X-User-ID` is an operator identifier the
server never compares to any record's `id`, so a shared constant is the canonical
form. `Subscriber` identity is entity backed: `X-User-ID` must be the `id` of the
acting subscriber account, so ownership-gated calls MUST use
`make_subscriber_headers(subscriber_id)`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles. The Subscriber entry is a
# fallback only for calls that never reach an ownership comparison (for example
# a 401/403/400 rejection or a not-found path).
TEST_USERS = {
    "provisioning_agent_headers": build_user_headers(
        "op-provisioning-1", "ProvisioningAgent"
    ),
    "provisioning_agent_2_headers": build_user_headers(
        "op-provisioning-2", "ProvisioningAgent"
    ),
    "network_ops_engineer_headers": build_user_headers(
        "op-netops-1", "NetworkOpsEngineer"
    ),
    "compliance_officer_headers": build_user_headers(
        "op-compliance-1", "ComplianceOfficer"
    ),
    "compliance_officer_2_headers": build_user_headers(
        "op-compliance-2", "ComplianceOfficer"
    ),
    "logistics_coordinator_headers": build_user_headers(
        "op-logistics-1", "LogisticsCoordinator"
    ),
    "subscriber_headers": build_user_headers("sub-not-a-real-account", "Subscriber"),
}


def make_provisioning_agent_headers(user_id: str) -> dict:
    """ProvisioningAgent headers for a named operator identifier.

    Use when a test needs two distinct operators — for example the submitting
    operator of an outage credit whose identifier is stored in
    `submitted_by_user_id`.
    """
    return build_user_headers(user_id, "ProvisioningAgent")


def make_network_ops_engineer_headers(user_id: str) -> dict:
    """NetworkOpsEngineer headers for a named operator identifier."""
    return build_user_headers(user_id, "NetworkOpsEngineer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers for a named operator identifier.

    Deciding an outage credit compares this identifier against the credit's
    `submitted_by_user_id`, so tests of that separation rule must build both
    sides explicitly.
    """
    return build_user_headers(user_id, "ComplianceOfficer")


def make_logistics_coordinator_headers(user_id: str) -> dict:
    """LogisticsCoordinator headers for a named operator identifier."""
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_subscriber_headers(subscriber_id: str) -> dict:
    """Subscriber headers. `subscriber_id` MUST be the acting account's `id`.

    Every ownership check compares the target resource's subscriber chain to
    this value, so passing anything other than a real account id is rejected
    with ERR_NOT_RESOURCE_OWNER.
    """
    return build_user_headers(subscriber_id, "Subscriber")
