"""Pre-built role headers for every role in the PRD.

Applicant and Attorney are entity-backed: ownership checks compare X-User-ID
against the resource's applicant_id / attorney_id. Tests that exercise an
ownership-gated mutation MUST use the per-instance builder threading the real
entity id. The shared TEST_USERS constants are safe only for the opaque office
roles (Examiner, TTABClerk) and for non-ownership tests (bad payload, 404,
401/403 role checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque office operators — shared constant is the canonical form.
    "examiner_headers": build_user_headers("examiner-op-1", "Examiner"),
    "ttab_clerk_headers": build_user_headers("ttab-clerk-op-1", "TTABClerk"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests
    # only (e.g., role-permission 403 checks where ownership never resolves).
    "applicant_headers": build_user_headers("applicant-fallback-1", "Applicant"),
    "attorney_headers": build_user_headers("attorney-fallback-1", "Attorney"),
}


def make_applicant_headers(applicant_id: str) -> dict:
    """For an Applicant acting on its own resource. Pass the actual Applicant.id."""
    return build_user_headers(applicant_id, "Applicant")


def make_attorney_headers(attorney_id: str) -> dict:
    """For an Attorney acting as attorney of record. Pass the actual Attorney.id."""
    return build_user_headers(attorney_id, "Attorney")


def examiner_headers() -> dict:
    return TEST_USERS["examiner_headers"]


def ttab_clerk_headers() -> dict:
    return TEST_USERS["ttab_clerk_headers"]
