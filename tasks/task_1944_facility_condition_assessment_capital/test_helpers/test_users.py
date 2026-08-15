"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque identities: X-User-ID is not tied to any persisted
entity, so the shared constants are safe everywhere. The one place the
identifier carries semantic weight is segregation of duties on plan approval
(PRD §3.6) — tests exercising it use the make_* builders to control the id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "consultant_headers": build_user_headers("test-consultant-1", "Consultant"),
    "facility_manager_headers": build_user_headers("test-facility-manager-1",
                                                   "FacilityManager"),
    "capital_planner_headers": build_user_headers("test-capital-planner-1",
                                                  "CapitalPlanner"),
    "approver_headers": build_user_headers("test-approver-1", "Approver"),
}


def make_consultant_headers(user_id: str = "test-consultant-1") -> dict:
    return build_user_headers(user_id, "Consultant")


def make_facility_manager_headers(user_id: str = "test-facility-manager-1") -> dict:
    return build_user_headers(user_id, "FacilityManager")


def make_capital_planner_headers(user_id: str = "test-capital-planner-1") -> dict:
    return build_user_headers(user_id, "CapitalPlanner")


def make_approver_headers(user_id: str = "test-approver-1") -> dict:
    return build_user_headers(user_id, "Approver")
