"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the five opaque roles (whose X-User-ID is never
# compared against any entity id), and for tests that do not exercise ownership.
# VolunteerDriver is entity-backed: the shared constant here is a fallback used
# only for non-ownership tests (e.g. a wrong-driver 403). Ownership-gated success
# paths (delivery completion) MUST use make_volunteer_driver_headers(driver_id).
TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "nutritionist_headers": build_user_headers("nutritionist-1", "Nutritionist"),
    "route_manager_headers": build_user_headers("route-manager-1", "RouteManager"),
    "program_admin_headers": build_user_headers("program-admin-1", "ProgramAdmin"),
    "contribution_clerk_headers": build_user_headers("contribution-clerk-1", "ContributionClerk"),
    "volunteer_driver_headers": build_user_headers("driver-shared", "VolunteerDriver"),
}


# ---- Per-instance builders ----
def make_intake_coordinator_headers(user_id: str = "intake-1") -> dict:
    """Opaque IntakeCoordinator identity."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_nutritionist_headers(user_id: str = "nutritionist-1") -> dict:
    """Opaque Nutritionist identity."""
    return build_user_headers(user_id, "Nutritionist")


def make_route_manager_headers(user_id: str = "route-manager-1") -> dict:
    """Opaque RouteManager identity."""
    return build_user_headers(user_id, "RouteManager")


def make_program_admin_headers(user_id: str = "program-admin-1") -> dict:
    """Opaque ProgramAdmin identity."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_contribution_clerk_headers(user_id: str = "contribution-clerk-1") -> dict:
    """Opaque ContributionClerk identity; recorded in acknowledged_by where applicable."""
    return build_user_headers(user_id, "ContributionClerk")


def make_volunteer_driver_headers(user_id: str) -> dict:
    """For VolunteerDriver (entity-backed). Pass the acting driver's id as user_id so
    the delivery-completion ownership check (route.driver_id == X-User-ID) passes."""
    return build_user_headers(user_id, "VolunteerDriver")
