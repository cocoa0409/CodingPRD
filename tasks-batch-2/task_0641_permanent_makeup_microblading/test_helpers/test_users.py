"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque or, for Technician, entity_backed. Per PRD §2.1, the
Technician role's X-User-ID is the id of the acting Technician entity; ownership
checks compare a resource's technician foreign key to X-User-ID. The
make_technician_headers builder threads the real Technician.id when a call is
ownership-gated. StudioAdmin, FrontDesk, and ComplianceOfficer use opaque
identifiers the server records but never compares to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles use these as their canonical form; the
# entity-backed Technician constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "studio_admin_headers": build_user_headers("test-studio-admin-1", "StudioAdmin"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-1", "ComplianceOfficer"
    ),
}


def make_technician_headers(technician_id: str) -> dict:
    """For the Technician role (entity_backed:Technician). Pass the actual
    Technician.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(technician_id, "Technician")


def make_studio_admin_headers(user_id: str = "test-studio-admin-1") -> dict:
    return build_user_headers(user_id, "StudioAdmin")


def make_front_desk_headers(user_id: str = "test-front-desk-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_compliance_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
