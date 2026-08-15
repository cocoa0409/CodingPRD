"""Pre-built role headers for every role in the PRD.

PRD §2.1: for all four roles, `X-User-ID` is an opaque operator identifier
never compared to any entity's `id` — "none of the four roles is
entity-backed". Shared constants are therefore the canonical form; the
make_*_headers builders exist so segregation-of-duties tests can pin a
specific `X-User-ID` per call (PRD §2.9).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "director_headers": build_user_headers("director-1", "FederalProgramsDirector"),
    "analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "monitor_headers": build_user_headers("monitor-1", "SEAMonitor"),
    "ombudsman_headers": build_user_headers("omb-1", "PrivateSchoolOmbudsman"),
}


def make_director_headers(user_id: str) -> dict:
    """FederalProgramsDirector headers for a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "FederalProgramsDirector")


def make_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst headers for a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_monitor_headers(user_id: str) -> dict:
    """SEAMonitor headers for a specific operator id (SoD tests)."""
    return build_user_headers(user_id, "SEAMonitor")


def make_ombudsman_headers(user_id: str) -> dict:
    """PrivateSchoolOmbudsman headers for a specific operator id."""
    return build_user_headers(user_id, "PrivateSchoolOmbudsman")
