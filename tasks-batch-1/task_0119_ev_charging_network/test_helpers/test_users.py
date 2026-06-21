"""Pre-built role headers for every role in the PRD (§2.1).

- CPOOperator and StationController are opaque actors: their X-User-ID is not
  tied to any entity, so the shared constants are the canonical form.
- Driver is entity_backed: ownership of a Reservation/ChargingSession is enforced
  by X-User-ID == resource.driver_id. Any ownership-gated Driver call MUST use
  make_driver_headers(driver_id) with the real Driver.id; the shared constant is
  only safe for non-ownership tests (e.g., 403/401 negative tests).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "cpo_headers": build_user_headers("test-cpo-1", "CPOOperator"),
    "station_headers": build_user_headers("test-station-1", "StationController"),
    # entity_backed fallback — only for tests that do NOT exercise ownership.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id as user_id
    whenever the call is ownership-gated (reservation/session actions)."""
    return build_user_headers(user_id, "Driver")


def make_cpo_headers(user_id: str = "test-cpo-1") -> dict:
    return build_user_headers(user_id, "CPOOperator")


def make_station_headers(user_id: str = "test-station-1") -> dict:
    return build_user_headers(user_id, "StationController")
