"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are operational/opaque identities — X-User-ID is never compared
to any persisted entity id (PRD §2.1), so the shared-constant form is canonical
for every role and no per-instance entity-backed builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "arena_manager_headers": build_user_headers("test-arena-manager-1", "ArenaManager"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    "field_marshal_headers": build_user_headers("test-field-marshal-1", "FieldMarshal"),
    "league_director_headers": build_user_headers("test-league-director-1", "LeagueDirector"),
}
