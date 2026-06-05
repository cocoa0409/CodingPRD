"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are *opaque operator identities* (PRD §2.1): X-User-ID is never
compared to a persisted entity id for ownership. It IS, however, recorded as the
confirming-specialist identity and later compared, as an operator identity,
against the finalizing supervisor for the segregation-of-duties rule (PRD §3.7).

That makes the *user_id* itself load-bearing for some flows:
 - When the SAME operator must both confirm and finalize, use the same user_id.
 - When confirm and finalize must differ, thread DISTINCT user_ids.

Hence both shared constants and per-user builders are provided.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — fine for tests that do not exercise the SoD identity rule.
TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-1", "Coordinator"),
    "background_screener_headers": build_user_headers("screener-1", "BackgroundScreener"),
    "match_specialist_headers": build_user_headers("specialist-1", "MatchSpecialist"),
    "supervisor_headers": build_user_headers("supervisor-1", "Supervisor"),
}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    return build_user_headers(user_id, "Coordinator")


def make_background_screener_headers(user_id: str = "screener-1") -> dict:
    return build_user_headers(user_id, "BackgroundScreener")


def make_match_specialist_headers(user_id: str = "specialist-1") -> dict:
    """For the MatchSpecialist. Pass an explicit user_id when its operator identity
    is recorded as the confirming user (segregation-of-duties, PRD §3.7)."""
    return build_user_headers(user_id, "MatchSpecialist")


def make_supervisor_headers(user_id: str = "supervisor-1") -> dict:
    """For the Supervisor. Pass an explicit user_id when its operator identity is
    compared against the confirming specialist (segregation-of-duties, PRD §3.7)."""
    return build_user_headers(user_id, "Supervisor")


def make_headers(user_id: str, role: str) -> dict:
    """Generic builder: arbitrary operator identity + role string. Used for
    unauthenticated / unrecognized-role probes (e.g. role='Anonymous')."""
    return build_user_headers(user_id, role)
