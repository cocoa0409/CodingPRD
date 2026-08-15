"""Pre-built role headers for every role in the PRD.

Per PRD section "User and Role-Based Access Control": the five staff roles
are opaque identities — the server does not compare X-User-ID to any entity
id. AircraftOwner and CrewMember are entity-backed: X-User-ID must equal the
acting entity's id whenever the call is ownership-gated (an owner reading its
own statements; a crew member recording a flight log as the trip's VETTED
PIC). The shared TEST_USERS constants for those two roles are only safe for
tests whose outcome does not depend on ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque staff roles: shared constants are the canonical form.
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "sales_agent_headers": build_user_headers("test-sales-1", "SalesAgent"),
    "dispatch_manager_headers": build_user_headers("test-dispatch-1", "DispatchManager"),
    "maintenance_controller_headers": build_user_headers("test-mx-1", "MaintenanceController"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Entity-backed roles: fallback constants for non-ownership tests only.
    "aircraft_owner_headers": build_user_headers("test-owner-1", "AircraftOwner"),
    "crew_member_headers": build_user_headers("test-crew-1", "CrewMember"),
}


def make_ops_admin_headers(user_id: str = "test-ops-admin-1") -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_sales_agent_headers(user_id: str = "test-sales-1") -> dict:
    return build_user_headers(user_id, "SalesAgent")


def make_dispatch_manager_headers(user_id: str = "test-dispatch-1") -> dict:
    return build_user_headers(user_id, "DispatchManager")


def make_maintenance_controller_headers(user_id: str = "test-mx-1") -> dict:
    return build_user_headers(user_id, "MaintenanceController")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_aircraft_owner_headers(user_id: str) -> dict:
    """For AircraftOwner (entity_backed:AircraftOwner). Pass the actual
    AircraftOwner.id whenever the call is ownership-gated (statement lists)."""
    return build_user_headers(user_id, "AircraftOwner")


def make_crew_member_headers(user_id: str) -> dict:
    """For CrewMember (entity_backed:CrewMember). Pass the actual
    CrewMember.id whenever the call is ownership-gated (flight log recording
    requires the trip's VETTED PIC)."""
    return build_user_headers(user_id, "CrewMember")
