"""Pre-built role headers for the four PRD roles (PRD §2.1).

TournamentDirector and TabStaff are opaque identities — the shared constants are
canonical. SchoolCoach and Judge are entity-backed: any ownership-gated call must
use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "director_headers": build_user_headers("test-director-1", "TournamentDirector"),
    "tabstaff_headers": build_user_headers("test-tabstaff-1", "TabStaff"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests.
    "coach_headers": build_user_headers("test-coach-1", "SchoolCoach"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
}


def make_coach_headers(school_id: str) -> dict:
    """SchoolCoach is entity-backed by School: pass the acting school's id
    whenever the call is ownership-gated (entries, judges, contracts, confirms)."""
    return build_user_headers(school_id, "SchoolCoach")


def make_judge_headers(judge_id: str) -> dict:
    """Judge is entity-backed by Judge: pass the acting judge's id whenever the
    call is ownership-gated (ballot create/submit/recall)."""
    return build_user_headers(judge_id, "Judge")
