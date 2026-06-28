"""Pre-built role headers for every role in the PRD.

All three roles (Underwriter, SeniorUnderwriter, ClaimsExaminer) are opaque operator
identities (PRD §2.1): the server never compares X-User-ID to any persisted entity's id,
and authorization is governed entirely by X-User-Role. There are no entity_backed roles, so
the shared constants below are the canonical headers for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "senior_underwriter_headers": build_user_headers("test-senior-1", "SeniorUnderwriter"),
    "claims_examiner_headers": build_user_headers("test-examiner-1", "ClaimsExaminer"),
}


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_senior_underwriter_headers(user_id: str = "test-senior-1") -> dict:
    return build_user_headers(user_id, "SeniorUnderwriter")


def make_claims_examiner_headers(user_id: str = "test-examiner-1") -> dict:
    return build_user_headers(user_id, "ClaimsExaminer")
