"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers (PRD §2.1: the X-User-ID value
"is an opaque operator identifier that is not tied to any persisted entity"),
so shared constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_operator_headers": build_user_headers("op-1", "PlantOperator"),
    "lab_technician_headers": build_user_headers("lab-1", "LabTechnician"),
    "quality_manager_headers": build_user_headers("qm-1", "QualityManager"),
    "inspector_headers": build_user_headers("insp-1", "QualityAgencyInspector"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "accounts_receivable_headers": build_user_headers("ar-1", "AccountsReceivable"),
}
