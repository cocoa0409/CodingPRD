"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles use shared constants. Entity-backed roles (FILMMAKER, PROGRAMMER,
JUROR) MUST be built per instance with the owning entity's id via the
make_*_headers builders — the shared constant for those roles is only a
fallback for tests that never exercise an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "public_headers": build_user_headers("public-caller-1", "PUBLIC"),
    "admin_headers": build_user_headers("admin-1", "FESTIVAL_ADMIN"),
    "chair_headers": build_user_headers("chair-1", "PROGRAM_CHAIR"),
    "director_headers": build_user_headers("dir-1", "FESTIVAL_DIRECTOR"),
    "ops_headers": build_user_headers("ops-1", "SCHEDULING_OPS"),
    "travel_headers": build_user_headers("travel-1", "TRAVEL_COORDINATOR"),
    "awards_headers": build_user_headers("awards-1", "AWARDS_ADMIN"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "filmmaker_headers": build_user_headers("test-filmmaker-1", "FILMMAKER"),
    "programmer_headers": build_user_headers("test-programmer-1", "PROGRAMMER"),
    "juror_headers": build_user_headers("test-juror-1", "JUROR"),
}


def make_filmmaker_headers(submitter_id: str) -> dict:
    """FILMMAKER is entity-backed by Submitter: pass the Submitter.id."""
    return build_user_headers(submitter_id, "FILMMAKER")


def make_programmer_headers(programmer_id: str) -> dict:
    """PROGRAMMER is entity-backed by Programmer: pass the Programmer.id."""
    return build_user_headers(programmer_id, "PROGRAMMER")


def make_juror_headers(juror_id: str) -> dict:
    """JUROR is entity-backed by Juror: pass the Juror.id."""
    return build_user_headers(juror_id, "JUROR")
