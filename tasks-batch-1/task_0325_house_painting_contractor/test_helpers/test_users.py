"""Pre-built role headers for every role in the PRD.

All four roles (Estimator, ProjectManager, Customer, CrewMember) carry an OPAQUE
identity (PRD §2.1): X-User-ID is an opaque operator identifier, never compared
to any entity's id. There is no entity-backed ownership check, so the shared
constants below are the canonical form for every test — no per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "crew_member_headers": build_user_headers("test-crew-1", "CrewMember"),
}
