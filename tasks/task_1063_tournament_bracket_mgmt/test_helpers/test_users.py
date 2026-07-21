"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Director/Referee/Public) and for
# tests that do not exercise Player ownership.
TEST_USERS = {
    "director_headers": build_user_headers("dir-1", "Director"),
    "referee_headers": build_user_headers("ref-1", "Referee"),
    "public_headers": build_user_headers("public-1", "Public"),
    # Fallback only — never use for an ownership-gated Player call.
    "player_headers": build_user_headers("player-fallback", "Player"),
}


def make_director_headers(user_id="dir-1") -> dict:
    return build_user_headers(user_id, "Director")


def make_referee_headers(user_id="ref-1") -> dict:
    """Referee identity is opaque; user_id distinguishes actors for SoD checks."""
    return build_user_headers(user_id, "Referee")


def make_player_headers(user_id) -> dict:
    """For Player (entity_backed:Player). Pass the actual Player.id as user_id
    whenever the call is ownership-gated (registration/check-in/withdraw/report/dispute)."""
    return build_user_headers(user_id, "Player")


def make_public_headers(user_id="public-1") -> dict:
    return build_user_headers(user_id, "Public")
