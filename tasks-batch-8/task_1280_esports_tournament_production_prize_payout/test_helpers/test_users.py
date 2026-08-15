"""Pre-built role headers for every role in the PRD (§2.1).

Seven roles are opaque operator identities; shared constants are canonical for
them. Two roles are entity-backed: TeamManager (X-User-ID is the acting
Registration's id) and Player (X-User-ID is the acting Player's id). For
entity-backed roles, fixtures and tests MUST call the per-instance builder
with the real entity id whenever the call is ownership-gated — the shared
constant exists only for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "organizer_admin_headers": build_user_headers("oa-shared-1",
                                                  "OrganizerAdmin"),
    "tournament_director_headers": build_user_headers("td-shared-1",
                                                      "TournamentDirector"),
    "referee_headers": build_user_headers("ref-shared-1", "Referee"),
    "anti_cheat_investigator_headers": build_user_headers(
        "ac-shared-1", "AntiCheatInvestigator"),
    "broadcast_producer_headers": build_user_headers("bp-shared-1",
                                                     "BroadcastProducer"),
    "payout_officer_headers": build_user_headers("po-shared-1",
                                                 "PayoutOfficer"),
    "sponsor_manager_headers": build_user_headers("sm-shared-1",
                                                  "SponsorManager"),
    # Entity-backed roles: fallback constants for non-ownership tests only.
    "team_manager_headers": build_user_headers("tm-shared-1", "TeamManager"),
    "player_headers": build_user_headers("pl-shared-1", "Player"),
}


def make_organizer_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OrganizerAdmin")


def make_tournament_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TournamentDirector")


def make_team_manager_headers(user_id: str) -> dict:
    """TeamManager is entity-backed: pass the acting Registration's id."""
    return build_user_headers(user_id, "TeamManager")


def make_player_headers(user_id: str) -> dict:
    """Player is entity-backed: pass the acting Player's id."""
    return build_user_headers(user_id, "Player")


def make_referee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Referee")


def make_anti_cheat_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AntiCheatInvestigator")


def make_broadcast_producer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BroadcastProducer")


def make_payout_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PayoutOfficer")


def make_sponsor_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SponsorManager")
