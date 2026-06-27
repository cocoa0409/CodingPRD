"""Pre-built role headers for every role in the Mold Remediation PRD (§2.1).

All five roles are opaque (X-User-ID is not tied to any persisted entity and is
never compared to an entity id); shared constants are the canonical form for
every role. There are no entity_backed roles, so no per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "abatement_supervisor_headers": build_user_headers("test-as-1", "AbatementSupervisor"),
    "lab_tech_headers": build_user_headers("test-lt-1", "LabTech"),
    "hygienist_headers": build_user_headers("test-hyg-1", "Hygienist"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
}
