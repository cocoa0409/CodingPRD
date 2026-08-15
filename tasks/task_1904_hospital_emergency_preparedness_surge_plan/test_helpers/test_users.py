"""Pre-built role headers for every role in the PRD (§2.1).

For the eight operational roles, X-User-ID is the id of the acting StaffMember;
ownership checks (segregation of duties, call-back ownership) compare resource
foreign keys against X-User-ID. PlatformAdmin carries an opaque identifier.

Shared constants are safe for calls that are not ownership-gated. For
ownership-gated calls (approving a plan/AAR, submitting a report, responding
to a call-back request) use the per-instance make_*_headers(user_id) builders
with the acting StaffMember's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "emergency_manager_headers": build_user_headers("test-em-1", "EmergencyManager"),
    "incident_commander_headers": build_user_headers("test-ic-1", "IncidentCommander"),
    "planning_chief_headers": build_user_headers("test-pc-1", "PlanningChief"),
    "logistics_chief_headers": build_user_headers("test-lc-1", "LogisticsChief"),
    "public_information_officer_headers": build_user_headers(
        "test-pio-1", "PublicInformationOfficer"
    ),
    "liaison_officer_headers": build_user_headers("test-lo-1", "LiaisonOfficer"),
    "hospital_administrator_headers": build_user_headers(
        "test-ha-1", "HospitalAdministrator"
    ),
    "on_call_staff_headers": build_user_headers("test-ocs-1", "OnCallStaff"),
    "platform_admin_headers": build_user_headers("test-pa-1", "PlatformAdmin"),
}


def make_emergency_manager_headers(user_id: str) -> dict:
    """EmergencyManager backed by a specific StaffMember id — required whenever
    the created resource's created_by_id participates in a SoD check."""
    return build_user_headers(user_id, "EmergencyManager")


def make_incident_commander_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IncidentCommander")


def make_planning_chief_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanningChief")


def make_logistics_chief_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LogisticsChief")


def make_public_information_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PublicInformationOfficer")


def make_liaison_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LiaisonOfficer")


def make_hospital_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HospitalAdministrator")


def make_on_call_staff_headers(user_id: str) -> dict:
    """OnCallStaff responding to a call-back request: X-User-ID must equal the
    request's staff_member_id (PRD §2.7)."""
    return build_user_headers(user_id, "OnCallStaff")


def make_platform_admin_headers(user_id: str = "test-pa-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
