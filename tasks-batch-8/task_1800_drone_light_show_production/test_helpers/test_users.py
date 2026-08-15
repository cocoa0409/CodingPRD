"""Pre-built role headers for every role in the PRD.

All five roles use opaque operator identifiers: X-User-ID is never
compared to any entity's id. It is only recorded into audit fields
(created_by_user_id, approved_by_user_id, decided_by, certified_by_user_id,
filed_by_user_id, closed_by_user_id) and compared against those fields by
the segregation-of-duties checks. The shared constants below are therefore
canonical; the per-instance builders exist so tests can deliberately
collide with (or avoid) a recorded audit id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical form for every role (all identities opaque).
TEST_USERS = {
    "planner_headers": build_user_headers("planner-1", "ProductionPlanner"),
    "planner_2_headers": build_user_headers("planner-2", "ProductionPlanner"),
    "authority_headers": build_user_headers("ao-1", "AuthorityOfficer"),
    "authority_2_headers": build_user_headers("ao-2", "AuthorityOfficer"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    "safety_officer_2_headers": build_user_headers("so-2", "SafetyOfficer"),
    "fleet_manager_headers": build_user_headers("fm-1", "FleetManager"),
    "ops_admin_headers": build_user_headers("ops-1", "OpsAdmin"),
}


def make_planner_headers(user_id: str = "planner-1") -> dict:
    """ProductionPlanner headers for a specific acting user id."""
    return build_user_headers(user_id, "ProductionPlanner")


def make_authority_headers(user_id: str = "ao-1") -> dict:
    """AuthorityOfficer headers for a specific acting user id."""
    return build_user_headers(user_id, "AuthorityOfficer")


def make_safety_officer_headers(user_id: str = "so-1") -> dict:
    """SafetyOfficer headers for a specific acting user id. Pass a user id
    equal to a recorded audit field to exercise segregation of duties, or a
    distinct one to pass it."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_fleet_manager_headers(user_id: str = "fm-1") -> dict:
    """FleetManager headers for a specific acting user id."""
    return build_user_headers(user_id, "FleetManager")


def make_ops_admin_headers(user_id: str = "ops-1") -> dict:
    """OpsAdmin headers for a specific acting user id."""
    return build_user_headers(user_id, "OpsAdmin")
