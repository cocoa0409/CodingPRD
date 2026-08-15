"""Pre-built role headers for every role in the PRD (section 2.1).

When X-User-Role is Driver, X-User-ID is the id of the acting Driver resource;
for the other three roles it is an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for Driver calls whose
# success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "league_admin_headers": build_user_headers("admin-1", "LeagueAdmin"),
    "race_director_headers": build_user_headers("rd-1", "RaceDirector"),
    "race_director_2_headers": build_user_headers("rd-2", "RaceDirector"),
    "steward_headers": build_user_headers("st-1", "Steward"),
    "steward_2_headers": build_user_headers("st-2", "Steward"),
    "steward_9_headers": build_user_headers("st-9", "Steward"),
    # Driver is entity-backed: this shared constant is a fallback for
    # non-ownership tests only (bad payloads, role probes).
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """Driver role is entity-backed (identity = the Driver resource id). Pass
    the actual Driver.id whenever the call is ownership-gated: paying or
    withdrawing an entry, booking practice time, check-in/check-out/cancel of
    a booking, and appealing an incident."""
    return build_user_headers(user_id, "Driver")
