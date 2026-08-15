"""Pre-built role headers for every role in the PRD (§2.1, §4).

GrowerMember and StationOperator are entity-backed: their X-User-ID is the id
of the acting Member / ReceivingStation resource, so ownership-gated calls MUST
use make_grower_headers(member["id"]) / make_station_operator_headers(station["id"])
with the real entity id. CoopAdmin, FieldOfficer, and PoolManager carry opaque
operator identifiers; the shared constants are their canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (bad-payload 400s, missing-resource 404s, wrong-role denials).
TEST_USERS = {
    "coop_admin_headers": build_user_headers("admin-1", "CoopAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "grower_headers": build_user_headers("test-grower-1", "GrowerMember"),
    "field_officer_headers": build_user_headers("officer-1", "FieldOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "station_operator_headers": build_user_headers("test-station-1", "StationOperator"),
    "pool_manager_headers": build_user_headers("pool-mgr-1", "PoolManager"),
}


def make_grower_headers(member_id: str) -> dict:
    """For GrowerMember (entity-backed by the Member resource). Pass the actual
    Member.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(member_id, "GrowerMember")


def make_station_operator_headers(station_id: str) -> dict:
    """For StationOperator (entity-backed by the ReceivingStation resource).
    Pass the actual ReceivingStation.id whenever the call is gated on the
    delivery's receiving_station_id (PRD §2.1)."""
    return build_user_headers(station_id, "StationOperator")


def make_coop_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "CoopAdmin")


def make_field_officer_headers(user_id: str = "officer-1") -> dict:
    return build_user_headers(user_id, "FieldOfficer")


def make_pool_manager_headers(user_id: str = "pool-mgr-1") -> dict:
    return build_user_headers(user_id, "PoolManager")
