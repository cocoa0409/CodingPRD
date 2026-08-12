"""Pre-built role headers for every role in the PRD.

All five roles use an opaque identity model (PRD §2.1): X-User-ID is an opaque
operator identifier, never a foreign key into any persisted entity table.
Segregation-of-duties checks compare X-User-ID values against operator-id
fields, so the shared constants below use distinct ids per role and are safe
for every call in the suite.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_controller_headers": build_user_headers("pc-001", "PlantController"),
    "qa_manager_headers": build_user_headers("qam-001", "QualityAssuranceManager"),
    "lab_technician_headers": build_user_headers("lab-001", "LabTechnician"),
    "pasteurizer_operator_headers": build_user_headers("pop-001", "PasteurizerOperator"),
    "state_inspector_headers": build_user_headers("si-001", "StateInspector"),
}
