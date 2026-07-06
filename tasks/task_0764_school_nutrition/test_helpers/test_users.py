"""Pre-built role headers for every role in the PRD.

For all five roles X-User-ID is an opaque operator identifier; the server never
compares it to any resource id. It is, however, recorded on menu submit and on
claim create/submit so that later segregation-of-duties checks can compare the
acting X-User-ID against the recorded value. Tests that exercise segregation of
duties MUST therefore control X-User-ID explicitly via the make_* builders.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — one default identity per role.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "menu_planner_headers": build_user_headers("planner-1", "MenuPlanner"),
    "nutrition_director_headers": build_user_headers("director-1", "NutritionDirector"),
    "cafeteria_manager_headers": build_user_headers("cafeteria-1", "CafeteriaManager"),
    "pos_clerk_headers": build_user_headers("clerk-1", "POSClerk"),
}

# Headers carrying a user id but NO recognized role (for the unauthenticated path).
NO_ROLE_HEADERS = {"X-User-ID": "nobody-1", "Content-Type": "application/json"}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MenuPlanner")


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NutritionDirector")


def make_cafeteria_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CafeteriaManager")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "POSClerk")
