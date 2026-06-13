"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are opaque operator identities (JuryAdministrator, CourtClerk,
Judge) — X-User-ID is never compared to an entity id. One role is entity-backed
(Juror -> Juror.id): a juror submitting a questionnaire or requesting a
disposition must own the summons, so X-User-ID must equal Summons.juror_id.
For those ownership-gated calls, use make_juror_headers(juror_id) with the real
Juror.id rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that do not exercise
# resource ownership (e.g. 401/403/404 paths, or opaque-role calls).
TEST_USERS = {
    "jury_administrator_headers": build_user_headers("test-jury-admin-1", "JuryAdministrator"),
    "court_clerk_headers": build_user_headers("test-court-clerk-1", "CourtClerk"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
    # entity_backed fallback — only valid where ownership is NOT asserted.
    "juror_headers": build_user_headers("test-juror-1", "Juror"),
}


# Per-instance builder — required for the entity_backed Juror role. Pass the
# actual Juror.id so ownership-gated calls authenticate as the owning juror.
def make_juror_headers(juror_id: str) -> dict:
    """For Juror (entity_backed:Juror). Pass the acting Juror.id as X-User-ID."""
    return build_user_headers(juror_id, "Juror")
