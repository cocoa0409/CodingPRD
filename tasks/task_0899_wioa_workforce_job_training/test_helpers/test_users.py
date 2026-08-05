"""Pre-built role headers for every role in the WIOA PRD.

All four roles have an opaque identity: the X-User-ID is never compared to any
persisted entity's id (PRD §2.1), so shared constants are the canonical form for
every role and no per-instance ownership builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "state_admin_headers": build_user_headers("test-state-admin-1", "StateAdmin"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "fiscal_officer_headers": build_user_headers("test-fiscal-officer-1", "FiscalOfficer"),
    "business_rep_headers": build_user_headers("test-business-rep-1", "BusinessServicesRep"),
    # Read pseudo-role "Any": any authenticated real role may read. Use a real role.
    "any_headers": build_user_headers("test-reader-1", "CaseManager"),
}
