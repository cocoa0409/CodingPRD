"""Pre-built role headers for the five PRD roles.

Per PRD §2.1, identity is opaque for every role: X-User-ID is not tied to any
persisted entity and no ownership check is derived from it, so the shared
constants below are the canonical form for all calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "contractor_pm_headers": build_user_headers("test-pm-1", "CONTRACTOR_PM"),
    "foreman_headers": build_user_headers("test-foreman-1", "FOREMAN"),
    "utility_inspector_headers": build_user_headers("test-inspector-1", "UTILITY_INSPECTOR"),
    "utility_dispatcher_headers": build_user_headers("test-dispatcher-1", "UTILITY_DISPATCHER"),
    "safety_officer_headers": build_user_headers("test-safety-1", "SAFETY_OFFICER"),
}


def make_contractor_pm_headers(user_id: str = "test-pm-1") -> dict:
    return build_user_headers(user_id, "CONTRACTOR_PM")


def make_foreman_headers(user_id: str = "test-foreman-1") -> dict:
    return build_user_headers(user_id, "FOREMAN")


def make_utility_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "UTILITY_INSPECTOR")


def make_utility_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "UTILITY_DISPATCHER")


def make_safety_officer_headers(user_id: str = "test-safety-1") -> dict:
    return build_user_headers(user_id, "SAFETY_OFFICER")
