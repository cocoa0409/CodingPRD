"""Pre-built role headers for every role in the PRD (Section 2.1).

Coordinator, Broker, and Auditor carry an opaque X-User-ID the server never
matches against any stored entity, so a shared constant is the canonical form
for them. Driver is entity-backed: X-User-ID must be the acting Driver row's id,
and leg ownership checks compare it against the trip's assigned_driver_id. For
Driver, always use make_driver_headers(driver_id) with the real Driver id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical (never ownership-gated by id).
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Driver (entity_backed): shared constant is a FALLBACK for non-ownership tests
    # only (e.g. 403-forbidden role tests, where no real Driver is involved).
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(driver_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id as the user id
    whenever the leg action is ownership-gated (PRD 2.1 / 3.5)."""
    return build_user_headers(driver_id, "Driver")
