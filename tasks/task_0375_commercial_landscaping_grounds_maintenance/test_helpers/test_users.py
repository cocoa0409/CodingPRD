"""Pre-built role headers for every role in the PRD (§2.1).

All four roles carry an OPAQUE identity (PRD §2.1): the X-User-ID is an opaque
operator identifier that is never compared to any persisted entity id, and
ownership is never decided by matching it to a stored foreign key. So a single
shared header per role is the canonical form for every test.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "crew_lead_headers": build_user_headers("test-crew-lead-1", "CrewLead"),
    "quality_inspector_headers": build_user_headers("test-quality-inspector-1", "QualityInspector"),
    "dispatch_operator_headers": build_user_headers("test-dispatch-operator-1", "DispatchOperator"),
}

# An unrecognized role value, for the auth-header rejection test (PRD §2.1).
UNKNOWN_ROLE_HEADERS = build_user_headers("test-intruder-1", "Intruder")
