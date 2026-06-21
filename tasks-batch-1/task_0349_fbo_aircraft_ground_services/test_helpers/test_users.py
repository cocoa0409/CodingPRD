"""Pre-built role headers for every role in the PRD (§2.1).

Four staff roles (OpsDispatcher, FuelTech, BillingClerk, LineManager) are opaque:
X-User-ID is not tied to any persisted entity, so a shared constant is the canonical
form. The Operator role is entity_backed: ownership checks compare the resource's
owning operator_id to X-User-ID, so ownership-gated Operator calls MUST use
make_operator_headers(operator["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque staff roles use these as the canonical form.
TEST_USERS = {
    "ops_dispatcher_headers": build_user_headers("test-ops-1", "OpsDispatcher"),
    "fuel_tech_headers": build_user_headers("test-fuel-1", "FuelTech"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "line_manager_headers": build_user_headers("test-line-1", "LineManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    # (e.g. ERR_FORBIDDEN_ROLE / ERR_NOT_RESOURCE_OWNER negative cases).
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
}


# Per-instance builder — REQUIRED for the entity_backed Operator role.
def make_operator_headers(operator_id: str) -> dict:
    """For the Operator role (entity_backed:Operator). Pass the actual Operator.id as
    user_id whenever the call is ownership-gated (re-request slot, own reads, etc.)."""
    return build_user_headers(operator_id, "Operator")
