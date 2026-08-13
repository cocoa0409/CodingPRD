"""Pre-built role headers for every role in the PRD.

Only `Student` is entity-backed: when the caller role is `Student`,
`X-User-ID` must be the `id` of the acting student record, because ownership
checks compare a resource's `student_id` against `X-User-ID`. Ownership-gated
calls MUST use `make_student_headers(student["id"])`. The other five roles are
opaque operator identities; the shared constants are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "registrar_headers": build_user_headers("registrar-001", "Registrar"),
    "aid_officer_headers": build_user_headers("aid-officer-001", "AidOfficer"),
    "committee_headers": build_user_headers("committee-001", "CommitteeMember"),
    "auditor_headers": build_user_headers("auditor-001", "Auditor"),
    "aid_admin_headers": build_user_headers("aid-admin-001", "AidAdministrator"),
    # Entity-backed role — fallback for non-ownership probes only (for example
    # authentication or role-gate tests that never reach an ownership check).
    "student_headers": build_user_headers("student-001", "Student"),
}

REGISTRAR = TEST_USERS["registrar_headers"]
AID_OFFICER = TEST_USERS["aid_officer_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
AID_ADMIN = TEST_USERS["aid_admin_headers"]

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_student_headers(student_id: str) -> dict:
    """Headers for the Student role acting as the student row `student_id`.

    Mandatory whenever the call is ownership-gated (own record read, advising
    preview, appeal submission, appeal resubmission, student-scoped lists).
    """
    return build_user_headers(student_id, "Student")
