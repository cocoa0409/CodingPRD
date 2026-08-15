"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque staff identities: `X-User-ID` is never matched
against a persisted entity's `id`, so the shared constants below are the
canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "counter_rep_headers": build_user_headers("test-counter-rep-1", "CounterRep"),
    "branch_manager_headers": build_user_headers("test-branch-manager-1",
                                                 "BranchManager"),
    "route_driver_headers": build_user_headers("test-route-driver-1",
                                               "RouteDriver"),
    "trainer_headers": build_user_headers("test-trainer-1", "Trainer"),
    "service_tech_headers": build_user_headers("test-service-tech-1",
                                               "ServiceTech"),
}


def make_counter_rep_headers(user_id: str = "test-counter-rep-1") -> dict:
    return build_user_headers(user_id, "CounterRep")


def make_branch_manager_headers(user_id: str = "test-branch-manager-1") -> dict:
    return build_user_headers(user_id, "BranchManager")


def make_route_driver_headers(user_id: str = "test-route-driver-1") -> dict:
    return build_user_headers(user_id, "RouteDriver")


def make_trainer_headers(user_id: str = "test-trainer-1") -> dict:
    return build_user_headers(user_id, "Trainer")


def make_service_tech_headers(user_id: str = "test-service-tech-1") -> dict:
    return build_user_headers(user_id, "ServiceTech")
