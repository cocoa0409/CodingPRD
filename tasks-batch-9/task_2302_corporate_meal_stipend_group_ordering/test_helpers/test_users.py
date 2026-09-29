"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers (PRD §2.1: for PlatformAdmin, ProgramAdmin and
# BenefitsController, X-User-ID is an opaque operator identifier not tied to
# any persisted entity).
PLATFORM_ADMIN_ID = "plat-admin-1"
PROGRAM_ADMIN_ID = "prog-admin-1"

# Four distinct controller identities so the two four-eyes workflows
# (rule drafting/activation and claim resolution/settlement) can each be
# performed by two different people.
CONTROLLER_DRAFTER_ID = "ctrl-drafter"
CONTROLLER_APPROVER_ID = "ctrl-approver"
CONTROLLER_RESOLVER_ID = "ctrl-resolver"
CONTROLLER_SETTLER_ID = "ctrl-settler"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_ID, "ProgramAdmin"),
    "benefits_controller_headers": build_user_headers(
        CONTROLLER_DRAFTER_ID, "BenefitsController"
    ),
    "controller_drafter_headers": build_user_headers(
        CONTROLLER_DRAFTER_ID, "BenefitsController"
    ),
    "controller_approver_headers": build_user_headers(
        CONTROLLER_APPROVER_ID, "BenefitsController"
    ),
    "controller_resolver_headers": build_user_headers(
        CONTROLLER_RESOLVER_ID, "BenefitsController"
    ),
    "controller_settler_headers": build_user_headers(
        CONTROLLER_SETTLER_ID, "BenefitsController"
    ),
    # Entity-backed roles — these shared constants are a fallback for tests
    # that do NOT exercise ownership (e.g. 400-on-bad-payload, 403-on-role).
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "restaurant_headers": build_user_headers("test-restaurant-1", "Restaurant"),
}


def make_employee_headers(user_id: str) -> dict:
    """For Employee (identity is the acting Employee's id). Pass the real
    Employee.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Employee")


def make_restaurant_headers(user_id: str) -> dict:
    """For Restaurant (identity is the acting Restaurant's id). Pass the real
    Restaurant.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Restaurant")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_controller_headers(user_id: str) -> dict:
    """For BenefitsController. The identifier is recorded as
    drafted_by_user_id / resolved_by_user_id, so distinct ids matter."""
    return build_user_headers(user_id, "BenefitsController")


ALL_ROLE_NAMES = [
    "PlatformAdmin",
    "ProgramAdmin",
    "BenefitsController",
    "Employee",
    "Restaurant",
]
