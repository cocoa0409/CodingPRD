"""Pre-built role headers for every role in the Board Governance PRD.

Two roles are opaque (CorporateSecretary, ExternalAuditor): a shared constant is
canonical. Two roles are entity_backed by Director (Director, BoardChair): the
shared constants below are safe ONLY for tests that never exercise ownership
checks; any ownership-gated call MUST go through the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "secretary_headers": build_user_headers("test-secretary-1", "CorporateSecretary"),
    "auditor_headers": build_user_headers("test-auditor-1", "ExternalAuditor"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "director_headers": build_user_headers("test-director-1", "Director"),
    "chair_headers": build_user_headers("test-chair-1", "BoardChair"),
}


def make_director_headers(director_id: str) -> dict:
    """For Director (entity_backed by Director). Pass the actual Director.id as
    director_id whenever the call is ownership-gated (waive own notice, cast or
    recast a ballot, sign a consent, file own disclosure, resign oneself)."""
    return build_user_headers(director_id, "Director")


def make_chair_headers(director_id: str) -> dict:
    """For BoardChair (entity_backed by Director). Pass the Director.id of the
    meeting's chair_director_id whenever the call is chair-gated (convene,
    adjourn, open/close vote, approve/reject minutes)."""
    return build_user_headers(director_id, "BoardChair")
