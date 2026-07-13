"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ProgramAdmin, Registrar), and for
# tests that don't exercise entity ownership. For Artist/Panelist these are only
# a fallback for non-ownership scenarios; ownership-gated calls MUST use the
# per-instance builders below with the real entity id.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "artist_headers": build_user_headers("test-artist-1", "Artist"),
    "panelist_headers": build_user_headers("test-panelist-1", "Panelist"),
}


def make_artist_headers(user_id: str) -> dict:
    """For Artist (entity_backed:Artist). Pass the actual Artist.id as user_id
    whenever the call is ownership-gated (submit/resubmit/milestone-submit)."""
    return build_user_headers(user_id, "Artist")


def make_panelist_headers(user_id: str) -> dict:
    """For Panelist (entity_backed:Panelist). Pass the actual Panelist.id as
    user_id whenever the call is ownership-gated (scoring)."""
    return build_user_headers(user_id, "Panelist")
