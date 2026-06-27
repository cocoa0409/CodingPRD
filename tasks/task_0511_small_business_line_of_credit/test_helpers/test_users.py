"""Pre-built role headers for every role in the PRD (§2.1).

All three roles (Underwriter, Servicer, CreditOfficer) use an opaque X-User-ID: the server
never compares it to any persisted entity's id, and authorization is governed by X-User-Role
(PRD §2.1). The shared constants below are therefore the canonical headers for role-gated
behaviour.

The server DOES, however, *record* specific X-User-ID values as audit anchors —
submitted_by_user_id on an Application and defaulted_by_user_id on a CreditLine — and the
segregation-of-duties checks compare the acting X-User-ID against those recorded values
(PRD §2.1, §3.2, §3.6). Tests that exercise segregation of duties must therefore control the
exact X-User-ID per call, so per-role builder functions are provided.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "underwriter_headers": build_user_headers("uw_1", "Underwriter"),
    "underwriter2_headers": build_user_headers("uw_2", "Underwriter"),
    "servicer_headers": build_user_headers("sv_1", "Servicer"),
    "credit_officer_headers": build_user_headers("co_1", "CreditOfficer"),
    "credit_officer2_headers": build_user_headers("co_2", "CreditOfficer"),
}


def make_underwriter_headers(user_id: str) -> dict:
    """Underwriter headers with an explicit X-User-ID (segregation-of-duties anchor)."""
    return build_user_headers(user_id, "Underwriter")


def make_servicer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Servicer")


def make_credit_officer_headers(user_id: str) -> dict:
    """CreditOfficer headers with an explicit X-User-ID (default/charge-off SoD anchor)."""
    return build_user_headers(user_id, "CreditOfficer")
