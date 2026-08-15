"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles are opaque-identity roles: PRD §2.1 states the value of
`X-User-ID` "is an opaque operator identifier that is not tied to any persisted
entity" and the server "never compares `X-User-ID` against any entity's `id`".
Shared per-role constants are therefore safe for every call. Distinct
SafetyOfficer identities are provided for the two-person rule (PRD §2.9).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "network_planner_headers": build_user_headers("np-1", "NetworkPlanner"),
    "test_supervisor_headers": build_user_headers("ts-1", "TestSupervisor"),
    "field_technician_headers": build_user_headers("ft-1", "FieldTechnician"),
    "safety_officer_headers": build_user_headers("so-1", "SafetyOfficer"),
    "fault_crew_lead_headers": build_user_headers("fcl-1", "FaultCrewLead"),
    "dispatch_coordinator_headers": build_user_headers("dc-1", "DispatchCoordinator"),
    "asset_engineer_headers": build_user_headers("ae-1", "AssetEngineer"),
}

# Distinct SafetyOfficer identities for the segregation-of-duties workflow:
# issuer (so-1), independent grounding verifier (so-2), releaser (so-3).
SAFETY_OFFICER_1_HEADERS = build_user_headers("so-1", "SafetyOfficer")
SAFETY_OFFICER_2_HEADERS = build_user_headers("so-2", "SafetyOfficer")
SAFETY_OFFICER_3_HEADERS = build_user_headers("so-3", "SafetyOfficer")
FIELD_TECHNICIAN_1_HEADERS = build_user_headers("ft-1", "FieldTechnician")


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary operator identity of the given role."""
    return build_user_headers(user_id, role)


def make_safety_officer_headers(user_id: str) -> dict:
    """Build SafetyOfficer headers for a specific officer identity (PRD §2.9
    compares recorded X-User-ID values across issue/verify/release)."""
    return build_user_headers(user_id, "SafetyOfficer")
