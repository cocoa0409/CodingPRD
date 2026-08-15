"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity-backed ownership (400/404/role-denial paths).
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "property_manager_headers": build_user_headers("test-manager-1", "PropertyManager"),
    "billing_clerk_headers": build_user_headers("clerk-1", "BillingClerk"),
    "compliance_officer_headers": build_user_headers("officer-9", "ComplianceOfficer"),
    # Entity-backed fallbacks for non-ownership tests only.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
}


def make_technician_headers(user_id: str) -> dict:
    """Technician is entity-backed: pass the actual Technician.id as user_id
    whenever the call is assignment-gated (complete / no-access)."""
    return build_user_headers(user_id, "Technician")


def make_resident_headers(user_id: str) -> dict:
    """Resident is entity-backed: pass the actual Resident.id as user_id
    whenever the call is ownership-gated (acknowledge-prep / dispute / reads)."""
    return build_user_headers(user_id, "Resident")


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_property_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_billing_clerk_headers(user_id: str = "clerk-1") -> dict:
    """BillingClerk is opaque; the X-User-ID is recorded as assessed_by."""
    return build_user_headers(user_id, "BillingClerk")


def make_compliance_officer_headers(user_id: str = "officer-9") -> dict:
    """ComplianceOfficer is opaque; the X-User-ID is recorded as resolved_by."""
    return build_user_headers(user_id, "ComplianceOfficer")
