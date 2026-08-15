"""Pre-built role headers for every role in the PRD (§2.1).

TeamCoach is entity-backed by Team, DeckOfficial and MeetReferee are
entity-backed by Official: for ownership-gated calls the caller's X-User-ID
must equal the real entity id, so use the per-instance builders below.
MeetDirector, TimingOperator and RecordsOfficer are opaque operators and may
always use the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (bad-payload 400s, not-found 404s, reads open to Any).
TEST_USERS = {
    "meet_director_headers": build_user_headers("test-meet-director-1", "MeetDirector"),
    "team_coach_headers": build_user_headers("test-team-coach-1", "TeamCoach"),
    "timing_operator_headers": build_user_headers("test-timing-operator-1", "TimingOperator"),
    "deck_official_headers": build_user_headers("test-deck-official-1", "DeckOfficial"),
    "meet_referee_headers": build_user_headers("test-meet-referee-1", "MeetReferee"),
    "records_officer_headers": build_user_headers("test-records-officer-1", "RecordsOfficer"),
}


def make_meet_director_headers(user_id: str = "test-meet-director-1") -> dict:
    return build_user_headers(user_id, "MeetDirector")


def make_team_coach_headers(user_id: str) -> dict:
    """TeamCoach is entity_backed:Team — pass the acting Team.id."""
    return build_user_headers(user_id, "TeamCoach")


def make_timing_operator_headers(user_id: str = "test-timing-operator-1") -> dict:
    return build_user_headers(user_id, "TimingOperator")


def make_deck_official_headers(user_id: str) -> dict:
    """DeckOfficial is entity_backed:Official — pass the acting Official.id."""
    return build_user_headers(user_id, "DeckOfficial")


def make_meet_referee_headers(user_id: str) -> dict:
    """MeetReferee is entity_backed:Official — pass the acting Official.id."""
    return build_user_headers(user_id, "MeetReferee")


def make_records_officer_headers(user_id: str = "test-records-officer-1") -> dict:
    return build_user_headers(user_id, "RecordsOfficer")
