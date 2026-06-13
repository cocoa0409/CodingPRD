"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use an opaque identity model: X-User-ID is an opaque operator
identifier never matched against any stored entity id (PRD §2.1). Shared
constants are therefore the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "clinic_admin_headers": build_user_headers("admin-1", "ClinicAdmin"),
    "front_desk_headers": build_user_headers("frontdesk-1", "FrontDeskStaff"),
    "patient_headers": build_user_headers("patient-1", "Patient"),
    "billing_clerk_headers": build_user_headers("billing-1", "BillingClerk"),
}
