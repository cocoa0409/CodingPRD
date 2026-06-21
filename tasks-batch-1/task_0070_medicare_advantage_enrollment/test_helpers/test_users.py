"""Pre-built role headers for every role in the PRD.

Both EnrollmentAdmin and ComplianceOfficer are opaque operator identifiers: the
X-User-ID is never compared to any entity id for ownership. So the shared
constants below are the canonical form for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "enrollment_admin_headers": build_user_headers("test-enrollment-admin-1", "EnrollmentAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
}
