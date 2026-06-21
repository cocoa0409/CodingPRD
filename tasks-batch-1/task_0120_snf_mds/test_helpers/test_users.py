"""Pre-built role headers for every role in the PRD.

All six roles carry an opaque operator identifier (PRD §2.1): "the accompanying
X-User-ID is an opaque identifier that is not tied to any persisted entity ...
ownership of a resource is never determined by matching X-User-ID to a foreign
key on that resource." So a single shared constant per role is the canonical form;
there are no entity_backed roles requiring per-instance header builders.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "administrator_headers": build_user_headers("test-admin-1", "Administrator"),
    "admissions_coordinator_headers": build_user_headers("test-admissions-1", "AdmissionsCoordinator"),
    "mds_coordinator_headers": build_user_headers("test-mds-1", "MdsCoordinator"),
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "billing_analyst_headers": build_user_headers("test-billing-1", "BillingAnalyst"),
}
