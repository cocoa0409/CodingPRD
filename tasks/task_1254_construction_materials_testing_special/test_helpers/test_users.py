"""Pre-built role headers for every role in the construction materials testing PRD.

Six roles (AgencyAdmin, ProjectManager, EngineerOfRecord, LabAnalyst, Contractor,
BuildingOfficial) use an opaque operator identifier for X-User-ID; the shared
constants below are their canonical form (PRD §2.1).

Technician is entity-backed: X-User-ID must be the id of the acting Technician
entity, because ownership checks (completing an assignment, recording a field
test or lab sample, filing a daily report, NCR segregation of duties) compare a
resource's technician foreign key against X-User-ID. Any call that is
ownership-gated MUST use make_technician_headers() with the actual
Technician.id — never the shared fallback constant, whose user id matches no
real technician.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "agency_admin_headers": build_user_headers("test-agency-admin-1", "AgencyAdmin"),
    "project_manager_headers": build_user_headers("test-project-manager-1", "ProjectManager"),
    "engineer_of_record_headers": build_user_headers("test-engineer-1", "EngineerOfRecord"),
    "lab_analyst_headers": build_user_headers("test-lab-analyst-1", "LabAnalyst"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
    "building_official_headers": build_user_headers("test-building-official-1", "BuildingOfficial"),
    # Fallback only — valid solely where no ownership check applies.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


def make_technician_headers(technician_id: str) -> dict:
    """Headers for Technician calls. Pass the acting Technician's id so
    ownership checks (resource technician FK == X-User-ID) resolve."""
    return build_user_headers(technician_id, "Technician")
