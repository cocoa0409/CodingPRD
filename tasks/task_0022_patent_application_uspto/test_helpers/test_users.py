"""Pre-built role headers per PRD §2.1.

PRD §2.1: When X-User-Role is `Applicant`, X-User-ID is the id of the acting
Applicant entity, and ownership checks compare the resource's foreign-key
field to X-User-ID. USPTOExaminer and USPTOAdmin are opaque operator
identifiers — they may use the shared constant for every call.

For Applicant calls, USE the make_applicant_headers(applicant_id) builder
with the actual Applicant.id; falling back to the shared constant produces
an X-User-ID that does not resolve to any real applicant, which PRD §2.1
treats as ERR_UNAUTHENTICATED (401) for Applicant-role requests.
"""
from prd_bench_local_runner.testing import build_user_headers


# ─── Shared constants ──────────────────────────────────────────────────

TEST_USERS = {
    # Opaque operator roles — shared constant is canonical (PRD §2.1).
    "examiner_headers": build_user_headers("examiner-001", "USPTOExaminer"),
    "admin_headers": build_user_headers("admin-001", "USPTOAdmin"),
    # entity_backed role — fallback ONLY for non-ownership tests where the
    # call must fail anyway (e.g. RBAC denial as the wrong role).
    "applicant_headers": build_user_headers("applicant-fallback", "Applicant"),
}


# ─── Per-instance builder for the entity_backed role ──────────────────

def make_applicant_headers(applicant_id: str) -> dict:
    """For role=Applicant (entity_backed:Applicant per PRD §2.1).
    Pass the actual Applicant.id as X-User-ID for ownership-gated calls."""
    return build_user_headers(applicant_id, "Applicant")
