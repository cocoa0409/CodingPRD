"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use an OPAQUE X-User-ID that the server records for audit but
never compares against any entity's id; authorization is decided purely by the
role appearing in the operation's authorized set. Shared constants are therefore
the canonical form for every role — there are no ownership-gated, entity-backed
roles in this system.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admissions_officer_headers": build_user_headers("test-admissions-1", "AdmissionsOfficer"),
    "servicing_officer_headers": build_user_headers("test-servicing-1", "ServicingOfficer"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}

# An unrecognized role for ERR_UNAUTHENTICATED probes (PRD §2.1).
UNRECOGNIZED_ROLE_HEADERS = build_user_headers("test-nobody-1", "Nobody")
