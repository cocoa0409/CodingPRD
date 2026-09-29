"""Pre-built role headers for the eight roles in the PRD.

Seven of the eight roles carry an opaque operator identifier that the server
never compares to any entity's ``id``, so a shared constant is the canonical
form for them.  ``Builder`` is different: ``X-User-ID`` is the ``id`` of the
acting ``Builder`` row and ownership checks compare it to the resource's builder
foreign key, so every ownership-gated call MUST be made with
``make_builder_headers(builder["id"])``.

Where a transition captures authorship the operator identifier is recorded
verbatim, so the engineer / manager / sealing-engineer identities below are
distinct on purpose: the submitting user may never be the reviewing user.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identifiers — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("u_admin_1", "PlatformAdmin"),
    "sales_engineer_headers": build_user_headers("u_sales_1", "SalesEngineer"),
    "engineer_headers": build_user_headers("u_eng_1", "Engineer"),
    "engineer_two_headers": build_user_headers("u_eng_2", "Engineer"),
    "engineering_manager_headers": build_user_headers("u_mgr_1", "EngineeringManager"),
    "engineering_manager_two_headers": build_user_headers(
        "u_mgr_2", "EngineeringManager"
    ),
    "sealing_engineer_headers": build_user_headers("u_seal_1", "SealingEngineer"),
    "production_planner_headers": build_user_headers("u_plan_1", "ProductionPlanner"),
    "logistics_coordinator_headers": build_user_headers("u_log_1", "LogisticsCoordinator"),
    # Entity-backed role: this shared constant is only for tests that never pass
    # an ownership check (wrong-role, missing-resource and malformed-payload cases).
    "builder_headers": build_user_headers("u_builder_unrelated", "Builder"),
}

# The user ids the authorship fields are expected to record.
ENGINEER_USER_ID = "u_eng_1"
ENGINEER_TWO_USER_ID = "u_eng_2"
ENGINEERING_MANAGER_USER_ID = "u_mgr_1"
ENGINEERING_MANAGER_TWO_USER_ID = "u_mgr_2"
SEALING_ENGINEER_USER_ID = "u_seal_1"


def make_builder_headers(builder_id: str) -> dict:
    """Headers for a ``Builder`` acting as the given builder row.

    Pass the real ``Builder.id`` whenever the call is ownership-gated — quote
    acceptance is the only write a ``Builder`` may perform, and its ownership
    check compares the quote's ``builder_id`` to ``X-User-ID``.
    """
    return build_user_headers(builder_id, "Builder")


def make_platform_admin_headers(user_id: str = "u_admin_1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sales_engineer_headers(user_id: str = "u_sales_1") -> dict:
    return build_user_headers(user_id, "SalesEngineer")


def make_engineer_headers(user_id: str = ENGINEER_USER_ID) -> dict:
    return build_user_headers(user_id, "Engineer")


def make_engineering_manager_headers(
    user_id: str = ENGINEERING_MANAGER_USER_ID,
) -> dict:
    return build_user_headers(user_id, "EngineeringManager")


def make_sealing_engineer_headers(user_id: str = SEALING_ENGINEER_USER_ID) -> dict:
    return build_user_headers(user_id, "SealingEngineer")


def make_production_planner_headers(user_id: str = "u_plan_1") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_logistics_coordinator_headers(user_id: str = "u_log_1") -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


ALL_ROLE_NAMES = [
    "PlatformAdmin",
    "SalesEngineer",
    "Engineer",
    "EngineeringManager",
    "SealingEngineer",
    "ProductionPlanner",
    "LogisticsCoordinator",
    "Builder",
]
