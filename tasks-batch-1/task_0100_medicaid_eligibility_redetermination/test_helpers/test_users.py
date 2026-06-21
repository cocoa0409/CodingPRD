"""Pre-built role headers for every role in the PRD.

All three roles (Applicant, CaseWorker, HearingOfficer) carry an OPAQUE
identity — X-User-ID is never compared to any entity's id. So the shared
constants below are the canonical form for ordinary calls.

The only place identity matters is segregation of duties: the HearingOfficer
who hears an appeal must differ from the assigned_caseworker_id pinned when the
CaseWorker claimed the application. The per-id builders let a test pin or
distinguish those operator identities explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles.
TEST_USERS = {
    "applicant_headers": build_user_headers("applicant-1", "Applicant"),
    "caseworker_headers": build_user_headers("caseworker-1", "CaseWorker"),
    "hearing_officer_headers": build_user_headers("hearing-officer-1", "HearingOfficer"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Applicant headers with an explicit opaque operator id."""
    return build_user_headers(user_id, "Applicant")


def make_caseworker_headers(user_id: str) -> dict:
    """CaseWorker headers with an explicit opaque operator id.

    Use to pin the assigned_caseworker_id (e.g. when a later segregation-of-duties
    check must observe a specific caseworker identity)."""
    return build_user_headers(user_id, "CaseWorker")


def make_hearing_officer_headers(user_id: str) -> dict:
    """HearingOfficer headers with an explicit opaque operator id.

    Pass an id that differs from (or deliberately equals) the claiming
    CaseWorker's id to exercise the segregation-of-duties rule."""
    return build_user_headers(user_id, "HearingOfficer")
