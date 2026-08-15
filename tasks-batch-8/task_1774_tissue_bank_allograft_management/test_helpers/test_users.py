"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers: the server never compares
X-User-ID against a resource's `id` (PRD §2.1), so shared constants are the
canonical form. Second-user variants exist for segregation-of-duties and
case-ownership scenarios.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "coordinator_headers": build_user_headers("tbc-1", "TissueBankCoordinator"),
    "coordinator2_headers": build_user_headers("tbc-2", "TissueBankCoordinator"),
    "quality_headers": build_user_headers("qm-1", "QualityManager"),
    "quality2_headers": build_user_headers("qm-2", "QualityManager"),
    "compliance_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "surgeon_headers": build_user_headers("surg-1", "ImplantingSurgeon"),
    "surgeon2_headers": build_user_headers("surg-2", "ImplantingSurgeon"),
    "admin_headers": build_user_headers("sca-1", "SupplyChainAdmin"),
}
