"""Pre-built role headers for every role in PRD §2.1.

PDSO and DSO are opaque operator identities (not tied to any persisted
entity). Student is entity-backed: when X-User-Role is Student, X-User-ID
must be the acting Student resource's id for any ownership-gated call.
Use make_student_headers(student["id"]) for those calls; the shared
constant is only a fallback for negative RBAC probes.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical form.
    "pdso_headers": build_user_headers("pdso-1", "PDSO"),
    "dso_headers": build_user_headers("dso-1", "DSO"),
    # entity_backed:Student — fallback for non-ownership probes only.
    "student_headers": build_user_headers("student-orphan-1", "Student"),
}

# Requests carrying no X-User-ID / X-User-Role headers (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_student_headers(student_id: str) -> dict:
    """Student is entity-backed by Student: pass the acting student's id
    whenever the call is ownership-gated (own documents, address reports,
    employment periods, OPT FILE)."""
    return build_user_headers(student_id, "Student")


def make_pdso_headers(user_id: str = "pdso-1") -> dict:
    return build_user_headers(user_id, "PDSO")


def make_dso_headers(user_id: str = "dso-1") -> dict:
    return build_user_headers(user_id, "DSO")
