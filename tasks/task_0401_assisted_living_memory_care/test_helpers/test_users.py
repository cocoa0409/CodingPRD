"""Pre-built role headers for every role in the PRD.

All six roles use an opaque identity model: X-User-ID is an opaque operator
identifier that is never compared to any persisted entity's id. Shared constants
are therefore the canonical form for every role; no entity-backed per-instance
builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "clinical_director_headers": build_user_headers("test-clinical-director-1", "ClinicalDirector"),
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "staff_headers": build_user_headers("test-staff-1", "Staff"),
}
