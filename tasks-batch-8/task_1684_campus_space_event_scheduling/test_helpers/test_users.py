"""Pre-built role headers for every role in the PRD.

Four roles are operator identities whose X-User-ID is an opaque string the
server never compares to a resource id: Scheduler, ServiceCoordinator,
FacilitiesManager, FinanceAdmin.

OrgRequester is an entity identity whose X-User-ID is the id of the acting
Organization. Every ownership-gated OrgRequester call MUST be built with
make_org_requester_headers(org["id"]) — the shared constant below is only a
placeholder for tests that never exercise ownership.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Operator identities — the shared constant is the canonical form.
    "scheduler_headers": build_user_headers("op-scheduler-1", "Scheduler"),
    "scheduler_2_headers": build_user_headers("op-scheduler-2", "Scheduler"),
    "service_coordinator_headers": build_user_headers(
        "op-service-coordinator-1", "ServiceCoordinator"
    ),
    "facilities_manager_headers": build_user_headers(
        "op-facilities-manager-1", "FacilitiesManager"
    ),
    "finance_admin_headers": build_user_headers("op-finance-admin-1", "FinanceAdmin"),
    "finance_admin_2_headers": build_user_headers("op-finance-admin-2", "FinanceAdmin"),
    # Entity identity — placeholder ONLY safe for tests that do not exercise
    # ownership (for example 401/403 probes).
    "org_requester_headers": build_user_headers(
        "org-requester-placeholder", "OrgRequester"
    ),
}


def make_org_requester_headers(org_id: str) -> dict:
    """Headers for an OrgRequester acting for its own Organization.

    Pass the real Organization.id whenever the call is ownership-gated
    (event create/confirm/cancel/check-in, order approve/revision, invoice pay).
    """
    return build_user_headers(org_id, "OrgRequester")


SCHEDULER = TEST_USERS["scheduler_headers"]
SCHEDULER_2 = TEST_USERS["scheduler_2_headers"]
SERVICE_COORDINATOR = TEST_USERS["service_coordinator_headers"]
FACILITIES_MANAGER = TEST_USERS["facilities_manager_headers"]
FINANCE_ADMIN = TEST_USERS["finance_admin_headers"]
FINANCE_ADMIN_2 = TEST_USERS["finance_admin_2_headers"]
