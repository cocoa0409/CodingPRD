"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "security_admin_headers": build_user_headers("test-security-admin-1", "SecurityAdmin"),
    "security_officer_headers": build_user_headers("test-security-officer-1", "SecurityOfficer"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


# Per-instance builders — required for entity_backed roles (Resident/Vendor).
def make_resident_headers(user_id: str) -> dict:
    """For Resident (entity_backed: Person). Pass the actual Person.id as user_id
    whenever the call is ownership-gated (own record read, own credential list,
    own charge payment, own report-lost)."""
    return build_user_headers(user_id, "Resident")


def make_vendor_headers(user_id: str) -> dict:
    """For Vendor (entity_backed: Person). Pass the actual Person.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Vendor")
