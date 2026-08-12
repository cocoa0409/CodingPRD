"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "intake_specialist_headers": build_user_headers("test-intake-specialist-1", "IntakeSpecialist"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "compliance_officer_alt_headers": build_user_headers("test-compliance-officer-2", "ComplianceOfficer"),
    "lease_manager_headers": build_user_headers("test-lease-manager-1", "LeaseManager"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # Household is entity_backed; the shared constant is a fallback only.
    "household_headers": build_user_headers("test-household-1", "Household"),
}


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_intake_specialist_headers(user_id: str = "test-intake-specialist-1") -> dict:
    return build_user_headers(user_id, "IntakeSpecialist")


def make_compliance_officer_headers(user_id: str = "test-compliance-officer-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_lease_manager_headers(user_id: str = "test-lease-manager-1") -> dict:
    return build_user_headers(user_id, "LeaseManager")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")


def make_household_headers(user_id: str) -> dict:
    """For Household (entity_backed:Household). Pass the actual Household.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Household")
