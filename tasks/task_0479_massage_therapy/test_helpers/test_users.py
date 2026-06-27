"""Pre-built role headers for every role in the PRD.

PracticeAdmin and FrontDesk identities are opaque operator ids (never matched against an
entity), so their shared constants are the canonical form. Therapist and Client are
entity_backed: ownership-gated calls MUST use the per-instance builder with the real
entity id (see make_therapist_headers / make_client_headers).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "admin_headers": build_user_headers("admin-op-1", "PracticeAdmin"),
    "front_desk_headers": build_user_headers("front-desk-op-1", "FrontDesk"),
    # entity_backed roles — these shared constants are a fallback for NON-ownership tests only
    # (e.g., a therapist acting on a note they do not own to assert ERR_UNAUTHORIZED, where the
    #  mismatch is the point). For ownership-gated success paths use the builders below.
    "therapist_headers": build_user_headers("therapist-fallback-1", "Therapist"),
    "client_headers": build_user_headers("client-fallback-1", "Client"),
}


def make_admin_headers(user_id: str = "admin-op-1") -> dict:
    return build_user_headers(user_id, "PracticeAdmin")


def make_front_desk_headers(user_id: str = "front-desk-op-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_therapist_headers(user_id: str) -> dict:
    """For Therapist (entity_backed:Therapist). Pass the actual Therapist.id whenever the
    call is ownership-gated (SOAP note create/finalize/reopen/edit, complete-by-therapist)."""
    return build_user_headers(user_id, "Therapist")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id whenever the call is
    ownership-gated (sign own intake, revoke own consent, read own records)."""
    return build_user_headers(user_id, "Client")
