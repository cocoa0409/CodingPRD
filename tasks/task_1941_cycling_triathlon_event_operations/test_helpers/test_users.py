"""Pre-built role headers for every role in the PRD.

Five roles (RaceDirector, PermitCoordinator, Referee, Timer,
VolunteerCoordinator) use opaque operator ids. The Athlete role is
entity-backed: X-User-ID must be the acting Athlete's id, so ownership-gated
calls MUST use make_athlete_headers(athlete["id"]) with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# Athlete ownership (bad-payload 400s, 404s, reads by any role).
TEST_USERS = {
    "race_director_headers": build_user_headers("test-rd-1", "RaceDirector"),
    "permit_coordinator_headers": build_user_headers("test-pc-1", "PermitCoordinator"),
    "referee_headers": build_user_headers("test-ref-1", "Referee"),
    "timer_headers": build_user_headers("test-timer-1", "Timer"),
    "volunteer_coordinator_headers": build_user_headers("test-vc-1", "VolunteerCoordinator"),
    # Fallback only for non-ownership paths; never use for a call gated on the
    # registration's athlete_id.
    "athlete_headers": build_user_headers("test-athlete-1", "Athlete"),
}


def make_race_director_headers(user_id: str = "test-rd-1") -> dict:
    return build_user_headers(user_id, "RaceDirector")


def make_permit_coordinator_headers(user_id: str = "test-pc-1") -> dict:
    return build_user_headers(user_id, "PermitCoordinator")


def make_referee_headers(user_id: str) -> dict:
    """Referee ids matter: penalty assessment stamps assessed_by_user_id and
    appeal decisions compare decided_by_user_id against it (segregation of
    duties), so callers choose the referee id deliberately."""
    return build_user_headers(user_id, "Referee")


def make_timer_headers(user_id: str = "test-timer-1") -> dict:
    return build_user_headers(user_id, "Timer")


def make_volunteer_coordinator_headers(user_id: str = "test-vc-1") -> dict:
    return build_user_headers(user_id, "VolunteerCoordinator")


def make_athlete_headers(user_id: str) -> dict:
    """For the Athlete role (entity-backed by Athlete). Pass the actual
    Athlete.id as user_id whenever the call is ownership-gated (register self,
    pay, withdraw, check-in/out, file appeal)."""
    return build_user_headers(user_id, "Athlete")
