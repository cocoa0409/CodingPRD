"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers: the server never compares
X-User-ID against any resource's id (PRD §2.1), so shared constants are the
canonical form for every role. Two distinct ProductActuary identities exist
because indication approval enforces segregation of duties (PRD §3.2).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "actuary_headers": build_user_headers("act-1", "ProductActuary"),
    "actuary2_headers": build_user_headers("act-2", "ProductActuary"),
    "analyst_headers": build_user_headers("analyst-1", "FilingAnalyst"),
    "officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "regulator_headers": build_user_headers("reg-1", "StateRegulator"),
    "lead_headers": build_user_headers("lead-1", "ImplementationLead"),
}
