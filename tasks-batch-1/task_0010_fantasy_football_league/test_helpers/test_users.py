"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, the TeamOwner role is entity-backed: X-User-ID must equal the
acting Team's id. Ownership-gated calls MUST use make_team_owner_headers
(team_id) — never the shared constant — or the server will reject the call
with ERR_FORBIDDEN because the shared id is not any real team's id.

The Commissioner role carries identity: opaque. PRD §2.1 explicitly says
'X-User-ID is an opaque operator identifier not tied to any persisted entity;
the server may record it for audit but does not compare it to any entity's id',
so a shared Commissioner constant is canonical for that role.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque role: shared constant is canonical.
    "commissioner_headers": build_user_headers("test-commissioner-1", "Commissioner"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "team_owner_headers": build_user_headers("test-team-owner-1", "TeamOwner"),
}


def make_commissioner_headers(opaque_id: str = "test-commissioner-1") -> dict:
    """For Commissioner (identity: opaque). X-User-ID is recorded but not
    compared to any entity per PRD §2.1.
    """
    return build_user_headers(opaque_id, "Commissioner")


def make_team_owner_headers(team_id: str) -> dict:
    """For TeamOwner (entity_backed:Team). Pass the actual Team.id as user_id
    whenever the call is ownership-gated (team-scoped roster mutations,
    waiver-claims, trade actions, veto-votes), per PRD §2.1.
    """
    return build_user_headers(team_id, "TeamOwner")
