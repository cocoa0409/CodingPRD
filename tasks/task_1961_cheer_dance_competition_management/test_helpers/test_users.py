"""Pre-built role headers for every role in the PRD.

Judge, HeadJudge, and SafetyJudge are entity-backed by Judge: their
X-User-ID is the acting Judge entity's id, and ownership/authorship checks
(score-sheet judge_id, deduction applied_by_judge_id, appeal
decided_by_judge_id) compare against it. Those calls MUST use the per-instance
builders with the real Judge.id. TeamCoach and Spectator are opaque but
ownership-gated via Team.coach_user_id / TicketOrder.purchaser_user_id, so the
same coach/spectator id string must be threaded consistently. EventDirector,
MusicCompliance, and EligibilityOfficer are fully opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "event_director_headers": build_user_headers("test-director-1", "EventDirector"),
    "team_coach_headers": build_user_headers("coach-1", "TeamCoach"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
    "head_judge_headers": build_user_headers("test-head-judge-1", "HeadJudge"),
    "safety_judge_headers": build_user_headers("test-safety-judge-1", "SafetyJudge"),
    "music_compliance_headers": build_user_headers("test-music-1", "MusicCompliance"),
    "eligibility_officer_headers": build_user_headers("test-eligibility-1",
                                                      "EligibilityOfficer"),
    "spectator_headers": build_user_headers("spec-1", "Spectator"),
}


def make_event_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "EventDirector")


def make_team_coach_headers(user_id: str) -> dict:
    """For TeamCoach (opaque, ownership via Team.coach_user_id). Pass the same
    coach id used at team registration for every ownership-gated call."""
    return build_user_headers(user_id, "TeamCoach")


def make_judge_headers(judge_id: str) -> dict:
    """For Judge (entity_backed:Judge). Pass the acting Judge.id whenever the
    call is authorship-gated (score-sheet create/PATCH/submit)."""
    return build_user_headers(judge_id, "Judge")


def make_head_judge_headers(judge_id: str) -> dict:
    """For HeadJudge (entity_backed:Judge). Pass the acting Judge.id whenever
    the call is segregation-gated (appeal resolve, deduction void)."""
    return build_user_headers(judge_id, "HeadJudge")


def make_safety_judge_headers(judge_id: str) -> dict:
    """For SafetyJudge (entity_backed:Judge). Pass the acting Judge.id whenever
    the call records applied_by_judge_id (mark-performed, deduction create)."""
    return build_user_headers(judge_id, "SafetyJudge")


def make_music_compliance_headers(user_id: str = "test-music-1") -> dict:
    return build_user_headers(user_id, "MusicCompliance")


def make_eligibility_officer_headers(user_id: str = "test-eligibility-1") -> dict:
    return build_user_headers(user_id, "EligibilityOfficer")


def make_spectator_headers(user_id: str) -> dict:
    """For Spectator (opaque, ownership via TicketOrder.purchaser_user_id).
    Pass the same spectator id used at order creation for pay/cancel."""
    return build_user_headers(user_id, "Spectator")
