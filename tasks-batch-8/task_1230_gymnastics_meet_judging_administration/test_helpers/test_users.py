"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership-gated calls. For entity-backed roles (JudgePanelChief -> Judge.id,
# Coach -> Coach.id) prefer the per-instance builders below whenever the call
# is ownership- or assignment-gated.
TEST_USERS = {
    "meet_director_headers": build_user_headers("test-meet-director-1", "MeetDirector"),
    "meet_referee_headers": build_user_headers("test-meet-referee-1", "MeetReferee"),
    "judge_panel_chief_headers": build_user_headers("test-panel-chief-1", "JudgePanelChief"),
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
    "gate_attendant_headers": build_user_headers("test-gate-attendant-1", "GateAttendant"),
    "spectator_headers": build_user_headers("test-spectator-1", "Spectator"),
}


def make_coach_headers(user_id: str) -> dict:
    """For Coach (entity-backed: Coach). Pass the actual Coach.id as user_id
    whenever the call binds the action to that coach (check-in, inquiry filing
    and withdrawal, qualification decline)."""
    return build_user_headers(user_id, "Coach")


def make_judge_panel_chief_headers(user_id: str) -> dict:
    """For JudgePanelChief (entity-backed: Judge). Pass the actual Judge.id of
    the confirmed panel chief as user_id whenever publishing or amending scores."""
    return build_user_headers(user_id, "JudgePanelChief")
