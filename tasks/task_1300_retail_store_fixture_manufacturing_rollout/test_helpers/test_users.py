"""Pre-built role headers for every role in the PRD.

All nine roles are opaque: PRD section 2.1 states X-User-ID "is an opaque
operator identifier that is not tied to any persisted entity and is never
compared against any resource's `id`". Shared constants are therefore the
canonical form. Per-instance builders exist so segregation-of-duties tests can
pin a specific X-User-ID against the recorded submitter/approver fields.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "program_manager_headers": build_user_headers("pm-shared-1", "ProgramManager"),
    "fixture_engineer_headers": build_user_headers("eng-shared-1", "FixtureEngineer"),
    "config_coordinator_headers": build_user_headers("cc-shared-1", "ConfigCoordinator"),
    "production_planner_headers": build_user_headers("pp-shared-1", "ProductionPlanner"),
    "warehouse_lead_headers": build_user_headers("wl-shared-1", "WarehouseLead"),
    "install_crew_lead_headers": build_user_headers("icl-shared-1", "InstallCrewLead"),
    "hotline_agent_headers": build_user_headers("ha-shared-1", "HotlineAgent"),
    "store_manager_headers": build_user_headers("sm-shared-1", "StoreManager"),
    "platform_admin_headers": build_user_headers("pa-shared-1", "PlatformAdmin"),
}


def make_program_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramManager")


def make_fixture_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FixtureEngineer")


def make_config_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConfigCoordinator")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_warehouse_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseLead")


def make_install_crew_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "InstallCrewLead")


def make_hotline_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HotlineAgent")


def make_store_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
